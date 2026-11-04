#!/usr/bin/env python3
"""A disk for the OS (tynix/kernel.c): python tynix/make_disk.py [IMG] [--new] [--size MB]

Makes the image (default tynix/disk.img, git-ignored like every *.img) when it
is missing or --new is given: TFS1, 64 MB, sparse. Then it builds the shell
(tynix/shell.c) as /bin/sh, which the kernel starts at boot, and every
program in PROGRAMS with `cc build --exe` and puts it in /bin under its
own name, replacing the old copy, and writes /readme.txt. Other files on
the disk are kept, so what was written from the OS survives a rebuild. From the
command line it also makes a Linux-like /home/user (Desktop, Documents,
Downloads, Music, Pictures, Videos, and Documents/welcome.txt), /tmp,
where visual_file_manager starts, and /etc/profile (the shell runs it at
start: PATH=/bin:/home/user/bin); make(..., home=False) leaves them out.

    python tynix/make_disk.py
    python cpu_sim/src/main.py compiler/ROM/kernel.rom --disk tynix/disk.img
    (after: python compiler/src/cc build tynix/kernel.c)
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
OS_DIR = ROOT / "tynix"                    # kernel.c, shell.c; the other OS programs are in bin/
DEFAULT_IMAGE = ROOT / "tynix" / "disk.img"

# compiler/examples/c/*/NAME.c -> /bin/NAME. Each one ends by itself, on
# Ctrl-D or on q, so the shell gets the CPU back.
PROGRAMS = ["echo", "hello", "primes", "structs", "guess", "gfx_demo", "image_demo",
            "snake", "stackfall", "maze3d", "game_of_life", "grapher", "qr", "disk_notes", "ed", "edit",
            "more", "grep", "find", "tree", "du", "diff", "hexdump", "calc",
            "visual_file_manager", "claude", "basic"]
SOURCES = {"sh": "shell"}               # /bin/sh is tynix/shell.c
REGIONS = {"diff": 0x140000}            # RAM a program asks for (cc build --exe --region):
                                        # diff's table of 1001 x 1001 words does not fit in 1M

README = """\
This disk was made by tynix/make_disk.py for Tynix (tynix/kernel.c, which
starts the shell, /bin/sh from tynix/shell.c).

  help             the commands, and the programs in /bin
  Up, Down, Tab    the last lines again; complete a command or a path
  ls -l /bin       the programs (cc build --exe), sizes in words
  primes           runs /bin/primes; its exit status comes back
  cat > todo.txt   type lines, then Ctrl-D: a new text file
  disk_notes       shows /notes.txt and adds the lines you type
  ed notes.txt     edit a text file by lines (h lists its commands)
  cd /home/user    your home folder (Documents, Downloads, ...)
  edit notes.txt   full-screen editor on the RGB screen (^G lists the keys)
  cp from to       copy a file, text or program
  more /readme.txt  a page at a time (space: page, Enter: line, q)
  grep -n disk /readme.txt   the lines with a word (-i -v too; a folder works)
  find / txt       paths whose name contains txt
  tree /           the folders and files as a tree (-s: sizes)
  du /bin          disk KB of each folder (-a: files too)
  diff a.txt b.txt   what changed between two text files
  hexdump /readme.txt   the values in hex
  basic /home/user/basic/fizzbuzz.bas   a BASIC program (basic alone: type lines, RUN, LIST)
  calc 0x1100000 + 256   integer calculator (calc alone: a line at a time)
  ed notes.txt < edits.txt   a file as a program's input (cat < f too)
  export X=1       a variable for the programs (echo $X; set: the shell's
                   own; env lists them); /etc/profile runs at start, PATH
                   lists the folders searched for a command
  primes > p.txt &   runs in the background; jobs lists what runs,
                   fg N brings one forward, kill N ends it
  Esc              (the NMI) on the program in front: kill, continue,
                   background, or the list of tasks
  ls /bin | grep e   a pipe: both run at once (; && || work too)
  for f in /bin/*; do echo $f; done   loops, if, case, functions: a
                   small sh (tynix/README.md in the repository)
  sh FILE ARGS     a script (#!/bin/sh first: runs by its name too);
                   run FILE: in this shell; alias ll='ls -l'
  claude           talk to Claude (on the PC, through device 0x9C: needs
                   an API key there); claude QUESTION asks once

On the RGB screen (the simulator window's tab): snake, maze3d (a 3D maze:
W S A D Q E M R X), stackfall
(falling blocks with gravity chains) and game_of_life (q quits), gfx_demo, image_demo, grapher and qr
(Ctrl-D quits these two), and visual_file_manager (j k h l move, space
select, y x p copy cut paste, u clear, r d a rename delete new folder,
~ home, q quits).
"""


# a Linux-like home: /home/user with the usual folders, and /tmp (made only when asked, and
# only what is missing, so files already there stay)
HOME_FOLDERS = ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"]
WELCOME = """\
Welcome to Tynix.

This is your home folder, /home/user. visual_file_manager starts here
(~ comes back to it), and `cd /home/user` gets the shell here.
"""


# run by the shell at start (`run /etc/profile`): settings kept on the disk
PROFILE = """\
# /etc/profile: the shell runs these lines when it starts (not sh -c).
# export NAME=value passes a variable to every program; set NAME=value
# keeps it in the shell. PATH: the folders searched for a command (make
# /home/user/bin for programs of your own).
export PATH=/bin:/home/user/bin
"""


def make_home(disk):
    for folder in ("/home", "/home/user", "/tmp", *(f"/home/user/{n}" for n in HOME_FOLDERS)):
        if disk.lookup(folder) is None:
            disk.mkdir(folder)
    if disk.lookup("/home/user/Documents/welcome.txt") is None:
        disk.put("/home/user/Documents/welcome.txt", WELCOME.encode())
    if disk.lookup("/home/user/basic") is None:
        disk.mkdir("/home/user/basic")
    for sample in sorted((OS_DIR / "basic").glob("*.bas")):     # BASIC programs to run: basic /home/user/basic/NAME
        if disk.lookup(f"/home/user/basic/{sample.name}") is None:
            disk.put(f"/home/user/basic/{sample.name}", sample.read_bytes())


def make_profile(disk):
    """/etc/profile, unless one is there (it is the user's to change)."""
    if disk.lookup("/etc") is None:
        disk.mkdir("/etc")
    if disk.lookup("/etc/profile") is None:
        disk.put("/etc/profile", PROFILE.encode())


def make(image=DEFAULT_IMAGE, programs=PROGRAMS, new=False, size_mb=64, log=print, home=False):
    """Make or update the disk image; returns {name: words} of the programs.
    home: also make /home/user (Desktop, Documents, ... Videos), /tmp and
    /etc/profile (each kept when it is there)."""
    image = Path(image)
    if new or not image.exists():
        fs.FileSystem.format(str(image), size_mb * 1024 * 1024 // 4).close()
        log(f"{image}: formatted, {size_mb} MB")
    sizes = {}
    with fs.FileSystem(str(image)) as disk:
        if disk.lookup("/bin") is None:
            disk.mkdir("/bin")
        for name in ["sh"] + [p for p in programs if p != "sh"]:
            source = OS_DIR / (f"{SOURCES[name]}.c" if name in SOURCES else f"bin/{name}.c")
            if not source.exists():                            # not one of the OS's own programs
                found = sorted(EXAMPLES.rglob(f"{name}.c"))
                if len(found) != 1:
                    raise fs.FsError(f"{name}.c: found {len(found)} times under compiler/examples/c")
                source = found[0]
            program, _ = driver.build([str(source)], exe=True)
            disk.put(f"/bin/{name}", driver.exe_bytes(program, REGIONS.get(name, 0)), binary=True)
            sizes[name] = len(program.rom)
            log(f"/bin/{name}: {len(program.rom)} words")
        disk.put("/readme.txt", README.encode())
        if home:
            make_home(disk)
            make_profile(disk)
        log(f"{disk.free_blocks()} of {disk.blocks} blocks free")
    return sizes


def main(argv=None):
    p = argparse.ArgumentParser(description="Make or update the OS's disk image.")
    p.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE))
    p.add_argument("--new", action="store_true", help="format it again (its files are lost)")
    p.add_argument("--size", type=int, default=64, help="size in MB when formatting (default 64)")
    args = p.parse_args(argv)
    try:
        make(args.image, new=args.new, size_mb=args.size, home=True)
    except (fs.FsError, driver.BuildError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
