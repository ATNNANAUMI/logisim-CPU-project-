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


FILL_DISK = r"""
#include <stdio.h>
#include <errno.h>
#include <sys/statvfs.h>

int main(void)
{
    struct statvfs s;
    FILE *f = fopen("/big", "wb");
    int i, n = 0;
    for (i = 0; i < 14 * 256; i++) {
        if (fputc(i, f) == EOF && ferror(f))
            break;
        n++;
    }
    printf("wrote %d errno %d\n", n, errno);
    fclose(f);
    statvfs("/", &s);
    printf("free %u remove %d\n", s.f_bfree, remove("/big"));
    f = fopen("/again", "wb");
    for (i = 0; i < 300; i++)
        fputc(i, f);
    fclose(f);
    statvfs("/", &s);
    printf("free %u\n", s.f_bfree);
    return 0;
}
"""


def check_disk_full():
    """fs.py and the C library both stop at a full disk; C's block search
    wraps round the end of the FAT and finds the blocks freed after."""
    import sys
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc

    with new_disk(fs.BLOCK * 8) as disk:             # 8 blocks: 3 for the system, 5 free
        assert disk.free_blocks() == 5
        disk.put("/f", bytes(4 * 1024))               # 4 blocks
        raises("disk full", disk.put, "/g", bytes(2 * 1024))
        assert disk.check() == [] and disk.lookup("/g") is None   # no leaked blocks, no stray entry
        disk.put("/f", b"x" * 100)
        raises("disk full", disk.put, "/f", bytes(8 * 1024))      # an overwrite that cannot fit
        assert disk.check() == [] and disk.get("/f") == b"x" * 100  # keeps the old contents
    with new_disk(fs.BLOCK * 16, "full.img") as disk:   # 13 free
        image = disk.path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fill.c"
        path.write_text(FILL_DISK)
        program, _ = driver.build([str(path)])
    cpu, out = driver.run_in_simulator(program.rom, "", 20_000_000, disk=image)
    assert cpu.halted and out == f"wrote {13 * 256} errno 28\nfree 0 remove 0\nfree 11\n", out
    with FileSystem(image) as disk:
        assert disk.check() == [] and disk.lookup("/again").length == 300


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
    assert run("format", host, "--size", "1")[0] != 0      # a file that is not a disk survives
    assert "not a disk image" in run("format", host, "--size", "1")[1]
    assert open(host).read() != ""
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
#include <sys/statvfs.h>

int main(void)
{
    char line[300];
    unsigned words[4];
    int c, n = 0, sum = 0, a, b;
    float x;
    FILE *f = fopen("/in.txt", "r");
    struct statvfs s;
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
    printf("errors %d %d %d %d\n", fopen("/none", "r") == 0 && errno == ENOENT,
           rmdir("/sub") == -1 && errno == ENOTEMPTY, chdir("/nums.txt") == -1 && errno == ENOTDIR,
           statvfs("/none", &s) == -1 && errno == ENOENT);
    statvfs("/made", &s);
    printf("df %u %u %u %u\n", s.f_blocks, s.f_bfree, (unsigned)s.f_bsize, (unsigned)s.f_namemax);
    return 0;
}
"""


def check_c_library():
    """The C library (compiler/libc/fs.c, dir.c) and fs.py agree: C reads
    what the tool wrote, the tool reads what C wrote, statvfs() counts the
    free blocks fs.py counts, and fsck finds every block in exactly one file
    afterwards."""
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
              "errors 1 1 1 1\n")
    with FileSystem(image) as disk:
        expect += f"df {disk.blocks} {disk.free_blocks()} 256 127\n"
        assert cpu.halted and out == expect, out
        assert disk.get("/sub/out.txt") == bytes(48 + n % 10 for n in range(1100)) + b"|end 1100\n"
        assert disk.get("/out.bin") == bytes.fromhex("07000000ffffffff")
        assert disk.get("/made/in.txt") == text + b"+more"
        assert disk.lookup("/in.txt") is None and disk.lookup("/in.bin") is None
        assert disk.check() == [], disk.check()
    return f"{cpu.instructions} instructions"


STAT_PROGRAM = r"""
#include <stdio.h>
#include <errno.h>
#include <sys/stat.h>

static void show(const char *path)
{
    struct stat st;
    if (stat(path, &st))
        printf("%s: error %d\n", path, errno);
    else
        printf("%s: %s%s size %u blocks %u ino %u links %u\n", path,
               S_ISDIR(st.st_mode) ? "dir" : S_ISREG(st.st_mode) ? "file" : "?",
               S_ISTEXT(st.st_mode) ? " text" : "", st.st_size, st.st_blocks,
               st.st_ino, st.st_nlink);
}

int main(void)
{
    show("/t.txt");
    show("/b.bin");
    show("/empty.txt");
    show("/sub");
    show("/");
    show("/nope");
    show("/t.txt/x");
    return 0;
}
"""


def check_stat():
    """stat() (sys/stat.h) from C against what fs.py says about the same
    files: type, text or binary, size, blocks, first block; the errors."""
    import sys
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import errno

    with new_disk(fs.BLOCK * 64, "stat.img") as disk:
        disk.put("/t.txt", bytes(32 + i % 95 for i in range(1500)))
        disk.put("/b.bin", bytes(4 * 300), binary=True)
        disk.put("/empty.txt", b"")
        disk.mkdir("/sub")
        first = {n: disk.lookup(n).first for n in ("/t.txt", "/b.bin")}
        image = disk.path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "stat.c"
        path.write_text(STAT_PROGRAM)
        program, _ = driver.build([str(path)])
    cpu, out = driver.run_in_simulator(program.rom, "", 5_000_000, disk=image)
    with FileSystem(image) as disk:
        sub = disk.lookup("/sub")
        top = disk.lookup("/")
        expect = (f"/t.txt: file text size 1500 blocks 2 ino {first['/t.txt']} links 1\n"
                  f"/b.bin: file size 300 blocks 2 ino {first['/b.bin']} links 1\n"
                  "/empty.txt: file text size 0 blocks 0 ino 0 links 1\n"
                  f"/sub: dir size {sub.length} blocks {(sub.length + 255) // 256} ino {sub.first} links 1\n"
                  f"/: dir size {top.length} blocks {(top.length + 255) // 256} ino {top.first} links 1\n"
                  f"/nope: error {errno.ENOENT}\n"
                  f"/t.txt/x: error {errno.ENOTDIR}\n")
    assert cpu.halted and out == expect, out
    return f"{cpu.instructions} instructions"


SPAWNED = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int runs = 1;           /* starts at 1 on every run: initialised again */
int zeros[300];         /* set to 0 by spawnv() each time */

static void deep(int n, int status)
{
    if (n == 0)
        exit(status);
    deep(n - 1, status);
}

int main(int argc, char **argv)
{
    char cwd[40], *p = malloc(5000);
    FILE *f;
    int i;
    memset(p, 0x55, 5000);      /* its own heap, after its variables */
    printf("%d %d %d %s:", runs++, zeros[299], argc, getcwd(cwd, sizeof cwd));
    zeros[299] = 9;
    for (i = 0; i < argc; i++)
        printf(" %s", argv[i]);
    printf("\n");
    f = fopen("log.txt", "a");
    fprintf(f, "%s;", argv[argc - 1]);
    fclose(f);
    if (argc > 2)
        deep(20, 40 + argc);
    return argc;
}
"""

SPAWNER = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>

int main(void)
{
    char *one[] = { "prog", "a", 0 }, *three[] = { "prog", "b", "c", 0 };
    char *kept = malloc(20), line[40];
    FILE *f;
    strcpy(kept, "kept");
    chdir("/work");
    printf("-> %d\n", spawnv("/bin/prog", one));
    printf("-> %d\n", spawnv("/bin/prog", three));
    printf("-> %d\n", spawnv("../bin/prog", one));
    printf("%d %d", spawnv("/none", one) == -1 && errno == ENOENT,
           spawnv("/work", one) == -1 && errno == EISDIR);
    printf(" %d %s\n", spawnv("/bin/text", one) == -1 && errno == ENOEXEC, kept);
    f = fopen("log.txt", "r");
    fgets(line, sizeof line, f);
    printf("%s\n", line);
    return 0;
}
"""


def check_spawn():
    """A program built with --exe, put on the disk by the tool, run three
    times by spawnv() from a ROM program: arguments, exit status (from main
    and from exit() deep down), fresh variables each run, the caller's
    directory and heap, and the files it writes."""
    import sys
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import linker                       # compiler/src/asm (driver puts it on the path)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "prog.c").write_text(SPAWNED)
        (tmp / "spawner.c").write_text(SPAWNER)
        program, _ = driver.build([str(tmp / "prog.c")], exe=True)
        assert program.base == linker.PROGRAM_BASE and program.rom[0] == linker.ENTRY_WORD
        (tmp / "prog.exe").write_bytes(driver.exe_bytes(program))
        image = str(tmp / "s.img")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            for args in (["format", image, "--size", "1"], ["mkdir", image, "/bin"],
                         ["mkdir", image, "/work"], ["put", image, str(tmp / "prog.exe"), "/bin/prog"]):
                assert cli.main(args) == 0, out.getvalue()
        with FileSystem(image) as disk:
            node = disk.lookup("/bin/prog")
            assert not node.packed and node.length == len(program.rom) + 5   # stored as words
            disk.put("/bin/text", b"TEX1 but packed text")
        spawner, _ = driver.build([str(tmp / "spawner.c")])
        heap_end = next(s.address for s in spawner.symbols if s.name == "_heap_end")
        assert spawner.rom[heap_end] == linker.PROGRAM_BASE, hex(spawner.rom[heap_end])
        try:
            (tmp / "bad.c").write_text("#include <unistd.h>\nint main(void) { return spawnv(0, 0); }\n")
            driver.build([str(tmp / "bad.c")], exe=True)
        except driver.BuildError as e:
            assert "can't call spawnv()" in str(e), e
        else:
            raise AssertionError("--exe with spawnv() built")
        cpu, text = driver.run_in_simulator(spawner.rom, "", 20_000_000, disk=image)
    expect = ("1 0 2 /work: prog a\n-> 2\n"
              "1 0 3 /work: prog b c\n-> 43\n"
              "1 0 2 /work: prog a\n-> 2\n"
              "1 1 1 kept\n"
              "a;c;a;\n")
    assert cpu.halted and text == expect, text
    return f"{cpu.instructions} instructions"


SHELL_KEYS = ("help\n"
              "mkdir docs\n"
              "echo \"two  spaces\" > docs/a.txt\n"
              "echo more >> docs/a.txt\n"
              "cd docs\n"
              "cat a.txt\n"
              "mv a.txt /\n"
              "ls -l /\n"
              "echo a \"b c\"\n"
              "/bin/echo x \"y z\"\n"
              "/bin/echo\n"
              "cat /bin/echo\n"
              "cp /a.txt /b.txt\n"
              "cp /bin/echo /e2\n"
              "/e2 copy\n"
              "cp /b.txt /b.txt\n"
              "cp /b.txt /docs/../b.txt\n"
              "cp /docs /x\n"
              "cp /nope /x\n"
              "cat /b.txt\n"
              "/a.txt\n"
              "nope\n"
              "/bin/echo r1 r2 > /p.txt\n"
              "/bin/echo r3 >> /p.txt\n"
              "/bin/echo > /q.txt\n"
              "cat /p.txt /q.txt\n"
              "cd ..\n"
              "cat > typed.txt\n"
              "line 1\n"
              "\x04"
              "cat typed.txt\n"
              "rmdir docs\n"
              "ls\n"
              "df\n"
              "halt\n")

SHELL_OUTPUT = """\
Tynix shell: help lists the commands
/> mkdir docs
/> echo "two  spaces" > docs/a.txt
/> echo more >> docs/a.txt
/> cd docs
/docs> cat a.txt
two  spaces
more
/docs> mv a.txt /
/docs> ls -l /
   <dir>  bin/
{readme:8}  readme.txt
   <dir>  docs/
      17  a.txt
/docs> echo a "b c"
a b c
/docs> /bin/echo x "y z"
x y z
/docs> /bin/echo
/bin/echo: no arguments (argc = 1)
[/bin/echo: exit status 1]
/docs> cat /bin/echo
cat: /bin/echo: a binary file (a program?)
/docs> cp /a.txt /b.txt
/docs> cp /bin/echo /e2
/docs> /e2 copy
copy
/docs> cp /b.txt /b.txt
cp: /b.txt and /b.txt are the same file
/docs> cp /b.txt /docs/../b.txt
cp: /b.txt and /docs/../b.txt are the same file
/docs> cp /docs /x
cp: /docs: is a directory
/docs> cp /nope /x
cp: /nope: No such file or directory
/docs> cat /b.txt
two  spaces
more
/docs> /a.txt
/a.txt: Exec format error
/docs> nope
nope: no such command (help lists them)
/docs> /bin/echo r1 r2 > /p.txt
/docs> /bin/echo r3 >> /p.txt
/docs> /bin/echo > /q.txt
[/bin/echo: exit status 1]
/docs> cat /p.txt /q.txt
r1 r2
r3
/bin/echo: no arguments (argc = 1)
/docs> cd ..
/> cat > typed.txt
line 1
/> cat typed.txt
line 1
/> rmdir docs
/> ls
bin/  readme.txt  a.txt  b.txt  e2  p.txt  q.txt  typed.txt
/> df
{df}
/> halt
CPU halted
"""


def check_shell():
    """tynix/shell.c on a disk made by tynix/make_disk.py: built-in commands, >
    and >>, quotes, a program from /bin with its arguments and exit status,
    the errors, cat from the keyboard up to Ctrl-D, df against fs.py."""
    import sys
    root = HERE.parent.parent.parent
    sys.path.append(str(root / "tynix"))
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import make_disk                    # tynix/

    image = os.path.join(TMP.name, "shell.img")
    sizes = make_disk.make(image, programs=["echo"], new=True, size_mb=1, log=lambda _: None)
    shell, _ = driver.build([str(root / "tynix" / "shell.c")])
    cpu, text = driver.run_in_simulator(shell.rom, SHELL_KEYS, 50_000_000, disk=image)
    assert cpu.halted, text
    help_text, sep, rest = text.partition("/> mkdir docs\n")
    assert help_text.startswith("Tynix shell: help lists the commands\n/> help\n  help ") and \
        help_text.endswith("programs in /bin (type the name):\n  echo\n"), help_text
    with FileSystem(image) as disk:
        used = disk.blocks - disk.free_blocks()
        df = (f"{disk.blocks} blocks of 1 KB (256 words): {used} used, "
              f"{disk.free_blocks()} free ({(used * 100 + disk.blocks - 1) // disk.blocks}% used)")
        got = help_text.partition("/> help\n")[0] + sep + rest
        assert got == SHELL_OUTPUT.format(df=df, readme=len(make_disk.README)), got
        assert disk.get("/p.txt") == b"r1 r2\nr3\n"       # a program's output, > and >>
        assert disk.get("/a.txt") == b"two  spaces\nmore\n" == disk.get("/b.txt")
        assert disk.lookup("/e2").length == sizes["echo"] + 5 and not disk.lookup("/e2").packed
        assert disk.get("/typed.txt") == b"line 1\n"
        assert disk.lookup("/bin/echo").length == sizes["echo"] + 5
        assert disk.check() == [], disk.check()
    return f"{cpu.instructions} instructions"


def check_reclaim():
    """fs_reclaim() (the shell runs it at boot and after a kill): blocks no
    file uses, and chain blocks past a file's length, are freed; nothing a
    file uses is touched, and fs.py finds the disk consistent afterwards."""
    import sys
    root = HERE.parent.parent.parent
    sys.path.append(str(root / "tynix"))
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import make_disk                    # tynix/

    image = os.path.join(TMP.name, "reclaim.img")
    make_disk.make(image, programs=["echo"], new=True, size_mb=1, log=lambda _: None)
    with FileSystem(image) as disk:
        disk.put("/a.txt", b"x" * 700)                      # 175 words: one block
        disk.put("/big.txt", b"y" * 3000)                   # 750 words: three blocks
        before = disk.free_blocks()
        lost = [disk.alloc() for _ in range(3)]             # blocks nothing points to
        tail = disk.chain(disk.lookup("/a.txt").first)[-1]
        extra = [disk.alloc(), disk.alloc()]                # a chain longer than the file
        disk.set_fat(tail, extra[0])
        disk.set_fat(extra[0], extra[1])
        assert disk.free_blocks() == before - 5 and len(disk.check()) == len(lost)
    shell, _ = driver.build([str(root / "tynix" / "shell.c")])
    cpu, text = driver.run_in_simulator(shell.rom, "cat /a.txt > /copy.txt\nhalt\n", 50_000_000,
                                        disk=image)
    assert cpu.halted and "[boot: freed 5 lost blocks]\n" in text, text
    with FileSystem(image) as disk:
        assert disk.check() == [], disk.check()
        assert disk.get("/a.txt") == b"x" * 700 and disk.get("/big.txt") == b"y" * 3000
        assert len(disk.chain(disk.lookup("/a.txt").first)) == 1
        assert disk.free_blocks() == before - 1             # only /copy.txt is new
    cpu, text = driver.run_in_simulator(shell.rom, "halt\n", 50_000_000, disk=image)
    assert "freed" not in text, text                        # nothing left to free
    return f"{cpu.instructions} instructions"


def check_kill():
    """The NMI (the kill switch): while a program from /bin spins, the shell's
    NMI handler asks; 2 goes on, 1 ends it with status 130 and the shell comes
    back at its prompt. At the prompt an NMI does nothing."""
    import sys
    root = HERE.parent.parent.parent
    sys.path.append(str(root / "tynix"))
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import make_disk                    # tynix/
    sys.path.append(str(root / "cpu_sim" / "src"))
    from cpu import CPU

    image = os.path.join(TMP.name, "kill.img")
    make_disk.make(image, programs=["echo"], new=True, size_mb=1, log=lambda _: None)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "spin.c").write_text(
            '#include <stdio.h>\n'
            'int main(void) { long n = 0; puts("spinning"); for (;;) n++; return 0; }\n')
        program, _ = driver.build([str(Path(tmp) / "spin.c")], exe=True)
        (Path(tmp) / "spin.exe").write_bytes(driver.exe_bytes(program))
        with FileSystem(image) as disk:
            disk.put("/bin/spin", (Path(tmp) / "spin.exe").read_bytes(), binary=True)
    shell, _ = driver.build([str(root / "tynix" / "shell.c")])

    cpu = CPU()
    cpu.mem.load_rom(shell.rom)
    cpu.bus.attach_disk(image)

    def until(text, limit=200):
        for _ in range(limit):
            if text in cpu.bus.display.text:
                return
            cpu.run(100_000)
        raise AssertionError(f"never saw {text!r} in:\n{cpu.bus.display.text}")

    try:
        until("/> ")
        cpu.nmi()                                       # at the prompt: nothing to stop
        cpu.run(100_000)
        assert "[" not in cpu.bus.display.text and not cpu.halted
        cpu.bus.keyboard.type("spin\n")
        until("spinning")
        cpu.nmi()
        until("[spin: 1 kill, 2 continue] ")
        cpu.bus.keyboard.type("2")
        cpu.run(100_000)
        assert cpu.bus.display.text.endswith("] 2\n") and cpu.ie == 1 and not cpu.in_nmi
        cpu.nmi()                                       # again: still running, so it asks again
        cpu.bus.keyboard.type("x1")                     # (x is not an answer)
        until("[spin: exit status 130]")
        until("/> ")
        cpu.bus.keyboard.type("echo back\nhalt\n")
        cpu.run(2_000_000)
        assert cpu.halted and "back\n" in cpu.bus.display.text
        assert cpu.bus.display.text.count("1 kill, 2 continue") == 2
    finally:
        cpu.bus.attach_disk(None)
    with FileSystem(image) as disk:
        assert disk.check() == [], disk.check()
    return f"{cpu.instructions} instructions"


EDITOR_KEYS = ("ed /a.txt\n"
               "a\n"
               "one x\n"
               "two x\n"
               "three\n"
               ".\n"
               "2d\n"
               "1s/x/Y/\n"
               "/thr\n"
               "1i\n"
               "zero\n"
               ".\n"
               "q\n"
               "w\n"
               "q\n"
               "cat /a.txt\n"
               "ed /bin/echo\n"
               "ed /a.txt\n"
               "$d\n"
               "\x04"
               "\x04"
               "cat /a.txt\n"
               "halt\n")

EDITOR_OUTPUT = """\
Tynix shell: help lists the commands
/> ed /a.txt
/a.txt: new file
*a
one x
two x
three
.
*2d
*1s/x/Y/
   1  one Y
*/thr
   2  three
*1i
zero
.
*q
unsaved changes (w saves, q again quits)
*w
17 chars
*q
/> cat /a.txt
zero
one Y
three
/> ed /bin/echo
/bin/echo: not a text file
[ed: exit status 1]
/> ed /a.txt
17 chars, 3 lines
*$d
*
unsaved changes (w saves, Ctrl-D again quits)
*
/> cat /a.txt
zero
one Y
three
/> halt
CPU halted
"""


def check_editor():
    """tynix/ed.c as a program from /bin, started by the shell: add, delete,
    substitute, find, insert, the unsaved-changes warning (q and Ctrl-D), a
    binary file refused, and the file on the disk read back with fs.py."""
    import sys
    root = HERE.parent.parent.parent
    sys.path.append(str(root / "tynix"))
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import make_disk                    # tynix/

    image = os.path.join(TMP.name, "editor.img")
    make_disk.make(image, programs=["echo", "ed"], new=True, size_mb=1, log=lambda _: None)
    shell, _ = driver.build([str(root / "tynix" / "shell.c")])
    cpu, text = driver.run_in_simulator(shell.rom, EDITOR_KEYS, 80_000_000, disk=image)
    assert cpu.halted and text == EDITOR_OUTPUT, text
    with FileSystem(image) as disk:
        assert disk.get("/a.txt") == b"zero\none Y\nthree\n"
        assert disk.check() == [], disk.check()
    return f"{cpu.instructions} instructions"


def _a(n):
    return chr(n)


SCREEN_KEYS = ("edit /s.txt\n"
               "abc\ndef\nghi"                    # three lines
               + _a(30) + _a(30) + _a(30) + "X"   # left x3 -> start of "ghi"... then insert
               + _a(28) + _a(5) + "\n"            # up, end of "def", Enter splits (empty line)
               + "k"                              # new line "k"
               + _a(8) + _a(8)                    # Backspace twice: removes k, then joins up
               + _a(11)                           # Ctrl-K deletes the line "def"
               + _a(19)                           # Ctrl-S
               + _a(17)                           # Ctrl-Q (saved, so it quits at once)
               + "cat /s.txt\n"
               "edit /s.txt\n" "Z" + _a(17)      # unsaved: warns, a second ^Q quits
               + _a(17) + "cat /s.txt\n"
               "edit /bin/echo\n"
               "halt\n")


def check_screen_editor():
    """tynix/edit.c as a program from /bin: insert, arrows, Enter, Backspace
    (also joining lines), Ctrl-K, Ctrl-S, the unsaved-changes warning, a
    binary file refused; the file read back with fs.py, text drawn on the
    RGB screen while it runs and the screen blank after it quits."""
    import sys
    root = HERE.parent.parent.parent
    sys.path.append(str(root / "tynix"))
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import make_disk                    # tynix/

    image = os.path.join(TMP.name, "screen_editor.img")
    make_disk.make(image, programs=["echo", "edit"], new=True, size_mb=1, log=lambda _: None)
    shell, _ = driver.build([str(root / "tynix" / "shell.c")])
    # while it runs: stop inside the editor and look at the screen
    cpu, _ = driver.run_in_simulator(shell.rom, "edit /s.txt\nabc\ndef", 12_000_000, disk=image)
    assert not cpu.halted and any(cpu.bus.video.pixels), "nothing drawn"
    cpu, text = driver.run_in_simulator(shell.rom, SCREEN_KEYS, 80_000_000, disk=image)
    assert cpu.halted, text
    assert text.count("abc\nXghi\n") == 2 and "Z" not in text, text
    assert "/bin/echo: not a text file" in text, text
    assert not any(cpu.bus.video.pixels), "screen not blank after quitting"
    with FileSystem(image) as disk:
        assert disk.get("/s.txt") == b"abc\nXghi\n", disk.get("/s.txt")
        assert disk.check() == [], disk.check()
    return f"{cpu.instructions} instructions"


TOOLS_KEYS = ("grep -n -i beta /docs/a.txt\n"
              "grep -i beta /docs\n"
              "grep -vn e /docs/a.txt\n"
              "grep zzz /docs/a.txt\n"
              "grep x /bin/echo\n"
              "grep x /nope\n"
              "grep\n"
              "find / txt\n"
              "find /docs sub\n"
              "find /nope x\n"
              "tree /docs\n"
              "tree -s /docs\n"
              "tree /nope\n"
              "du /docs\n"
              "du -a /docs\n"
              "du /nope\n"
              "diff /docs/a.txt /docs/a.txt\n"
              "diff /docs/a.txt /docs/b.txt\n"
              "diff /x.txt /y.txt\n"
              "diff /docs/a.txt /bin/echo\n"
              "hexdump /h.txt\n"
              "hexdump /nope /h.txt\n"
              "calc 2 * (3 + 4)\n"
              "calc -1\n"
              "calc 1 / 0\n"
              "calc 0x1100000 + 256\n"
              "calc \"256 >> 4\"\n"
              "calc \"'a' + 1\"\n"
              "calc 7 % 3 | 8 ^ 2\n"
              "calc 2 + 3 * 4\n"
              "calc 1 << 2 + 1\n"
              "calc -7 / 2 + -7 % 2\n"
              "calc \"-16 >> 2\"\n"
              "calc 4294967295\n"
              "calc 4294967296\n"
              "calc 1 +\n"
              "calc\n"
              "1 + 1\n"
              "0b101 << 2\n"
              "(1\n"
              "\x04"
              "more -n 3 /long.txt\n"
              " " "\n" "q"
              "more -n 0 /long.txt\n"
              "more /bin/echo\n"
              "more /long.txt > /more.txt\n"
              "tree /docs > /out.txt\n"
              "halt\n")

TOOLS_OUTPUT = """\
Tynix shell: help lists the commands
/> grep -n -i beta /docs/a.txt
2:Beta line
/> grep -i beta /docs
/docs/a.txt:Beta line
/docs/b.txt:Beta changed
/docs/sub/c.txt:Beta in sub
/> grep -vn e /docs/a.txt
1:alpha
3:gamma
/> grep zzz /docs/a.txt
[grep: exit status 1]
/> grep x /bin/echo
grep: /bin/echo: not a text file
[grep: exit status 2]
/> grep x /nope
grep: /nope: No such file or directory
[grep: exit status 2]
/> grep
usage: grep [-i] [-n] [-v] text [path...]
[grep: exit status 1]
/> find / txt
{find_txt}/> find /docs sub
/docs/sub/
/> find /nope x
find: /nope: No such file or directory
[find: exit status 1]
/> tree /docs
/docs
|-- a.txt
|-- b.txt
`-- sub
    `-- c.txt
1 directory, 3 files
/> tree -s /docs
/docs
|-- [      36]  a.txt
|-- [      38]  b.txt
`-- [   <dir>]  sub
    `-- [      20]  c.txt
1 directory, 3 files
/> tree /nope
tree: /nope: No such file or directory
[tree: exit status 1]
/> du /docs
{du_sub}
{du_docs}
/> du -a /docs
{du_a}
{du_sub}
{du_docs}
/> du /nope
du: /nope: No such file or directory
[du: exit status 1]
/> diff /docs/a.txt /docs/a.txt
/> diff /docs/a.txt /docs/b.txt
2c2
< Beta line
---
> Beta changed
4d3
< delta
5a5
> zeta
[diff: exit status 1]
/> diff /x.txt /y.txt
2d1
< 2
5a5
> 5b
9a10
> 9b
[diff: exit status 1]
/> diff /docs/a.txt /bin/echo
diff: /bin/echo: not a text file
[diff: exit status 2]
/> hexdump /h.txt
{hex}
/> hexdump /nope /h.txt
/nope:
hexdump: /nope: No such file or directory
/h.txt:
{hex}
[hexdump: exit status 1]
/> calc 2 * (3 + 4)
14
/> calc -1
-1 (4294967295 unsigned)
/> calc 1 / 0
calc: division by zero
[calc: exit status 1]
/> calc 0x1100000 + 256
17826048
/> calc "256 >> 4"
16
/> calc "'a' + 1"
98
/> calc 7 % 3 | 8 ^ 2
11
/> calc 2 + 3 * 4
14
/> calc 1 << 2 + 1
8
/> calc -7 / 2 + -7 % 2
-4 (4294967292 unsigned)
/> calc "-16 >> 2"
-4 (4294967292 unsigned)
/> calc 4294967295
-1 (4294967295 unsigned)
/> calc 4294967296
calc: number does not fit in 32 bits
[calc: exit status 1]
/> calc 1 +
calc: the expression ends too soon
[calc: exit status 1]
/> calc
calc> 1 + 1
2
calc> 0b101 << 2
20
calc> (1
calc: missing )
calc> 
/> more -n 3 /long.txt
line 1
line 2
line 3
--more-- (space: page, Enter: line, q: quit)
line 4
line 5
line 6
--more-- (space: page, Enter: line, q: quit)
line 7
--more-- (space: page, Enter: line, q: quit)
/> more -n 0 /long.txt
more: -n needs a number of lines, 1 or more
[more: exit status 1]
/> more /bin/echo
more: /bin/echo: not a text file
[more: exit status 1]
/> more /long.txt > /more.txt
/> tree /docs > /out.txt
/> halt
CPU halted
"""

HEXDUMP_TEXT = b"hello, world\n"


FM2_KEYS = ("visual_file_manager /m\n"
            "j" " " " " "x"                    # space selects a.txt and b.txt, x cuts both
            "g" "l" "p" "h"                    # into dest, paste both, back
            "j" "y" "y" "g" "l" "p" "h"        # c.txt: copy, the same key again clears it: nothing to paste in dest
            "jj" " " "y" "g" "l" "u" "p" "h"   # d.txt selected and copied; u forgets it in dest: nothing to paste
            "j" " " " " "d" "y"                # select c.txt and d.txt, delete both
            "~" "a" "tilde\n"                  # ~ goes home: a folder made there
            "q"
            "visual_file_manager\n"           # no argument: starts in /home/user
            "a" "mk\n" "q"
            "halt\n")

FM2_OUTPUT = """\
Tynix shell: help lists the commands
/> visual_file_manager /m
/> visual_file_manager
/> halt
CPU halted
"""


FM3_KEYS = ("visual_file_manager /r\n"
            "jj" "y" "g" "l" "p" "h"           # copy the folder tree (nested) into dest, back
            "j" "d" "y"                        # delete junk, nested files and all
            "y" "l" "p"                        # copy tree into itself: refused
            "q"
            "halt\n")

FM4_KEYS = ("visual_file_manager /q\n"
            "j" "y" "g" "l" "p"                # copy t (9 blocks) into d on a disk with 4 free: fails half way
            "q"
            "halt\n")

FM3_OUTPUT = """\
Tynix shell: help lists the commands
/> visual_file_manager /r
/> halt
CPU halted
"""
FM4_OUTPUT = FM3_OUTPUT.replace("/r", "/q")


def _tree(disk, path):
    """A folder as nested dicts of name -> contents, to compare two copies."""
    node = disk.lookup(path)
    if not node.is_dir:
        return disk.get(path)
    return {e.name: _tree(disk, path.rstrip("/") + "/" + e.name) for e in disk.entries(node)}


def _hexdump(data):
    lines = []
    for at in range(0, len(data), 8):
        chunk = data[at:at + 8]
        values = "".join(f" {c:08x}" for c in chunk) + "         " * (8 - len(chunk))
        chars = "".join(chr(c) if 32 <= c <= 126 else "." for c in chunk)
        lines.append(f"{at:06x}:{values}  {chars}")
    return "\n".join(lines)


def _kb(disk, path):
    """Disk KB under path by fs.py's own block chains: a file's blocks, a folder's
    own directory file plus all it holds (what `du` has to print)."""
    node = disk.lookup(path)
    total = len(disk.chain(node.first))
    if node.is_dir:
        for e in disk.entries(node):
            total += _kb(disk, path.rstrip("/") + "/" + e.name)
    return total


FM_KEYS = ("visual_file_manager /fm\n"
           "jj" "y" "k" "l" "p" "p" "h"       # copy one.txt, enter sub, paste (a second p is refused), back
           "j" "x" "kk" "l" "p" "h"           # cut one.txt, enter dest, paste: moved
           "jj" "y" "kk" "l" "p" "h"          # copy two.txt, paste into dest: dest has one, refused
           "j" "r" "x\b2\n"                   # rename: the name is there to edit; sub -> sub2
           "d" "n"                            # sub2 holds files: asked, no, it stays
           "jj" "d" "n" "k" "d" "y"           # zzz.txt: asked, no; two.txt: asked, yes
           "a" "newdir\n"                     # a new folder
           "k" "l" "y" "\n"                   # in dest: copy one.txt, Enter opens it in edit:
           "Z\x13\x11"                        #   edit types Z, saves, quits; the manager is back
           "h" "p" "q"                        # up, paste the copy it still holds, quit
           "visual_file_manager /bin echo\n"
           "\n"                               # Enter on the program echo: it runs, the manager is back
           "q"
           "halt\n")

FM_OUTPUT = """\
Tynix shell: help lists the commands
/> visual_file_manager /fm
/> visual_file_manager /bin echo
/bin/echo: no arguments (argc = 1)
[/bin/echo: exit status 1]
/> halt
CPU halted
"""


def check_tools():
    """The eight command-line tools in tynix/ (more grep find tree du diff hexdump
    calc) as programs from /bin, run by the shell on known files, with their
    exact output, exit status messages and errors; then visual_file_manager's
    copy, cut, paste, rename, delete and new folder, and opening a file through
    the shell (edit) and a program; all read back with fs.py."""
    import sys
    root = HERE.parent.parent.parent
    sys.path.append(str(root / "tynix"))
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import make_disk                    # tynix/

    names = ["echo", "edit", "more", "grep", "find", "tree", "du", "diff", "hexdump", "calc",
             "visual_file_manager"]
    image = os.path.join(TMP.name, "tools.img")
    make_disk.make(image, programs=names, new=True, size_mb=1, log=lambda _: None)
    a = b"alpha\nBeta line\ngamma\ndelta\nepsilon\n"
    long_text = b"".join(b"line %d\n" % i for i in range(1, 13))
    with FileSystem(image) as disk:
        disk.mkdir("/docs")
        disk.put("/docs/a.txt", a)
        disk.put("/docs/b.txt", b"alpha\nBeta changed\ngamma\nepsilon\nzeta\n")
        disk.mkdir("/docs/sub")
        disk.put("/docs/sub/c.txt", b"Beta in sub\nnothing\n")
        disk.put("/long.txt", long_text)
        disk.put("/x.txt", b"".join(b"%d\n" % i for i in range(1, 10)))
        disk.put("/y.txt", b"1\n3\n4\n5\n5b\n6\n7\n8\n9\n9b\n")
        disk.put("/h.txt", HEXDUMP_TEXT)
        expected = TOOLS_OUTPUT.format(
            find_txt="/readme.txt\n/docs/a.txt\n/docs/b.txt\n/docs/sub/c.txt\n/long.txt\n"
                     "/x.txt\n/y.txt\n/h.txt\n",
            du_sub=f"{_kb(disk, '/docs/sub'):<6} /docs/sub",
            du_docs=f"{_kb(disk, '/docs'):<6} /docs",
            du_a="\n".join(f"{_kb(disk, p):<6} {p}" for p in
                           ("/docs/a.txt", "/docs/b.txt", "/docs/sub/c.txt")),
            hex=_hexdump(HEXDUMP_TEXT))
    shell, _ = driver.build([str(root / "tynix" / "shell.c")])
    cpu, text = driver.run_in_simulator(shell.rom, TOOLS_KEYS, 30_000_000, disk=image)
    assert cpu.halted, text
    assert text == expected, "\n".join(
        f"{n}: {x!r} != {y!r}" for n, (x, y) in enumerate(zip(text.split("\n"), expected.split("\n")))
        if x != y) or (len(text), len(expected))
    with FileSystem(image) as disk:
        assert disk.get("/more.txt") == long_text, disk.get("/more.txt")
        assert disk.get("/out.txt") == (b"/docs\n|-- a.txt\n|-- b.txt\n`-- sub\n"
                                        b"    `-- c.txt\n1 directory, 3 files\n")
        assert disk.get("/docs/a.txt") == a
        assert disk.check() == [], disk.check()
        disk.mkdir("/fm")
        disk.mkdir("/fm/dest")
        disk.put("/fm/dest/two.txt", b"dest two\n")
        disk.mkdir("/fm/sub")
        disk.put("/fm/sub/inner.txt", b"inner\n")
        disk.put("/fm/one.txt", b"one\n")
        disk.put("/fm/two.txt", b"two\n")
        disk.put("/fm/zzz.txt", b"zzz\n")
        make_disk.make_home(disk)
        disk.mkdir("/m")
        disk.mkdir("/m/dest")
        for n in "abcd":
            disk.put(f"/m/{n}.txt", f"{n}\n".encode())
        for folder in ("/r", "/r/dest", "/r/tree", "/r/tree/sub", "/r/tree/sub/deep", "/r/junk", "/r/junk/s"):
            disk.mkdir(folder)
        disk.put("/r/tree/top.txt", b"top\n")
        disk.put("/r/tree/sub/mid.txt", b"mid\n" * 300)         # more than a block
        disk.put("/r/tree/sub/deep/bottom.txt", b"bottom\n")
        disk.put("/r/junk/j1.txt", b"j1\n")
        disk.put("/r/junk/s/j2.txt", b"j2\n" * 400)
    tools = cpu.instructions
    cpu, text = driver.run_in_simulator(shell.rom, FM_KEYS, 40_000_000, disk=image)
    assert cpu.halted and text == FM_OUTPUT, text
    assert not any(cpu.bus.video.pixels), "screen not blank after quitting"
    with FileSystem(image) as disk:
        assert sorted(e.name for e in disk.entries(disk.lookup("/fm"))) == \
            ["dest", "newdir", "one.txt", "sub2", "zzz.txt"]
        assert disk.get("/fm/dest/one.txt") == b"Zone\n"       # moved, then edited through the shell
        assert disk.get("/fm/one.txt") == b"Zone\n"            # the clipboard survived the trip
        assert disk.get("/fm/dest/two.txt") == b"dest two\n"   # a paste never overwrites
        assert disk.get("/fm/sub2/one.txt") == b"one\n"        # the first copy
        assert disk.get("/fm/sub2/inner.txt") == b"inner\n"    # not overwritten, not deleted
        assert disk.get("/fm/zzz.txt") == b"zzz\n"             # a no to "delete?" keeps it
        assert disk.lookup("/fm/newdir").is_dir and disk.lookup("/.next") is None
        assert disk.check() == [], disk.check()
    fm = cpu.instructions
    cpu, text = driver.run_in_simulator(shell.rom, FM2_KEYS, 40_000_000, disk=image)
    assert cpu.halted and text == FM2_OUTPUT, text
    with FileSystem(image) as disk:
        assert sorted(e.name for e in disk.entries(disk.lookup("/m"))) == ["dest"]
        assert sorted(e.name for e in disk.entries(disk.lookup("/m/dest"))) == ["a.txt", "b.txt"]
        assert disk.get("/m/dest/b.txt") == b"b\n"
        assert disk.lookup("/home/user/tilde").is_dir and disk.lookup("/home/user/mk").is_dir
        assert sorted(e.name for e in disk.entries(disk.lookup("/home/user")))[:6] == \
            ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"]
        assert disk.lookup("/.clipboard") is None and disk.check() == [], disk.check()
    fm2 = cpu.instructions
    cpu, text = driver.run_in_simulator(shell.rom, FM3_KEYS, 60_000_000, disk=image)
    assert cpu.halted and text == FM3_OUTPUT, text
    with FileSystem(image) as disk:
        assert sorted(e.name for e in disk.entries(disk.lookup("/r"))) == ["dest", "tree"], \
            "junk was not deleted"
        assert _tree(disk, "/r/dest/tree") == _tree(disk, "/r/tree")     # the whole folder, copied
        assert _tree(disk, "/r/tree")["sub"]["mid.txt"] == b"mid\n" * 300
        assert "tree" not in _tree(disk, "/r/tree")                       # not into itself
        assert disk.check() == [], disk.check()                           # the blocks of junk are free
        disk.mkdir("/q")
        disk.mkdir("/q/d")
        disk.mkdir("/q/t")
        for n in "abc":
            disk.put(f"/q/t/{n}.txt", (n * 99 + "\n").encode() * 30)     # 3000 chars: 3 blocks each
        disk.put("/fill", bytes(4 * 256 * (disk.free_blocks() - 4)), binary=True)
        assert 1 <= disk.free_blocks() <= 5, disk.free_blocks()
    fm3 = cpu.instructions
    cpu, text = driver.run_in_simulator(shell.rom, FM4_KEYS, 60_000_000, disk=image)
    assert cpu.halted and text == FM4_OUTPUT, text
    with FileSystem(image) as disk:
        assert disk.entries(disk.lookup("/q/d")) == [], "a failed copy left a half folder"
        assert len(disk.entries(disk.lookup("/q/t"))) == 3
        assert disk.check() == [], disk.check()
    return f"{tools} + {fm} + {fm2} + {fm3} + {cpu.instructions} instructions"


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
    check_stat,
    check_spawn,
    check_shell,
    check_reclaim,
    check_kill,
    check_editor,
    check_screen_editor,
    check_tools,
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
