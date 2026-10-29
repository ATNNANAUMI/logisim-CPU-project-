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
              "/a.txt\n"
              "nope\n"
              "primes > p.txt\n"
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
/docs> /a.txt
/a.txt: Exec format error
/docs> nope
nope: no such command (help lists them)
/docs> primes > p.txt
> works only for the built-in commands
/docs> cd ..
/> cat > typed.txt
line 1
/> cat typed.txt
line 1
/> rmdir docs
/> ls
bin/  readme.txt  a.txt  typed.txt
/> df
{df}
/> halt
CPU halted
"""


def check_shell():
    """os/shell.c on a disk made by os/make_disk.py: built-in commands, >
    and >>, quotes, a program from /bin with its arguments and exit status,
    the errors, cat from the keyboard up to Ctrl-D, df against fs.py."""
    import sys
    root = HERE.parent.parent.parent
    sys.path.append(str(root / "os"))
    sys.path.append(str(HERE.parent / "cc"))
    import driver                       # compiler/src/cc
    import make_disk                    # os/

    image = os.path.join(TMP.name, "shell.img")
    sizes = make_disk.make(image, programs=["echo"], new=True, size_mb=1, log=lambda _: None)
    shell, _ = driver.build([str(root / "os" / "shell.c")])
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
        assert disk.get("/a.txt") == b"two  spaces\nmore\n"
        assert disk.get("/typed.txt") == b"line 1\n"
        assert disk.lookup("/bin/echo").length == sizes["echo"] + 5
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
    check_spawn,
    check_shell,
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
