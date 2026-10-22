"""Image converter: a PNG -> a compressed image for gfx_image() (gfx.h).
Run it from the project root:

    python compiler/src/img picture.png        -> picture.h next to the PNG

The .h holds `static const unsigned int picture[] = {...};` (in ROM once
compiled); a C program does `#include "picture.h"` and
`gfx_image(x, y, picture)`. The format is in codec.py.

Pictures bigger than the screen (128 x 128) are shrunk to fit unless --size
says otherwise. Up to 256 colours are kept exactly (as RGB565); more are
reduced to --colors (default 256). Fewer colours = smaller; --dither looks
smoother with few colours but compresses worse. Transparent pixels (alpha
below 128) are left out when drawing.
"""

import argparse
import re
import shlex
import sys
from pathlib import Path

import codec
import imagefile
from palette import make_palette, to888

SCREEN = 128
MARK = "made by compiler/src/img"       # in the first line: a file we may overwrite


def parse_size(text):
    m = re.fullmatch(r"(\d*)x(\d*)", text)
    if not m or not any(m.groups()):
        raise argparse.ArgumentTypeError(f"{text!r}: write WxH, Wx or xH (e.g. 64x48, 64x)")
    return tuple(int(v) if v else None for v in m.groups())


def target_size(width, height, size):
    """The size to convert to: --size (a missing side keeps the shape), or
    shrunk to fit the screen."""
    if size:
        w, h = size
        if w is None:
            w = max(1, round(width * h / height))
        if h is None:
            h = max(1, round(height * w / width))
        return w, h
    if width <= SCREEN and height <= SCREEN:
        return width, height
    scale = min(SCREEN / width, SCREEN / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def c_name(text):
    name = re.sub(r"\W", "_", text)
    return "_" + name if not name or name[0].isdigit() else name


def header_text(name, filename, source, command, width, height, k, words, note):
    lines = [
        f"/* {filename} - {MARK} from {source}",
        " *",
        f" *   {command}",
        " *",
        f" * {width} x {height} pixels, {k} colours{note}: {len(words)} words",
        f" * (one word per pixel would be {width * height}). Draw it with",
        f" *   gfx_image(x, y, {name});",
        " */",
        f"static const unsigned int {name}[{len(words)}] = {{",
    ]
    for i in range(0, len(words), 8):
        lines.append("    " + " ".join(f"0x{w:08X}," for w in words[i:i + 8]))
    lines.append("};")
    return "\n".join(lines) + "\n"


def main(argv=None):
    cli = argparse.ArgumentParser(
        prog="python compiler/src/img",
        description="Turn a PNG into a compressed image for gfx_image() (gfx.h).")
    cli.add_argument("picture", help="a PNG file")
    cli.add_argument("-o", "--output", help="the .h to write (default: the PNG's name, .h)")
    cli.add_argument("--name", help="the C array's name (default: from the output file name)")
    cli.add_argument("--size", type=parse_size, metavar="WxH",
                     help="resize to W x H pixels; Wx or xH keeps the shape "
                          "(default: shrink to fit 128 x 128)")
    cli.add_argument("--colors", type=int, default=256, metavar="N",
                     help="at most N colours, 1-256 (default 256)")
    cli.add_argument("--dither", action="store_true",
                     help="dither when colours have to be reduced")
    cli.add_argument("--preview", metavar="FILE.png",
                     help="also save the picture as the screen will show it (2x size)")
    args = cli.parse_args(argv)

    try:
        if not 1 <= args.colors <= codec.MAX_COLORS:
            raise ValueError(f"--colors {args.colors}: must be 1-{codec.MAX_COLORS}")
        src = Path(args.picture)
        out = Path(args.output) if args.output else src.with_suffix(".h")
        name = c_name(args.name or out.stem)
        if out.exists() and MARK not in out.read_text(errors="replace").split("\n", 1)[0]:
            raise ValueError(f"{out} exists and was not made by this tool: "
                             f"pick another name with -o")

        width, height, pixels = imagefile.read_png(src)
        w, h = target_size(width, height, args.size)
        if w > codec.MAX_WIDTH:
            raise ValueError(f"{w} pixels wide: gfx_image() takes at most {codec.MAX_WIDTH} "
                             f"(use --size)")
        pixels = imagefile.resize(width, height, pixels, w, h)
        palette, clear, indices, exact = make_palette(pixels, w, args.colors, args.dither)
        words = codec.encode(indices, w, h, palette, clear)
        if codec.decode(words) != (w, h, [None if i == clear else palette[i] for i in indices]):
            raise AssertionError("the encoded image does not decode back (a bug)")

        k = len(palette)
        note = "" if exact else f" (reduced{', dithered' if args.dither else ''})"
        if clear is not None:
            note += ", 1 of them transparent"
        if words[2] & codec.PACKED:
            b = codec.index_bits(k)
            note += f"; packed ({b} bit{'s' * (b > 1)} a pixel: fewer than with runs)"
        command = shlex.join(["python", "compiler/src/img", *(argv if argv is not None else sys.argv[1:])])
        out.write_text(header_text(name, out.name, src.name, command, w, h, k, words, note))

        resized = f", resized from {width} x {height}" if (w, h) != (width, height) else ""
        print(f"{out}: {name}, {w} x {h}{resized}, {k} colours{note}, {len(words)} words "
              f"({w * h / len(words):.1f} times smaller than one word per pixel)")
        if args.preview:
            shown = [None if i == clear else to888(palette[i]) for i in indices]
            imagefile.write_png(args.preview, w, h, shown, scale=2)
        return 0
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
