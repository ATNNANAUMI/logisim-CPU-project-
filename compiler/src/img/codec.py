"""The compressed image format that gfx_image() (compiler/libc/gfx_image.c)
draws. Everything is 32-bit words:

    word 0      width, 1-256
    word 1      height, 1 or more
    word 2      k, the number of palette colours, 1-256, plus PACKED
                (0x10000) when the pixels are in the packed form (below)
    word 3      the palette index that is transparent, or -1 for none
    word 4...   the palette: k RGB565 colours, two per word, the first one
                in bits 31-16 (the last word's low half is 0 when k is odd)
    then        the pixels as a stream of bits, read from bit 31 of each
                word down to bit 0, then the next word

The pixels go row by row, top to bottom, each row left to right. The stream
is a list of tokens:

    0 i         one pixel of palette colour i, in b bits (b is the number of
                bits k-1 needs, at least 1: 1-2 colours 1 bit, 3-4 colours
                2, ..., 129-256 colours 8)
    1 kk n      n pixels, each one a copy of a neighbour:
                    kk = 00   the previous pixel (so a run of one colour;
                              it goes on into the next row like the pixels do)
                         01   the pixel above
                         10   the pixel above and to the left
                         11   the pixel above and to the right
                n is an Elias gamma code: as many 0 bits as n has bits after
                its top bit, then n from its top bit (a 1) down:
                1 = 1, 2 = 010, 3 = 011, 4 = 00100, 9 = 0001001
                A run can go on past the end of a row.

Neighbours outside the image (above the first row, left of the first
column, right of the last) count as palette colour 0, and so does the
"previous pixel" before the first one. The encoder sorts the palette by use,
so colour 0 is the most common one (usually the background).

The encoder is greedy: at each pixel it takes the longest of the four runs
when that is cheaper than writing the pixels one by one.

The packed form has no tokens: just each pixel's palette index, b bits
each. A picture with few runs (a dithered or noisy one) costs 1 + b bits a
pixel in tokens but b packed, so encode() writes both and keeps the
smaller: a picture is never bigger than b bits a pixel (black and white: 32
pixels a word).
"""

LITERAL = None
REPEAT, UP, UP_LEFT, UP_RIGHT = range(4)
HEADER_WORDS = 4
PACKED = 0x10000      # in word 2: the pixels are packed palette indices
MAX_WIDTH = 256       # GFX_IMAGE_MAX_WIDTH in gfx.h: the decoder keeps two rows
MAX_COLORS = 256
MAX_RUN_BITS = 24     # longest gamma code the decoder accepts: n < 2^25
MAX_RUN = (1 << MAX_RUN_BITS + 1) - 1


def index_bits(k):
    """Bits per palette index for k colours."""
    return max(1, (k - 1).bit_length())


def gamma_bits(n):
    """Length in bits of n's gamma code."""
    return 2 * n.bit_length() - 1


class BitWriter:
    def __init__(self):
        self.words = []
        self.value = 0      # bits not yet in a word, the oldest at the top
        self.count = 0

    def put(self, value, nbits):
        for shift in range(nbits - 1, -1, -1):
            self.value = self.value << 1 | (value >> shift) & 1
            self.count += 1
            if self.count == 32:
                self.words.append(self.value)
                self.value = self.count = 0

    def gamma(self, n):
        self.put(0, n.bit_length() - 1)
        self.put(n, n.bit_length())

    def finish(self):
        if self.count:
            self.words.append(self.value << (32 - self.count))
            self.value = self.count = 0
        return self.words


class BitReader:
    def __init__(self, words, pos):
        self.words, self.pos = words, pos
        self.bit = 0        # bits of words[pos] already read

    def get(self, nbits):
        value = 0
        for _ in range(nbits):
            if self.pos >= len(self.words):
                raise ValueError("the bit stream ends too early")
            value = value << 1 | (self.words[self.pos] >> (31 - self.bit)) & 1
            self.bit += 1
            if self.bit == 32:
                self.pos, self.bit = self.pos + 1, 0
        return value

    def gamma(self):
        zeros = 0
        while self.get(1) == 0:
            zeros += 1
            if zeros > MAX_RUN_BITS:
                raise ValueError("run length too long")
        return 1 << zeros | self.get(zeros)


def _neighbour_runs(indices, width, height):
    """For UP, UP_LEFT and UP_RIGHT: runs[kind][i] = how many pixels from
    pixel i on are equal to that neighbour (0 outside the image)."""
    n = width * height
    runs = {}
    for kind, dx in ((UP, 0), (UP_LEFT, -1), (UP_RIGHT, 1)):
        run = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            x = i % width + dx
            above = indices[i - width + dx] if i >= width and 0 <= x < width else 0
            run[i] = run[i + 1] + 1 if indices[i] == above else 0
        runs[kind] = run
    return runs


def encode_tokens(indices, width, height, k):
    """Greedy parse: [(LITERAL, index) or (kind, n)]."""
    b = index_bits(k)
    n = width * height
    runs = _neighbour_runs(indices, width, height)
    tokens = []
    i, previous = 0, 0
    while i < n:
        j = i
        while j < n and indices[j] == previous:
            j += 1
        lengths = [j - i, runs[UP][i], runs[UP_LEFT][i], runs[UP_RIGHT][i]]
        best = max(range(4), key=lambda kind: (lengths[kind], -kind))
        length = min(lengths[best], MAX_RUN)
        if length and 3 + gamma_bits(length) < length * (1 + b):
            tokens.append((best, length))
            i += length
            previous = indices[i - 1]
        else:
            previous = indices[i]
            tokens.append((LITERAL, previous))
            i += 1
    return tokens


def encode(indices, width, height, palette, transparent=None, form=None):
    """indices: one palette index per pixel, row by row. palette: RGB565
    colours (the transparent entry's colour is ignored). transparent: the
    index of the transparent entry, or None. form: "tokens" or "packed";
    None writes both and keeps the smaller (packed on a tie: it draws
    faster). Returns the words."""
    k = len(palette)
    if not 1 <= width <= MAX_WIDTH:
        raise ValueError(f"width {width}: must be 1-{MAX_WIDTH}")
    if height < 1:
        raise ValueError("height must be 1 or more")
    if not 1 <= k <= MAX_COLORS:
        raise ValueError(f"{k} palette colours: must be 1-{MAX_COLORS}")
    if len(indices) != width * height or not all(0 <= v < k for v in indices):
        raise ValueError("indices don't match the size or the palette")
    colors = [0 if i == transparent else c & 0xFFFF for i, c in enumerate(palette)]
    if k % 2:
        colors.append(0)
    if form not in (None, "tokens", "packed"):
        raise ValueError(f"unknown form {form!r}")
    header = [width, height, k, 0xFFFFFFFF if transparent is None else transparent]
    header += [colors[i] << 16 | colors[i + 1] for i in range(0, len(colors), 2)]
    b = index_bits(k)
    packed = tokens = None
    if form != "tokens":
        bits = BitWriter()
        for v in indices:
            bits.put(v, b)
        packed = bits.finish()
    if form != "packed":
        bits = BitWriter()
        for kind, value in encode_tokens(indices, width, height, k):
            if kind is LITERAL:
                bits.put(0, 1)
                bits.put(value, b)
            else:
                bits.put(4 | kind, 3)
                bits.gamma(value)
        tokens = bits.finish()
    if tokens is None or packed is not None and len(packed) <= len(tokens):
        header[2] |= PACKED
        return header + packed
    return header + tokens


def decode(words):
    """The reference decoder: (width, height, pixels), the pixels row by row
    as RGB565 colours, None where transparent. Works like gfx_image()."""
    if len(words) < HEADER_WORDS:
        raise ValueError("too short for the header")
    width, height, k, transparent = words[:HEADER_WORDS]
    packed = k & PACKED
    k &= ~PACKED
    if not 1 <= width <= MAX_WIDTH or height < 1 or not 1 <= k <= MAX_COLORS:
        raise ValueError("not an image: bad header")
    palette = [words[HEADER_WORDS + i // 2] >> (0 if i % 2 else 16) & 0xFFFF for i in range(k)]
    if transparent < k:
        palette[transparent] = None
    reader = BitReader(words, HEADER_WORDS + (k + 1) // 2)
    b = index_bits(k)
    n = width * height
    if packed:
        return width, height, [palette[reader.get(b)] for _ in range(n)]
    pixels = []
    while len(pixels) < n:
        if reader.get(1) == 0:
            pixels.append(palette[reader.get(b)])
            continue
        kind = reader.get(2)
        for _ in range(min(reader.gamma(), n - len(pixels))):
            i = len(pixels)
            if kind == REPEAT:
                pixels.append(pixels[-1] if pixels else palette[0])
                continue
            dx = (0, -1, 1)[kind - UP]
            x = i % width + dx
            pixels.append(pixels[i - width + dx] if i >= width and 0 <= x < width else palette[0])
    return width, height, pixels
