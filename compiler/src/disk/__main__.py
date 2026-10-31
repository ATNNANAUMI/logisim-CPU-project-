"""Disk tool: makes and edits disk images (TFS1, see fs.py) from the PC.
Run it from the project root:

    python compiler/src/disk format disk.img [--size MB]   new empty disk (default 64 MB, sparse)
    python compiler/src/disk ls disk.img [PATH]           list a directory
    python compiler/src/disk put disk.img HOST [PATH] [--binary]   copy a file in
    python compiler/src/disk get disk.img PATH [HOST]     copy a file out (HOST - = the terminal)
    python compiler/src/disk cat disk.img PATH            print a file
    python compiler/src/disk rm disk.img PATH             delete a file
    python compiler/src/disk mkdir disk.img PATH          make a directory
    python compiler/src/disk rmdir disk.img PATH          delete an empty directory
    python compiler/src/disk mv disk.img OLD NEW          rename or move
    python compiler/src/disk df disk.img                  free space
    python compiler/src/disk fsck disk.img                check that every block is in one file

Paths on the disk start at the root ("/notes/a.txt"; a leading "/" is
optional). put stores a text file (4 chars a word) unless --binary, which
stores the host file's bytes as little-endian words (a program built with
`cc build --exe` is always stored that way); PATH defaults to the
host file's name in the root, and a PATH that is a directory puts it there.
"""

import argparse
import os
import sys
from pathlib import Path

import fs
from fs import FileSystem, FsError

MB = 1 << 20

EXE_MAGIC = b"TEX1"         # a program for the OS (compiler/libc/spawn.c)


def size_text(node):
    if node.is_dir:
        return "dir"
    return f"{node.length} {'chars' if node.packed else 'words'}"


def cmd_format(args):
    if os.path.exists(args.image) and os.path.getsize(args.image) and not args.force:
        try:
            FileSystem(args.image).close()
            what = "already a disk"
        except FsError:
            what = "not a disk image"
        raise FsError(f"{args.image} is {what}: --force to overwrite it")
    words = int(args.size * MB) // 4
    with FileSystem.format(args.image, words) as disk:
        print(f"{args.image}: {disk.blocks} blocks of {fs.BLOCK} words, "
              f"{disk.free_blocks()} free")


def cmd_ls(disk, args):
    node = disk.lookup(args.path)
    if node is None:
        raise FsError(f"{args.path}: no such file or directory")
    nodes = disk.entries(node) if node.is_dir else [node]
    for n in sorted(nodes, key=lambda n: n.name):
        print(f"{size_text(n):>16}  {n.name}{'/' if n.is_dir else ''}")


def cmd_put(disk, args):
    data = Path(args.host).read_bytes()
    path = args.path or "/" + Path(args.host).name
    target = disk.lookup(path)
    if target is not None and target.is_dir:
        path = path.rstrip("/") + "/" + Path(args.host).name
    binary = args.binary or data[:4] == EXE_MAGIC
    node = disk.put(path, data, binary=binary)
    print(f"{path}: {size_text(node)}")


def cmd_get(disk, args):
    data = disk.get(args.path)
    if args.host == "-":
        sys.stdout.buffer.write(data)
        return
    host = args.host or fs.split(args.path)[-1]
    Path(host).write_bytes(data)
    print(f"{host}: {len(data)} bytes")


def cmd_cat(disk, args):
    sys.stdout.buffer.write(disk.get(args.path))


def cmd_df(disk, _args):
    free = disk.free_blocks()
    print(f"{disk.blocks} blocks of {fs.BLOCK} words, {disk.blocks - free} used, "
          f"{free} free ({free * fs.BLOCK * 4 // 1024} KB)")


def main(argv=None):
    cli = argparse.ArgumentParser(prog="python compiler/src/disk",
                                  description="make and edit TFS1 disk images")
    sub = cli.add_subparsers(dest="command", required=True)

    def command(name, help_text, *paths):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("image", help="the disk image file")
        for path in paths:
            p.add_argument(path)
        return p

    p = command("format", "make an empty disk")
    p.add_argument("--size", type=float, default=64, help="size in MB (default 64)")
    p.add_argument("--force", action="store_true", help="overwrite an existing file (a disk or not)")
    command("ls", "list a directory").add_argument("path", nargs="?", default="/")
    p = command("put", "copy a file from the PC onto the disk", "host")
    p.add_argument("path", nargs="?")
    p.add_argument("--binary", action="store_true", help="store words, not packed text")
    p = command("get", "copy a file from the disk to the PC", "path")
    p.add_argument("host", nargs="?")
    command("cat", "print a file", "path")
    command("rm", "delete a file", "path")
    command("mkdir", "make a directory", "path")
    command("rmdir", "delete an empty directory", "path")
    command("mv", "rename or move", "old", "new")
    command("df", "free space")
    command("fsck", "check the disk's consistency")
    args = cli.parse_args(argv)

    try:
        if args.command == "format":
            cmd_format(args)
            return 0
        with FileSystem(args.image) if os.path.exists(args.image) else _missing(args.image) as disk:
            if args.command == "ls":
                cmd_ls(disk, args)
            elif args.command == "put":
                cmd_put(disk, args)
            elif args.command == "get":
                cmd_get(disk, args)
            elif args.command == "cat":
                cmd_cat(disk, args)
            elif args.command == "rm":
                disk.remove(args.path)
            elif args.command == "mkdir":
                disk.mkdir(args.path)
            elif args.command == "rmdir":
                disk.remove(args.path, directory=True)
            elif args.command == "mv":
                disk.rename(args.old, args.new)
            elif args.command == "df":
                cmd_df(disk, args)
            elif args.command == "fsck":
                problems = disk.check()
                for problem in problems:
                    print(problem)
                print(f"{len(problems)} problem(s)")
                return 1 if problems else 0
        return 0
    except (FsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _missing(image):
    raise FsError(f"{image}: no such disk image (make one with: "
                  f"python compiler/src/disk format {image})")


if __name__ == "__main__":
    sys.exit(main())
