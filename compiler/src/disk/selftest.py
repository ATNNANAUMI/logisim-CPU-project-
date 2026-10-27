"""Checks for the disk tool and its filesystem (TFS1). Run from the project root:

    python compiler/src/disk/selftest.py
"""

import contextlib
import importlib.util
import io
import os
import random
import tempfile
import traceback
from pathlib import Path

import fs
from fs import FileSystem, FsError

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("disk_cli", HERE / "__main__.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

TMP = tempfile.TemporaryDirectory()


def new_disk(words=1 << 16, name="t.img"):
    path = os.path.join(TMP.name, name)
    return FileSystem.format(path, words)


def raises(text, call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except FsError as e:
        assert text in str(e), (text, str(e))
    else:
        raise AssertionError(f"no error ({text})")


def check_format():
    with new_disk(1 << 24) as disk:                  # 64 MB
        free = disk.free_blocks()
        assert free == disk.blocks - fs.fat_blocks(disk.blocks) - 2, free
        path = disk.path
    with open(path, "rb") as f:
        assert f.read(4) == b"TFS1"
    assert os.stat(path).st_blocks * 512 < 1 << 20, "not sparse"
    raises("at least", FileSystem.format, path, fs.BLOCK * 3)
    blank = os.path.join(TMP.name, "blank.img")
    with open(blank, "wb") as f:
        f.truncate(1 << 16)
    raises("not formatted", FileSystem, blank)


def check_text_round_trip():
    rng = random.Random(1)
    with new_disk() as disk:
        for n in (0, 1, 3, 4, 5, 1023, 1024, 1025, 3000):
            data = bytes(rng.randrange(256) for _ in range(n))
            disk.put(f"/t{n}", data)
            assert disk.get(f"/t{n}") == data, n
            node = disk.lookup(f"/t{n}")
            assert node.packed and node.length == n
            assert len(disk.chain(node.first)) == (n + 1023) // 1024
        disk.put("/plain.txt", b"read me on the PC")
        first = disk.lookup("/plain.txt").first
        start = first * fs.BLOCK * 4
        assert bytes(disk.map[start:start + 17]) == b"read me on the PC"


def check_binary_round_trip():
    with new_disk() as disk:
        data = bytes(range(256)) * 5 + b"\x01\x02"     # not a whole word: padded
        node = disk.put("/b", data, binary=True)
        assert not node.packed and node.length == (len(data) + 3) // 4
        assert disk.get("/b") == data + bytes(2)
        assert disk.read(node, 0, 1) == [0x03020100]


def check_overwrite_frees():
    with new_disk() as disk:
        free = disk.free_blocks()
        disk.put("/f", bytes(5000))
        assert disk.free_blocks() == free - 5
        disk.put("/f", b"small")
        assert disk.free_blocks() == free - 1 and disk.get("/f") == b"small"
        disk.remove("/f")
        assert disk.free_blocks() == free and disk.lookup("/f") is None


def check_directory_grows():
    with new_disk() as disk:
        for i in range(40):
            disk.put(f"/file{i}", f"number {i}".encode())
        root = disk.root()
        assert root.length == 40 * fs.ENTRY and len(disk.chain(root.first)) == 21
        assert all(disk.get(f"/file{i}") == f"number {i}".encode() for i in range(40))
        for i in range(0, 40, 2):
            disk.remove(f"/file{i}")
        disk.put("/again", b"x")                     # reuses the first free entry
        assert disk.root().length == 40 * fs.ENTRY and disk.lookup("/again").index == 0
        assert len(disk.entries(disk.root())) == 21


def check_subdirectories():
    with new_disk() as disk:
        disk.mkdir("/a")
        disk.mkdir("a/b")
        disk.mkdir("/a/b/c")
        disk.put("/a/b/c/../f.txt", b"in b")
        assert disk.get("/a/./b/f.txt") == b"in b"
        assert disk.lookup("/../a").is_dir
        raises("not empty", disk.remove, "/a/b", directory=True)
        raises("is a directory", disk.remove, "/a/b")
        raises("is not a directory", disk.remove, "/a/b/f.txt", directory=True)
        raises("no such directory", disk.put, "/x/y", b"")
        raises("already exists", disk.mkdir, "/a/b")
        raises("inside", disk.rename, "/a", "/a/b/c/a")
        disk.rename("/a/b/f.txt", "/moved.txt")
        assert disk.get("/moved.txt") == b"in b" and disk.lookup("/a/b/f.txt") is None
        disk.rename("/a/b", "/b2")
        assert disk.lookup("/b2/c").is_dir
        disk.remove("/b2/c", directory=True)
        assert disk.entries(disk.lookup("/b2")) == []


def check_names():
    with new_disk() as disk:
        disk.put("/" + "n" * fs.MAX_NAME, b"long")
        assert disk.get("/" + "n" * fs.MAX_NAME) == b"long"
        raises("1 to 127", disk.put, "/" + "n" * (fs.MAX_NAME + 1), b"")
        raises("no '/', spaces", disk.put, "/a b", b"")
        raises("no '/', spaces", disk.mkdir, "/tab\there")
        raises("no name", disk.put, "/", b"")


def check_disk_full():
    with new_disk(fs.BLOCK * 8) as disk:             # 8 blocks: 3 for the system, 5 free
        assert disk.free_blocks() == 5
        disk.put("/f", bytes(4 * 1024))               # 4 blocks
        raises("disk full", disk.put, "/g", bytes(2 * 1024))


def check_command_line():
    img = os.path.join(TMP.name, "cli.img")
    host = os.path.join(TMP.name, "hello.txt")
    Path(host).write_text("hi from the PC\n")

    def run(*args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(args))
        return code, out.getvalue()

    assert run("format", img, "--size", "1")[0] == 0
    assert "already a disk" in run("format", img, "--size", "1")[1]
    assert run("mkdir", img, "/docs")[0] == 0
    assert run("put", img, host, "/docs")[1].strip() == "/docs/hello.txt: 15 chars"
    code, text = run("ls", img, "docs")
    assert code == 0 and text.split() == ["15", "chars", "hello.txt"], text
    out = os.path.join(TMP.name, "back.txt")
    run("get", img, "/docs/hello.txt", out)
    assert Path(out).read_text() == "hi from the PC\n"
    assert "no such file" in run("rm", img, "/nothing")[1]
    assert "free" in run("df", img)[1]
    assert "no such disk image" in run("ls", os.path.join(TMP.name, "none.img"))[1]


CHECKS = [
    check_format,
    check_text_round_trip,
    check_binary_round_trip,
    check_overwrite_frees,
    check_directory_grows,
    check_subdirectories,
    check_names,
    check_disk_full,
    check_command_line,
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
