"""Checks for the image converter and gfx_image(). Run from the project root:

    python compiler/src/img/selftest.py

The last check builds a C program that draws images with gfx_image() and
compares the simulator's screen with what codec.decode() says.
"""

import contextlib
import io
import random
import re
import struct
import subprocess
import sys
import tempfile
import traceback
import zlib
from pathlib import Path

import codec
import imagefile
from palette import make_palette, to565, to888

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent / "cc"))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("img_cli", HERE / "__main__.py")
assert _spec is not None and _spec.loader is not None
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def round_trip(indices, width, height, k, transparent=None):
    """Both forms decode back; encode() keeps the smaller (packed on a tie)."""
    palette = [(i * 2654435761) & 0xFFFF for i in range(k)]
    expect = [None if i == transparent else palette[i] for i in indices]
    sizes = {}
    for form in ("tokens", "packed", None):
        words = codec.encode(indices, width, height, palette, transparent, form)
        assert codec.decode(words) == (width, height, expect), (width, height, k, form)
        assert bool(words[2] & codec.PACKED) == (form == "packed" or form is None
                                                 and sizes["packed"] <= sizes["tokens"])
        sizes[form] = len(words)
    assert sizes[None] == min(sizes["tokens"], sizes["packed"])
    return words


def shapes(width, height):
    """An image with flat areas, diagonals, stripes and noise (every token kind)."""
    rng = random.Random(width * 1000 + height)
    out = []
    for y in range(height):
        for x in range(width):
            if x + y < width // 2:
                v = 1                                   # a diagonal edge
            elif (x - y) % 7 == 0:
                v = 2                                   # lines going down-right
            elif (x + y) % 5 == 0:
                v = 3                                   # lines going down-left
            elif y % 9 < 2:
                v = 4                                   # horizontal stripes
            elif x > width * 3 // 4:
                v = rng.randrange(8)                    # noise
            else:
                v = 0
            out.append(v)
    return out


# ---------------------------------------------------------------- checks

def check_gamma():
    for n in [*range(1, 300), 1 << 20, (1 << 25) - 1]:
        w = codec.BitWriter()
        w.put(5, 3)
        w.gamma(n)
        r = codec.BitReader(w.finish(), 0)
        assert r.get(3) == 5 and r.gamma() == n, n
        assert codec.gamma_bits(n) == 2 * n.bit_length() - 1
    w = codec.BitWriter()
    w.gamma(9)
    assert w.finish() == [0b0001001 << 25]


def check_round_trip():
    rng = random.Random(1)
    for width, height in ((1, 1), (1, 9), (7, 3), (40, 30), (256, 3)):
        for k in (1, 2, 3, 16, 200, 256):
            noise = [rng.randrange(k) for _ in range(width * height)]
            round_trip(noise, width, height, k)
            round_trip(noise, width, height, k, transparent=k - 1)
            flat = [min(k - 1, v) for v in shapes(width, height)]
            round_trip(flat, width, height, k, transparent=0)
    tokens = codec.encode_tokens(shapes(40, 30), 40, 30, 8)
    kinds = {kind for kind, _ in tokens}
    assert kinds == {codec.LITERAL, codec.REPEAT, codec.UP, codec.UP_LEFT, codec.UP_RIGHT}, kinds
    # one colour: one run for the whole picture
    words = round_trip([0] * 128 * 128, 128, 128, 1)
    assert len(words) == codec.HEADER_WORDS + 1 + 1, words


def check_packed():
    """A noisy picture is packed: never more than b bits a pixel."""
    rng = random.Random(5)
    noise = [rng.randrange(2) for _ in range(128 * 128)]
    words = round_trip(noise, 128, 128, 2)
    assert words[2] == 2 | codec.PACKED and len(words) == codec.HEADER_WORDS + 1 + 512
    assert words[5] == int("".join(map(str, noise[:32])), 2)    # 32 pixels a word, first at the top
    words = round_trip([rng.randrange(16) for _ in range(100 * 7)], 100, 7, 16, transparent=3)
    assert words[2] & codec.PACKED and len(words) == codec.HEADER_WORDS + 8 + 100 * 7 * 4 // 32 + 1
    # a picture with runs stays in tokens
    words = round_trip(shapes(40, 30), 40, 30, 8)
    assert not words[2] & codec.PACKED


def check_bad_input():
    for args in (([0], 0, 1, [0]), ([0] * 257, 257, 1, [0]), ([0], 1, 1, []),
                 ([0] * 257, 1, 1, [0] * 257), ([3], 1, 1, [0, 0])):
        try:
            codec.encode(*args)
        except ValueError:
            continue
        raise AssertionError(f"no error for {args[1:3]}")
    try:
        codec.encode([0], 1, 1, [0], form="raw")
        raise AssertionError("no error for form='raw'")
    except ValueError:
        pass
    for words in ([], [0, 1, 1, -1], [1, 1, 300, -1], [1, 1, 1, -1, 0],
                  [1, 1, 1, -1, 0, 0x80000000, 0],       # too short; 29+ zeros
                  [1, 1, 0x20001, -1, 0, 0], [1, 2, 0x10002, -1, 0]):   # flags; packed too short
        try:
            codec.decode(words)
        except ValueError:
            continue
        raise AssertionError(f"no error for {words}")


def png_bytes(width, height, ctype, depth, rows, filters, plte=b"", trns=b""):
    """A PNG from raw (unfiltered) rows, each row filtered with its filter type."""
    bpp = max(1, imagefile.CHANNELS[ctype] * depth // 8)
    data, prev = b"", bytes(len(rows[0]))
    for row, f in zip(rows, filters):
        out = bytearray()
        for i, x in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up, corner = prev[i], prev[i - bpp] if i >= bpp else 0
            pa, pb, pc = abs(up - corner), abs(left - corner), abs(left + up - 2 * corner)
            paeth = left if pa <= pb and pa <= pc else up if pb <= pc else corner
            out.append((x - (0, left, up, (left + up) // 2, paeth)[f]) & 255)
        data += bytes([f]) + bytes(out)
        prev = row

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    head = struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, 0)
    extra = (chunk(b"PLTE", plte) if plte else b"") + (chunk(b"tRNS", trns) if trns else b"")
    return (imagefile.SIGNATURE + chunk(b"IHDR", head) + extra
            + chunk(b"IDAT", zlib.compress(data)) + chunk(b"IEND", b""))


def read(data):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.png"
        path.write_bytes(data)
        return imagefile.read_png(path)


def check_png():
    rng = random.Random(2)
    filters = [0, 1, 2, 3, 4, 4, 3, 1]
    # RGBA, every filter type
    rows = [bytes(rng.randrange(256) for _ in range(5 * 4)) for _ in range(8)]
    w, h, px = read(png_bytes(5, 8, 6, 8, rows, filters))
    assert (w, h) == (5, 8) and px == [tuple(r[i:i + 4]) for r in rows for i in range(0, 20, 4)]
    # 16-bit RGB with a tRNS colour
    rows = [bytes([0x12, 0x34, 0, 0, 0xFF, 0xFF, 1, 2, 3, 4, 5, 6]) for _ in range(2)]
    _, _, px = read(png_bytes(2, 2, 2, 16, rows, [1, 4], trns=b"\x12\x34\x00\x00\xff\xff"))
    assert px == [(0x12, 0, 0xFF, 0), (1, 3, 5, 255)] * 2, px
    # 2-bit palette with tRNS, 1-bit grey, grey + alpha
    plte = bytes([10, 20, 30, 40, 50, 60, 70, 80, 90, 1, 2, 3])
    _, _, px = read(png_bytes(5, 1, 3, 2, [bytes([0b00011011, 0b01000000])], [0],
                              plte=plte, trns=b"\x80"))
    assert px == [(10, 20, 30, 128), (40, 50, 60, 255), (70, 80, 90, 255), (1, 2, 3, 255),
                  (40, 50, 60, 255)], px
    _, _, px = read(png_bytes(9, 1, 0, 1, [bytes([0b10100000, 0b10000000])], [2]))
    assert [p[0] for p in px] == [255, 0, 255, 0, 0, 0, 0, 0, 255]
    _, _, px = read(png_bytes(2, 1, 4, 8, [bytes([7, 255, 9, 0])], [3]))
    assert px == [(7, 7, 7, 255), (9, 9, 9, 0)]
    # write_png -> read_png
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "w.png"
        imagefile.write_png(path, 2, 1, [(1, 2, 3), None], scale=2)
        assert imagefile.read_png(path) == (4, 2, [(1, 2, 3, 255)] * 2 + [(0, 0, 0, 0)] * 2
                                            + [(1, 2, 3, 255)] * 2 + [(0, 0, 0, 0)] * 2)
    for bad in (b"GIF89a", png_bytes(1, 1, 2, 8, [b"\0\0\0"], [0]).replace(
            b"IHDR" + struct.pack(">II", 1, 1) + b"\x08\x02\x00\x00\x00",
            b"IHDR" + struct.pack(">II", 1, 1) + b"\x08\x02\x00\x00\x01")):
        try:
            read(bad)
        except ValueError:
            continue
        raise AssertionError("no error for a bad file")


def check_resize():
    px = [(0, 0, 0, 255), (100, 0, 0, 255), (0, 0, 0, 0), (200, 0, 0, 255)]
    assert imagefile.resize(2, 2, px, 1, 1) == [(100, 0, 0, 191)]     # clear: no colour
    assert imagefile.resize(2, 2, px, 4, 2)[:4] == [px[0], px[0], px[1], px[1]]
    assert imagefile.resize(2, 2, px, 2, 2) is px
    assert cli.target_size(600, 300, None) == (256, 128)
    assert cli.target_size(300, 150, None) == (256, 128)
    assert cli.target_size(256, 256, None) == (256, 256)
    assert cli.target_size(100, 50, None) == (100, 50)
    assert cli.target_size(100, 50, cli.parse_size("x20")) == (40, 20)
    assert cli.target_size(100, 50, cli.parse_size("30x")) == (30, 15)
    assert cli.target_size(100, 50, cli.parse_size("7x9")) == (7, 9)


def check_palette():
    rng = random.Random(3)
    px = [(rng.randrange(256), rng.randrange(256), rng.randrange(256), 255) for _ in range(600)]
    pal, clear, idx, exact = make_palette(px, 30, 256)
    assert not exact and len(pal) <= 256 and clear is None
    pal, clear, idx, exact = make_palette(px, 30, 16, dither=True)
    assert not exact and len(pal) <= 16 and max(idx) < len(pal)
    # few colours: kept exactly, most used first, transparent one included
    few = [(255, 0, 0, 255)] * 5 + [(0, 0, 255, 255)] * 9 + [(9, 9, 9, 0)] * 2
    pal, clear, idx, exact = make_palette(few, 4, 3)
    assert exact and pal == [to565(0, 0, 255), to565(255, 0, 0), 0] and clear == 2
    assert idx == [1] * 5 + [0] * 9 + [2] * 2
    # reduced: the error stays small for a smooth gradient
    grad = [(x * 2, y * 2, 100, 255) for y in range(64) for x in range(64)]
    pal, _, idx, exact = make_palette(grad, 64, 32)
    error = max(abs(a - b) for p, i in zip(grad, idx) for a, b in zip(p[:3], to888(pal[i])))
    assert not exact and len(pal) <= 32 and error < 40, error
    assert to565(255, 255, 255) == 0xFFFF and to888(0xFFFF) == (255, 255, 255)
    assert to565(0x12, 0x34, 0x56) == ((0x12 & 0xF8) << 8 | (0x34 & 0xFC) << 3 | 0x56 >> 3)


def check_command_line():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        px = [(x * 8, 255 - x * 8, 0, 255 if x else 0) for _ in range(20) for x in range(30)]
        src = tmp / "my picture.png"
        imagefile.write_png(src, 30, 20, [None if p[3] == 0 else p[:3] for p in px])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert cli.main([str(src), "--size", "15x", "--colors", "8",
                             "--preview", str(tmp / "prev.png")]) == 0
        header = (tmp / "my picture.h").read_text()
        assert header.startswith(f"/* my picture.h - {cli.MARK}")
        assert "static const unsigned int my_picture[" in header and "15 x 10" in out.getvalue()
        words = [int(v, 16) for v in re.findall(r"0x([0-9A-F]{8}),", header)]
        w, h, pixels = codec.decode(words)
        assert (w, h) == (15, 10) and words[2] <= 8 and None in pixels
        assert imagefile.read_png(tmp / "prev.png")[:2] == (30, 20)
        # again (our own file: fine), then onto a file it didn't make (refused)
        with contextlib.redirect_stdout(io.StringIO()):
            assert cli.main([str(src), "--name", "pic"]) == 0
        assert "pic[" in (tmp / "my picture.h").read_text()
        (tmp / "mine.h").write_text("int x;\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert cli.main([str(src), "-o", str(tmp / "mine.h")]) == 1
            assert cli.main([str(src), "--colors", "0"]) == 1
            assert cli.main([str(tmp / "missing.png")]) == 1
        assert "not made by this tool" in err.getvalue()
        assert (tmp / "mine.h").read_text() == "int x;\n"


def check_c_decoder():
    """gfx_image() on the simulator draws what codec.decode() says, clipped
    on every side; transparent pixels keep what was under them."""
    import driver                       # compiler/src/cc

    rng = random.Random(4)
    noise = [rng.randrange(256) for _ in range(23 * 11)]
    images = {
        "shapes": (40, 30, shapes(40, 30), 8, 0, "tokens"),
        "noise": (23, 11, noise, 256, None, "tokens"),
        "one": (5, 4, [0] * 20, 1, None, "tokens"),
        "wide": (256, 3, [x // 3 % 4 for _ in range(3) for x in range(256)], 4, 3, "tokens"),
        "noise_p": (23, 11, noise, 256, 7, "packed"),
        "dots_p": (37, 19, [rng.randrange(2) for _ in range(37 * 19)], 2, 0, "packed"),
        "wide_p": (256, 2, [x % 5 for _ in range(2) for x in range(256)], 5, None, "packed"),
    }
    draws = [("shapes", 0, 0), ("noise", 10, 5), ("shapes", 100, 110), ("shapes", -20, -15),
             ("one", 60, 60), ("wide", -50, 70), ("noise", 120, -3), ("shapes", 200, 10),
             ("noise_p", 40, 40), ("dots_p", 100, 90), ("dots_p", -5, 120), ("wide_p", -100, 80),
             # past the right and bottom edges of the 256 x 256 screen
             ("shapes", 230, 240), ("noise", 250, -3), ("shapes", 300, 10), ("dots_p", -5, 250),
             ("wide", 10, 200), ("wide_p", 1, 255), ("one", 255, 255), ("one", 256, 0)]
    words = {}
    for name, (w, h, indices, k, clear, form) in images.items():
        palette = [rng.randrange(1, 0x10000) for _ in range(k)]
        words[name] = codec.encode(indices, w, h, palette, clear, form)
        assert bool(words[name][2] & codec.PACKED) == (form == "packed")
    lines = ["#include <gfx.h>", "#include <stdio.h>"]
    for name, data in words.items():
        lines.append(f"static const unsigned int {name}[] = {{{', '.join(map(str, data))}u}};")
    lines.append("static const unsigned int bad[] = {0, 1, 1, 0};")
    lines.append("int main(void)\n{")
    lines += [f"    printf(\"%d\", gfx_image({x}, {y}, {name}));" for name, x, y in draws]
    lines.append("    printf(\" %d %d\\n\", gfx_image(0, 0, bad), GFX_IMAGE_WIDTH(wide));")
    lines.append("    return 0;\n}")

    S = cli.SCREEN
    screen = [0] * (S * S)
    for name, x0, y0 in draws:
        w, h, pixels = codec.decode(words[name])
        for i, c in enumerate(pixels):
            x, y = x0 + i % w, y0 + i // w
            if c is not None and 0 <= x < S and 0 <= y < S:
                screen[y * S + x] = c

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "draw.c"
        path.write_text("\n".join(lines) + "\n")
        program, _ = driver.build([str(path)])
    cpu, out = driver.run_in_simulator(program.rom, "", 20_000_000)
    assert cpu.halted and out == "0" * len(draws) + " -1 256\n", out
    assert (cpu.bus.video.width, cpu.bus.video.height) == (S, S)
    wrong = [i for i in range(S * S) if cpu.bus.video.pixels[i] != screen[i]]
    assert not wrong, f"{len(wrong)} pixels differ, the first at {wrong[0] % S},{wrong[0] // S}"
    return f"{cpu.instructions} instructions"


def check_video():
    """video.py: each frame lands on the screen as the tool says (frame 0
    whole, the others only what changed); a folder of PNGs goes through the
    command line; video_player.c on the simulator ends on the last frame;
    and a real video through ffmpeg, when it is installed."""
    import driver                       # compiler/src/cc
    import video
    from palette import nearest

    w, h, n = 24, 16, 12

    def frame(t):                       # a gradient, and a yellow box moving down-right
        return [to565(255, 255, 0) if t <= x < t + 5 and t // 2 <= y < t // 2 + 4
                else to565(x * 10, y * 15, 80) for y in range(h) for x in range(w)]

    frames = [frame(t) for t in range(n)]
    words, starts, palette, screens = video.encode_video(frames, w, h, colors=8, tolerance=0)
    assert words[starts[0] + 3] == 0xFFFFFFFF          # frame 0: no transparent colour
    ends = starts[1:] + [len(words)]
    screen = [None] * (w * h)
    for i in range(n):
        assert codec.decode(words[starts[i]:ends[i]])[:2] == (w, h)
        for p, c in enumerate(codec.decode(words[starts[i]:ends[i]])[2]):
            if c is not None:
                screen[p] = c
        assert screen == screens[i], f"frame {i}"
        if i:
            assert ends[i] - starts[i] < ends[0] - starts[0], f"frame {i} isn't smaller"
    shades = [to888(c) for c in palette]
    assert screens[-1] == [palette[nearest(shades, to888(c))] for c in frames[-1]]

    player = HERE.parent.parent / "examples" / "c" / "graphics" / "video_player.c"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "frames").mkdir()
        for i, f in enumerate(frames):
            imagefile.write_png(tmp / "frames" / f"f{i:02d}.png", w, h, [to888(c) for c in f])
        out = tmp / "clip.h"
        with contextlib.redirect_stdout(io.StringIO()):
            assert video.main([str(tmp / "frames"), "-o", str(out), "--colors", "8",
                               "--tolerance", "0", "--fps", "50"]) == 0
        text = out.read_text()
        assert text.startswith(f"/* clip.h - {video.MARK}") and "#define VIDEO_FRAMES 12\n" in text
        program, _ = driver.build([str(player)], defines=[f'VIDEO="{out}"'])
        note = "ffmpeg not installed: no video file read"
        if video.shutil.which("ffmpeg"):
            clip = tmp / "test.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=duration=1:size=160x120:rate=25", str(clip)], check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                assert video.main([str(clip), "--fps", "5", "--size", "40x"]) == 0
            text = clip.with_suffix(".h").read_text()
            assert "#define VIDEO_FRAMES 5\n" in text and "#define VIDEO_HEIGHT 30\n" in text
            note = "and a 1 s video through ffmpeg"
    cpu, out = driver.run_in_simulator(program.rom, "", 1_000_000_000)
    assert cpu.halted and out.startswith("12 frames, ") and "(the video is 0.2 s)" in out, out
    S = cli.SCREEN
    x0, y0 = (S - w) // 2, (S - h) // 2
    expect = [0] * (S * S)
    for p, c in enumerate(screens[-1]):
        expect[(y0 + p // w) * S + x0 + p % w] = c
    wrong = [i for i in range(S * S) if cpu.bus.video.pixels[i] != expect[i]]
    assert not wrong, f"{len(wrong)} pixels differ, the first at {wrong[0] % S},{wrong[0] // S}"
    return note


CHECKS = [
    check_gamma,
    check_round_trip,
    check_packed,
    check_bad_input,
    check_png,
    check_resize,
    check_palette,
    check_command_line,
    check_c_decoder,
    check_video,
]


def run():
    failed = 0
    for check in CHECKS:
        name = check.__name__[len("check_"):]
        try:
            note = check()
            print(f"ok    {name}" + (f"  ({note})" if note else ""))
        except Exception:
            failed += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(CHECKS) - failed} of {len(CHECKS)} checks passed")
    return failed == 0


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
