"""Colours: RGB565, and fitting an image into a palette of at most N colours
(median cut, then a few rounds of k-means; Floyd-Steinberg dithering if asked).
"""

from collections import Counter

WEIGHTS = (2, 4, 3)          # how much an error in r, g, b shows


def to565(r, g, b):
    """8-bit components -> RGB565, the low bits dropped like GFX_RGB() does
    (rounding instead splits the dark noise of photos into two levels, and
    the image gets much bigger)."""
    return (r & 0xF8) << 8 | (g & 0xFC) << 3 | b >> 3


def to888(c):
    """RGB565 -> 8-bit (r, g, b), the low bits filled the way the screen does."""
    r, g, b = c >> 11 & 31, c >> 5 & 63, c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def distance(p, q):
    return (WEIGHTS[0] * (p[0] - q[0]) ** 2 + WEIGHTS[1] * (p[1] - q[1]) ** 2
            + WEIGHTS[2] * (p[2] - q[2]) ** 2)


def nearest(colors, p):
    """Index of the colour in colors (888 tuples) closest to p."""
    best, best_d = 0, None
    for i, c in enumerate(colors):
        d = distance(c, p)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def median_cut(counts, n):
    """counts: {RGB565: pixels}. Splits the colours into at most n boxes,
    always the box with the widest spread times pixels, at its median."""
    boxes = [[(to888(c), k) for c, k in counts.items()]]
    while len(boxes) < n:
        best = None
        for i, box in enumerate(boxes):
            if len(box) < 2:
                continue
            total = sum(k for _, k in box)
            for axis in range(3):
                values = [c[axis] for c, _ in box]
                score = (max(values) - min(values)) * WEIGHTS[axis] * total
                if score and (best is None or score > best[0]):
                    best = (score, i, axis)
        if best is None:
            break
        _, i, axis = best
        box = sorted(boxes.pop(i), key=lambda e: e[0][axis])
        half, seen = sum(k for _, k in box) / 2, 0
        for cut, (_, k) in enumerate(box, 1):
            seen += k
            if seen >= half:
                break
        cut = min(max(cut, 1), len(box) - 1)
        boxes += [box[:cut], box[cut:]]
    return [_mean(box) for box in boxes]


def _mean(entries):
    total = sum(k for _, k in entries)
    return tuple(sum(c[axis] * k for c, k in entries) / total for axis in range(3))


def kmeans(counts, centers, rounds):
    """Moves each centre to the mean of the colours closest to it."""
    colors = [(to888(c), k) for c, k in counts.items()]
    for _ in range(rounds):
        groups = [[] for _ in centers]
        for entry in colors:
            groups[nearest(centers, entry[0])].append(entry)
        centers = [_mean(g) if g else c for g, c in zip(groups, centers)]
    return centers


def make_palette(pixels, width, max_colors=256, dither=False, rounds=3):
    """Fit pixels ((r, g, b, a) tuples, rows of width; alpha below 128 is
    transparent) into
    at most max_colors palette entries, the transparent one included.

    Returns (palette, transparent, indices, exact): palette = RGB565 colours,
    most used first (0 in the transparent entry); transparent = that entry's
    index or None; indices = one per pixel; exact = no colour was changed
    (beyond rounding to RGB565)."""
    colors = [None if p[3] < 128 else to565(*p[:3]) for p in pixels]
    has_clear = None in colors
    slots = max_colors - has_clear
    counts = Counter(c for c in colors if c is not None)
    if slots < 1 and counts:
        raise ValueError("no palette entry left for the colours (the transparent one takes one)")

    exact = len(counts) <= slots
    if exact:
        chosen = list(counts)
        mapped = colors
    else:
        centers = kmeans(counts, median_cut(counts, slots), rounds)
        chosen = sorted({to565(*(round(v) for v in c)) for c in centers})
        if dither:
            mapped = _dither(pixels, width, colors, chosen)
        else:
            shades = [to888(c) for c in chosen]
            best = {c: chosen[nearest(shades, to888(c))] for c in counts}
            mapped = [None if c is None else best[c] for c in colors]

    use = Counter(mapped)
    palette = sorted(use, key=lambda c: (-use[c], -1 if c is None else c))
    number = {c: i for i, c in enumerate(palette)}
    transparent = number.get(None)
    return ([0 if c is None else c for c in palette], transparent,
            [number[c] for c in mapped], exact)


def _dither(pixels, width, colors, chosen):
    """Floyd-Steinberg: each pixel's rounding error is passed on to the
    pixels right and below. Returns the chosen RGB565 colour per pixel."""
    shades = [to888(c) for c in chosen]
    cache = {}
    error = [[0.0, 0.0, 0.0] for _ in range(len(pixels) + width + 2)]
    out = []
    for i, p in enumerate(pixels):
        if colors[i] is None:
            out.append(None)
            continue
        want = [min(255, max(0, p[axis] + error[i][axis])) for axis in range(3)]
        key = to565(*(round(v) for v in want))
        if key not in cache:
            cache[key] = nearest(shades, to888(key))
        j = cache[key]
        out.append(chosen[j])
        got = shades[j]
        x = i % width
        for dx, dy, part in ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)):
            if 0 <= x + dx < width:
                e = error[i + dy * width + dx]
                for axis in range(3):
                    e[axis] += (want[axis] - got[axis]) * part / 16
    return out
