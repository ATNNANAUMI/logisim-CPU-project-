"""Video converter: a video (or a folder of PNG frames) -> a .h holding every
frame compressed for gfx_image(), which compiler/examples/c/graphics/video_player.c
plays at the video's own speed (it waits on clock(), the timer). Run it from
the project root:

    python compiler/src/img/video.py clip.mp4             -> clip.h next to it
    python compiler/src/img/video.py frames/ --fps 12     (PNGs, in name order)

ffmpeg (it has to be installed) reads the video at --fps frames a second
(default 10), shrunk to fit the 128 x 128 screen unless --size says
otherwise; --start and --seconds take a part of it. All frames share one
palette of --colors colours (default 32), so a pixel that keeps its colour
keeps its palette entry. Frame 0 is drawn whole. Every later frame draws
only the pixels whose colour moved by more than --tolerance since the
screen showed them: the rest are transparent, and a run of those costs a
few bits. Each frame is then an ordinary picture in the format of codec.py
(its own palette holds just the colours it draws, transparent first).

A player has to draw every frame in order (each one builds on the screen
the others left), so one that falls behind can't skip ahead; it catches up
when the frames get cheaper.

The .h holds:

    #define VIDEO_FRAMES, VIDEO_FPS, VIDEO_WIDTH, VIDEO_HEIGHT
    static const unsigned int video_data[];     every frame, one after another
    static const unsigned int video_start[];    where frame i starts in video_data

--preview DIR also saves each frame as the screen will show it, as PNGs.
"""

import argparse
import importlib.util
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import codec
import imagefile
from palette import WEIGHTS, distance, fit_colors, nearest, to565, to888

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("img_cli", HERE / "__main__.py")
assert _spec is not None and _spec.loader is not None
img_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(img_cli)

MARK = "made by compiler/src/img/video.py"   # in the first line: a file we may overwrite
ROM_WORDS = 1 << 24                          # linker.ROM_SIZE


# ------------------------------------------------------------------ reading
def probe(path):
    """(width, height) of the video's first video stream, from ffprobe."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
                          str(path)], capture_output=True, text=True)
    try:
        w, h = out.stdout.split()[0].split("x")
        return int(w), int(h)
    except (IndexError, ValueError):
        raise ValueError(f"{path}: ffprobe found no video in it ({out.stderr.strip()})")


def read_video(path, fps, size, start=None, seconds=None, max_frames=None):
    """The frames as (width, height, [frame, ...]), a frame being one RGB565
    colour per pixel, row by row. ffmpeg does the decoding and the scaling."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("ffmpeg and ffprobe are needed to read a video "
                         "(Arch: sudo pacman -S ffmpeg), or give a folder of PNG frames")
    w, h = img_cli.target_size(*probe(path), size)
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(path)]
    if seconds is not None:
        cmd += ["-t", str(seconds)]
    if max_frames is not None:
        cmd += ["-frames:v", str(max_frames)]
    cmd += ["-an", "-vf", f"fps={fps},scale={w}:{h}:flags=area",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    run = subprocess.run(cmd, capture_output=True)
    if run.returncode:
        raise ValueError(f"ffmpeg failed: {run.stderr.decode(errors='replace').strip()}")
    raw, step = run.stdout, w * h * 3
    frames = []
    for at in range(0, len(raw) - step + 1, step):
        b = raw[at:at + step]
        frames.append([(b[i] & 0xF8) << 8 | (b[i + 1] & 0xFC) << 3 | b[i + 2] >> 3
                       for i in range(0, step, 3)])
    return w, h, frames


def read_folder(folder, size, max_frames=None):
    """The same from a folder of PNGs (every *.png, in name order), each
    shrunk like the first one says. Transparent pixels count as black."""
    paths = sorted(Path(folder).glob("*.png"))[:max_frames]
    if not paths:
        raise ValueError(f"{folder}: no .png files in it")
    frames, w, h = [], None, None
    for path in paths:
        width, height, pixels = imagefile.read_png(path)
        if w is None:
            w, h = img_cli.target_size(width, height, size)
        pixels = imagefile.resize(width, height, pixels, w, h)
        frames.append([to565(r, g, b) if a >= 128 else 0 for r, g, b, a in pixels])
    return w, h, frames


# ----------------------------------------------------------------- encoding
def encode_video(frames, width, height, colors=32, tolerance=16):
    """The frames (RGB565 lists) as gfx_image() pictures. Returns (words,
    starts, palette, screens): starts[i] = where frame i begins in words,
    palette = the colours the frames share, screens[i] = what the screen
    shows after frame i (RGB565 per pixel)."""
    counts = Counter()
    for frame in frames:
        counts.update(frame)
    palette = fit_colors(counts, colors)
    shades = [to888(c) for c in palette]
    best = {c: nearest(shades, to888(c)) for c in counts}
    # same[a][b]: palette colour b may stay on the screen where a is due
    limit = tolerance * tolerance * sum(WEIGHTS)
    same = [[distance(p, q) <= limit for q in shades] for p in shades]

    words, starts, screens = [], [], []
    screen = None                      # palette index on the screen, per pixel
    for frame in frames:
        due = [best[c] for c in frame]
        if screen is None:             # frame 0: everything, nothing transparent
            drawn = due
            screen = list(due)
        else:
            drawn = []
            for i, (want, shown) in enumerate(zip(due, screen)):
                if same[want][shown]:
                    drawn.append(None)
                else:
                    drawn.append(want)
                    screen[i] = want
        # this frame's palette: transparent first (if any), then by use
        use = Counter(drawn)
        order = sorted(use, key=lambda v: (v is not None, -use[v], v or 0))
        number = {v: n for n, v in enumerate(order)}
        clear = number.get(None)
        frame_palette = [0 if v is None else palette[v] for v in order]
        picture = codec.encode([number[v] for v in drawn], width, height, frame_palette, clear)
        expect = [None if v is None else palette[v] for v in drawn]
        if codec.decode(picture) != (width, height, expect):
            raise AssertionError("a frame does not decode back (a bug)")
        starts.append(len(words))
        words += picture
        screens.append([palette[v] for v in screen])
    return words, starts, palette, screens


# ------------------------------------------------------------------- output
def header_text(filename, source, command, width, height, fps, palette, words, starts):
    source, command = (t.replace("*/", "* /") for t in (source, command))   # stay inside the comment
    frames = len(starts)
    lines = [
        f"/* {filename} - {MARK} from {source}",
        " *",
        f" *   {command}",
        " *",
        f" * {frames} frames of {width} x {height} at {fps} a second ({frames / fps:.1f} s),",
        f" * {len(palette)} colours: {len(words)} words, {len(words) / frames:.0f} a frame",
        f" * (one word per pixel would be {width * height} a frame). Play it with",
        " * compiler/examples/c/graphics/video_player.c (#include this file there).",
        " */",
        f"#define VIDEO_FRAMES {frames}",
        f"#define VIDEO_FPS {fps}",
        f"#define VIDEO_WIDTH {width}",
        f"#define VIDEO_HEIGHT {height}",
        "",
        f"static const unsigned int video_start[{frames}] = {{",
    ]
    for i in range(0, frames, 8):
        lines.append("    " + " ".join(f"{s}," for s in starts[i:i + 8]))
    lines += ["};", "", f"static const unsigned int video_data[{len(words)}] = {{"]
    for i in range(0, len(words), 8):
        lines.append("    " + " ".join(f"0x{w:08X}," for w in words[i:i + 8]))
    lines.append("};")
    return "\n".join(lines) + "\n"


def main(argv=None):
    cli = argparse.ArgumentParser(
        prog="python compiler/src/img/video.py",
        description="Turn a video into compressed frames for video_player.c (gfx_image).")
    cli.add_argument("video", help="a video file (read with ffmpeg) or a folder of PNG frames")
    cli.add_argument("-o", "--output", help="the .h to write (default: the video's name, .h)")
    cli.add_argument("--fps", type=int, default=10, help="frames a second, 1-60 (default 10)")
    cli.add_argument("--size", type=img_cli.parse_size, metavar="WxH",
                     help="frame size; Wx or xH keeps the shape (default: fit 128 x 128)")
    cli.add_argument("--colors", type=int, default=32, metavar="N",
                     help="colours shared by all frames, 1-255 (default 32)")
    cli.add_argument("--tolerance", type=int, default=16, metavar="T",
                     help="a pixel is redrawn when its colour moves by more than about T "
                          "(0-255, per channel) from what the screen shows (default 16; "
                          "0 = every change)")
    cli.add_argument("--start", type=float, metavar="SECONDS", help="start this far into the video")
    cli.add_argument("--seconds", type=float, help="take only this long a part")
    cli.add_argument("--max-frames", type=int, metavar="N", help="at most N frames")
    cli.add_argument("--preview", metavar="DIR",
                     help="also save every frame as the screen will show it (PNG, 2x size)")
    args = cli.parse_args(argv)

    try:
        if not 1 <= args.fps <= 60:
            raise ValueError(f"--fps {args.fps}: must be 1-60")
        if not 1 <= args.colors <= codec.MAX_COLORS - 1:      # one entry stays for transparent
            raise ValueError(f"--colors {args.colors}: must be 1-{codec.MAX_COLORS - 1}")
        if not 0 <= args.tolerance <= 255:
            raise ValueError(f"--tolerance {args.tolerance}: must be 0-255")
        src = Path(args.video)
        out = Path(args.output) if args.output else src.with_suffix(".h")
        if out.exists() and MARK not in out.read_text(errors="replace").split("\n", 1)[0]:
            raise ValueError(f"{out} exists and was not made by this tool: pick another name with -o")

        if src.is_dir():
            w, h, frames = read_folder(src, args.size, args.max_frames)
        else:
            w, h, frames = read_video(src, args.fps, args.size, args.start, args.seconds,
                                      args.max_frames)
        if not frames:
            raise ValueError(f"{src}: no frames (check --start and --seconds)")
        if w > codec.MAX_WIDTH:
            raise ValueError(f"{w} pixels wide: gfx_image() takes at most {codec.MAX_WIDTH} (use --size)")
        print(f"{src}: {len(frames)} frames of {w} x {h}, encoding...")
        words, starts, palette, screens = encode_video(frames, w, h, args.colors, args.tolerance)
        if len(words) > ROM_WORDS // 2:
            raise ValueError(f"{len(words)} words: more than half the ROM; use fewer --seconds, "
                             "a lower --fps, a smaller --size or fewer --colors")

        command = shlex.join(["python", "compiler/src/img/video.py",
                              *(argv if argv is not None else sys.argv[1:])])
        out.write_text(header_text(out.name, src.name, command, w, h, args.fps, palette,
                                   words, starts))
        print(f"{out}: {len(frames)} frames, {len(frames) / args.fps:.1f} s at {args.fps} fps, "
              f"{len(palette)} colours, {len(words)} words "
              f"({len(words) / len(frames):.0f} a frame, {w * h * len(frames) / len(words):.1f} "
              f"times smaller than one word per pixel)")
        if args.preview:
            folder = Path(args.preview)
            folder.mkdir(parents=True, exist_ok=True)
            for i, screen in enumerate(screens):
                imagefile.write_png(folder / f"frame_{i:04d}.png", w, h,
                                    [to888(c) for c in screen], scale=2)
            print(f"{folder}: {len(screens)} frames as PNG")
        return 0
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
