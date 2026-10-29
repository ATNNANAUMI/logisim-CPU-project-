#!/usr/bin/env python3
"""A disk for the OS (os/shell.c): python os/make_disk.py [IMG] [--new] [--size MB]

Makes the image (default os/disk.img, git-ignored like every *.img) when it
is missing or --new is given: TFS1, 64 MB, sparse. Then it builds every
program in PROGRAMS with `cc build --exe` and puts it in /bin under its
own name, replacing the old copy, and writes /readme.txt. Other files on
the disk are kept, so what was written from the OS survives a rebuild.

    python os/make_disk.py
    python cpu_sim/src/main.py compiler/ROM/shell.rom --disk os/disk.img
    (after: python compiler/src/cc build os/shell.c)
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "compiler" / "src" / "disk"))
sys.path.insert(0, str(ROOT / "compiler" / "src" / "cc"))
import fs                               # compiler/src/disk
import driver                           # compiler/src/cc

EXAMPLES = ROOT / "compiler" / "examples" / "c"      # in folders by kind (games/, os/, ...)
OS_DIR = ROOT / "os"
DEFAULT_IMAGE = ROOT / "os" / "disk.img"

# compiler/examples/c/*/NAME.c -> /bin/NAME. Each one ends by itself, on
# Ctrl-D or on q, so the shell gets the CPU back.
PROGRAMS = ["echo", "hello", "primes", "structs", "guess", "gfx_demo", "image_demo",
            "snake", "game_of_life", "grapher", "qr", "disk_notes", "ed"]

README = """\
This disk was made by os/make_disk.py for the shell in os/shell.c.

  help             the commands, and the programs in /bin
  ls -l /bin       the programs (cc build --exe), sizes in words
  primes           runs /bin/primes; its exit status comes back
  cat > todo.txt   type lines, then Ctrl-D: a new text file
  disk_notes       shows /notes.txt and adds the lines you type
  ed notes.txt     edit a text file by lines (h lists its commands)
  cp from to       copy a file, text or program

On the RGB screen (the simulator window's tab): snake and
game_of_life (q quits), gfx_demo, image_demo, grapher and qr
(Ctrl-D quits these two).
"""


def make(image=DEFAULT_IMAGE, programs=PROGRAMS, new=False, size_mb=64, log=print):
    """Make or update the disk image; returns {name: words} of the programs."""
    image = Path(image)
    if new or not image.exists():
        fs.FileSystem.format(str(image), size_mb * 1024 * 1024 // 4).close()
        log(f"{image}: formatted, {size_mb} MB")
    sizes = {}
    with fs.FileSystem(str(image)) as disk:
        if disk.lookup("/bin") is None:
            disk.mkdir("/bin")
        for name in programs:
            source = OS_DIR / f"{name}.c"           # the OS's own programs
            if not source.exists():
                found = sorted(EXAMPLES.rglob(f"{name}.c"))
                if len(found) != 1:
                    raise fs.FsError(f"{name}.c: found {len(found)} times under compiler/examples/c")
                source = found[0]
            program, _ = driver.build([str(source)], exe=True)
            disk.put(f"/bin/{name}", driver.exe_bytes(program), binary=True)
            sizes[name] = len(program.rom)
            log(f"/bin/{name}: {len(program.rom)} words")
        disk.put("/readme.txt", README.encode())
        log(f"{disk.free_blocks()} of {disk.blocks} blocks free")
    return sizes


def main(argv=None):
    p = argparse.ArgumentParser(description="Make or update the OS's disk image.")
    p.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE))
    p.add_argument("--new", action="store_true", help="format it again (its files are lost)")
    p.add_argument("--size", type=int, default=64, help="size in MB when formatting (default 64)")
    args = p.parse_args(argv)
    try:
        make(args.image, new=args.new, size_mb=args.size)
    except (fs.FsError, driver.BuildError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
