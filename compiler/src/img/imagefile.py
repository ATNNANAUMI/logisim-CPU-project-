"""PNG files in and out, and resizing. Standard library only (zlib).

Pixels are lists of (r, g, b, a) tuples, 0-255, row by row.
"""

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}      # PNG colour type -> samples per pixel


def read_png(path):
    """(width, height, pixels) from a PNG file: any colour type and bit
    depth, but not interlaced."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != SIGNATURE:
        raise ValueError(f"{path}: not a PNG file (convert it to PNG first)")
    pos, header, idat, plte, trns = 8, None, [], b"", None
    while pos + 8 <= len(data):
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + size]
        pos += 12 + size
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError(f"{path}: no IHDR chunk")
    width, height, depth, ctype, _, _, interlace = header
    if ctype not in CHANNELS or depth not in (1, 2, 4, 8, 16):
        raise ValueError(f"{path}: unknown PNG colour type {ctype} / bit depth {depth}")
    if interlace:
        raise ValueError(f"{path}: interlaced PNG: save it again without interlacing")
    raw = zlib.decompress(b"".join(idat))

    channels = CHANNELS[ctype]
    bpp = max(1, channels * depth // 8)              # filter unit, in bytes
    stride = (width * channels * depth + 7) // 8
    rows, prev, p = [], bytearray(stride), 0
    for _ in range(height):
        kind, line = raw[p], bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        _unfilter(kind, line, prev, bpp)
        rows.append(line)
        prev = line

    maxval = (1 << depth) - 1
    alpha_key = None                                  # tRNS for colour types 0 and 2
    if trns and ctype == 0:
        alpha_key = (struct.unpack(">H", trns[:2])[0],)
    elif trns and ctype == 2:
        alpha_key = struct.unpack(">HHH", trns[:6])
    pixels = []
    for line in rows:
        samples = _samples(line, width * channels, depth)
        for x in range(width):
            s = samples[x * channels:(x + 1) * channels]
            if ctype == 3:
                i = s[0]
                r, g, b = plte[3 * i:3 * i + 3] if 3 * i + 3 <= len(plte) else (0, 0, 0)
                a = trns[i] if trns and i < len(trns) else 255
                pixels.append((r, g, b, a))
                continue
            a = 255 if alpha_key is None or tuple(s) != alpha_key else 0
            if ctype in (4, 6):
                a = s[-1] * 255 // maxval
            v = [c * 255 // maxval for c in s]
            if ctype in (0, 4):
                pixels.append((v[0], v[0], v[0], a))
            else:
                pixels.append((v[0], v[1], v[2], a))
    return width, height, pixels


def _unfilter(kind, line, prev, bpp):
    if kind == 0:
        return
    if kind == 2:
        line[:] = bytes((a + b) & 255 for a, b in zip(line, prev))
        return
    for i in range(len(line)):
        left = line[i - bpp] if i >= bpp else 0
        if kind == 1:
            line[i] = (line[i] + left) & 255
        elif kind == 3:
            line[i] = (line[i] + (left + prev[i]) // 2) & 255
        elif kind == 4:
            up = prev[i]
            corner = prev[i - bpp] if i >= bpp else 0
            pa, pb, pc = abs(up - corner), abs(left - corner), abs(left + up - 2 * corner)
            pred = left if pa <= pb and pa <= pc else up if pb <= pc else corner
            line[i] = (line[i] + pred) & 255
        else:
            raise ValueError(f"unknown PNG filter type {kind}")


def _samples(line, count, depth):
    if depth == 8:
        return list(line[:count])
    if depth == 16:
        return [line[2 * i] << 8 | line[2 * i + 1] for i in range(count)]
    per_byte, mask = 8 // depth, (1 << depth) - 1
    return [line[i // per_byte] >> (8 - depth * (i % per_byte + 1)) & mask for i in range(count)]


def write_png(path, width, height, pixels, scale=1):
    """pixels: (r, g, b) tuples, or None for transparent."""
    rows = []
    for y in range(height):
        line = bytearray()
        for p in pixels[y * width:(y + 1) * width]:
            line += bytes((0, 0, 0, 0) if p is None else (*p, 255)) * scale
        rows += [b"\0" + bytes(line)] * scale

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body)))

    head = struct.pack(">IIBBBBB", width * scale, height * scale, 8, 6, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(SIGNATURE + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(b"".join(rows)))
                + chunk(b"IEND", b""))


def resize(width, height, pixels, new_width, new_height):
    """Area average (each new pixel is the mean of the old ones under it;
    colours weighted by alpha). Enlarging repeats pixels."""
    if (new_width, new_height) == (width, height):
        return pixels
    xs = [(x * width // new_width, max(x * width // new_width + 1, (x + 1) * width // new_width))
          for x in range(new_width)]
    out = []
    for y in range(new_height):
        y0 = y * height // new_height
        y1 = max(y0 + 1, (y + 1) * height // new_height)
        for x0, x1 in xs:
            r = g = b = a = n = 0
            for yy in range(y0, y1):
                row = yy * width
                for p in pixels[row + x0:row + x1]:
                    r += p[0] * p[3]
                    g += p[1] * p[3]
                    b += p[2] * p[3]
                    a += p[3]
                    n += 1
            out.append((r // a, g // a, b // a, a // n) if a else (0, 0, 0, 0))
    return out
