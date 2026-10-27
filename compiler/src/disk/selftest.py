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


def check_fsck():
    with new_disk() as disk:
        disk.mkdir("/d")
        disk.put("/d/f", bytes(3000))
        assert disk.check() == []
        f = disk.lookup("/d/f")
        disk.set_fat(disk.alloc(), fs.END)              # a block nobody owns
        disk.set_fat(disk.chain(f.first)[-1], disk.root().first)   # a chain into the root
        problems = "\n".join(disk.check())
        assert "leaked" in problems and "in /d/f and in /" in problems, problems


C_PROGRAM = r"""
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <unistd.h>

int main(void)
{
    char line[300];
    unsigned words[4];
    int c, n = 0, sum = 0, a, b;
    float x;
    FILE *f = fopen("/in.txt", "r");
    DIR *d;
    struct dirent *e;
    while ((c = fgetc(f)) != EOF) {
        n++;
        sum += c;
    }
    fclose(f);
    printf("in.txt %d %d\n", n, sum);
    f = fopen("in.bin", "rb");
    printf("in.bin %d", (int)fread(words, 1, 4, f));
    printf(" %x %x %x\n", words[0], words[1], words[2]);
    fclose(f);
    d = opendir("/");
    while ((e = readdir(d)))
        printf("%s:%d:%u ", e->d_name, e->d_type == DT_DIR, e->d_size);
    printf("\n");
    closedir(d);
    chdir("/sub");
    f = fopen("deep.txt", "r");
    fgets(line, sizeof line, f);
    printf("deep %s", line);
    fclose(f);
    f = fopen("/nums.txt", "r");
    fscanf(f, "%d %d %f", &a, &b, &x);
    printf("nums %d %g\n", a + b, x * 2);
    fclose(f);
    f = fopen("out.txt", "w");
    for (n = 0; n < 1100; n++)
        fputc('0' + n % 10, f);
    fprintf(f, "|end %d\n", 1100);
    fclose(f);
    words[0] = 7;
    words[1] = 0xFFFFFFFF;
    f = fopen("/out.bin", "wb");
    fwrite(words, 1, 2, f);
    fclose(f);
    f = fopen("/in.txt", "a");
    fputs("+more", f);
    fclose(f);
    mkdir("/made");
    printf("rename %d remove %d\n", rename("/in.txt", "/made/in.txt"), remove("/in.bin"));
    printf("errors %d %d %d\n", fopen("/none", "r") == 0 && errno == ENOENT,
           rmdir("/sub") == -1 && errno == ENOTEMPTY, chdir("/nums.txt") == -1 && errno == ENOTDIR);
    return 0;
}
"""


def check_c_library():
    """The C library (compiler/libc/fs.c, dir.c) and fs.py agree: C reads
    what the tool wrote, the tool reads what C wrote, and fsck finds every
    block in exactly one file afterwards."""
    import sys
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc

    text = bytes(32 + i % 95 for i in range(1500))        # past one block (1024 chars)
    with new_disk(fs.BLOCK * 64, "c.img") as disk:
        disk.put("/in.txt", text)
        disk.put("/in.bin", bytes.fromhex("0100000002000000ffffffff"), binary=True)
        disk.mkdir("/sub")
        disk.put("/sub/deep.txt", b"down here\n")
        disk.put("/nums.txt", b"12 30 2.25\n")
        image = disk.path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "files.c"
        path.write_text(C_PROGRAM)
        program, _ = driver.build([str(path)])
    cpu, out = driver.run_in_simulator(program.rom, "", 20_000_000, disk=image)
    expect = (f"in.txt 1500 {sum(text)}\n"
              "in.bin 3 1 2 ffffffff\n"
              "in.txt:0:1500 in.bin:0:3 sub:1:132 nums.txt:0:11 \n"
              "deep down here\n"
              "nums 42 4.5\n"
              "rename 0 remove 0\n"
              "errors 1 1 1\n")
    assert cpu.halted and out == expect, out
    with FileSystem(image) as disk:
        assert disk.get("/sub/out.txt") == bytes(48 + n % 10 for n in range(1100)) + b"|end 1100\n"
        assert disk.get("/out.bin") == bytes.fromhex("07000000ffffffff")
        assert disk.get("/made/in.txt") == text + b"+more"
        assert disk.lookup("/in.txt") is None and disk.lookup("/in.bin") is None
        assert disk.check() == [], disk.check()
    return f"{cpu.instructions} instructions"


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
    check_fsck,
    check_c_library,
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
