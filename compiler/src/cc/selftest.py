"""Checks for the C compiler. Run from the project root:

    python compiler/src/cc/selftest.py

The test programs in tests/ are compiled, run in the simulator and compared
with tests/<name>.expected (gcc's output, written by tests/difftest.py).
"""

import contextlib
import importlib.util
import io
import tempfile
import traceback
from pathlib import Path
from typing import Any

import driver
from cerror import CError
from cparser import parse
from driver import BuildError
from preprocessor import Preprocessor

HERE = Path(__file__).resolve().parent
TESTS = HERE / "tests"

_spec = importlib.util.spec_from_file_location("cc_cli", HERE / "__main__.py")
assert _spec is not None and _spec.loader is not None
cli: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def preprocess(text):
    toks = Preprocessor().run_text(text, "test.c")
    return " ".join(t.text for t in toks)


def run_c(text, keys="", name="test.c", steps=20_000_000):
    """Build a C program from text and run it; returns (cpu, display text)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_text(text)
        program, _ = driver.build([str(path)])
    cpu, out = driver.run_in_simulator(program.rom, keys, steps)
    assert cpu.halted, "the program did not halt"
    return cpu, out


def output(text, keys=""):
    return run_c(text, keys)[1]


def expect_error(text, fragment):
    try:
        toks = Preprocessor().run_text(text, "test.c")
        parse(toks)
    except CError as e:
        if fragment in e.message:
            return
        raise AssertionError(f"wrong error for {text!r}: {e}")
    raise AssertionError(f"no error for {text!r}")


# ---------------------------------------------------------------- checks

def check_preprocessor():
    assert preprocess("#define F(x, y) x ## y + #x\nF(a, b)") == 'ab + "a"'
    assert preprocess("#define V(f, ...) f(__VA_ARGS__)\nV(g, 1, 2)") == "g ( 1 , 2 )"
    assert preprocess("#define G(f, a...) f(0 , ## a)\nG(h) G(h, 1)") == "h ( 0 ) h ( 0 , 1 )"
    assert preprocess("#if 1 + 2 * 3 == 7 && !defined(X)\nyes\n#else\nno\n#endif") == "yes"
    assert preprocess("#ifdef X\na\n#elif 0\nb\n#else\nc\n#endif") == "c"
    assert preprocess("#define f(a) a*g\n#define g(a) f(a)\nf(2)(9)") == "2 * 9 * g"
    assert preprocess("__LINE__\n\n__LINE__") == "1 3"
    assert preprocess('"a" "b"') == '"a" "b"'      # joined into one token
    toks = Preprocessor().run_text('"a" "b" 0x10u 1.5f \'\\n\'', "t.c")
    assert toks[0].value == [97, 98]
    assert toks[1].value == 16 and toks[1].ty == ("int", "u", 16)
    assert toks[2].value == 1.5 and toks[3].value == 10


def check_errors():
    expect_error("int main(void) { return x; }", "'x' undeclared")
    expect_error("int main(void) { foo(); }", "implicit declaration of function 'foo'")
    expect_error("int main(void) { int a; a(); }", "not a function")
    expect_error("int main(void) { 1 = 2; }", "lvalue required")
    expect_error("int main(void) { const int c = 1; c = 2; }", "read-only")
    expect_error("int f(int a, int b); int main(void) { return f(1); }", "too few arguments")
    expect_error("int main(void) { long long x; }", "long long")
    expect_error("int main(int n) { int a[n]; }", "variable-length arrays")
    expect_error("struct s; int main(void) { struct s v; }", "storage size")
    expect_error("int main(void) { break; }", "'break' outside")
    expect_error("int main(void) { goto nowhere; }", "label 'nowhere' used but not defined")
    expect_error("int main(void) { switch (1) { case 1: case 1: ; } }", "duplicate case")
    expect_error("int main(void) { int x; return x.y; }", "request for member")
    expect_error("int main(void) { return \"a\" * 2; }", "invalid operands")
    expect_error("#error stop here\n", "#error stop here")
    expect_error("int main(void) { return 1 }", "expected ';'")
    expect_error("_Static_assert(1 == 2, \"no\");", "static assertion failed")


def check_warnings():
    warnings = []
    toks = Preprocessor().run_text("int *p = 5; int main(void) { char *s = p; return 0; }", "t.c")
    parse(toks, warn=warnings.append)
    messages = " | ".join(w.message for w in warnings)
    assert "pointer from an integer" in messages, messages
    assert "incompatible pointer types" in messages, messages


def check_sizes():
    """Everything is one 32-bit word (CHAR_BIT is 32)."""
    out = output(r"""
        #include <stdio.h>
        #include <limits.h>
        struct s { char c; int i; double d; char name[3]; };
        int main(void) {
            printf("%d %d %d %d %d %d %d %d\n", (int)sizeof(char), (int)sizeof(short),
                   (int)sizeof(int), (int)sizeof(long), (int)sizeof(float), (int)sizeof(double),
                   (int)sizeof(void *), (int)sizeof(struct s));
            printf("%d %u\n", CHAR_BIT, UCHAR_MAX);
            return 0;
        }""")
    assert out == "1 1 1 1 1 1 1 6\n32 4294967295\n", out


def check_programs():
    """Every test program gives gcc's output (tests/*.expected)."""
    failed = []
    count = 0
    for path in sorted(TESTS.glob("*.c")):
        expected = path.with_suffix(".expected")
        if not expected.exists():
            continue
        keys = path.with_suffix(".keys")
        program, _ = driver.build([str(path)])
        cpu, out = driver.run_in_simulator(program.rom, keys.read_text() if keys.exists() else "",
                                           50_000_000)
        count += 1
        if not cpu.halted or out != expected.read_text():
            failed.append(path.stem)
    assert not failed, "different from the expected output: " + ", ".join(failed)
    return f"{count} programs"


def check_exit_and_atexit():
    cpu, out = run_c(r"""
        #include <stdio.h>
        #include <stdlib.h>
        static void bye(void) { puts("bye"); }
        int main(void) { atexit(bye); puts("main"); return 7; }""")
    assert out == "main\nbye\n" and cpu.regs[0] == 7, (out, cpu.regs[0])
    cpu, out = run_c(r"""
        #include <stdlib.h>
        int main(void) { exit(3); return 1; }""")
    assert cpu.regs[0] == 3


def check_input():
    """getchar reads a line at a time with echo and backspace; Ctrl-D is EOF."""
    out = output(r"""
        #include <stdio.h>
        int main(void) {
            int c, n = 0;
            while ((c = getchar()) != EOF)
                if (c != '\n')
                    n++;
            printf("[%d]\n", n);
            return 0;
        }""", keys="ab\bc\nxyz\n\x04")
    assert out == "ac\nxyz\n[5]\n", repr(out)
    out = output(r"""
        #include <stdio.h>
        int main(void) {
            int a, b;
            char word[20];
            printf("? ");
            if (scanf("%d %d %19s", &a, &b, word) == 3)
                printf("%d %s\n", a + b, word);
            return 0;
        }""", keys="12 30 hello\n")
    assert out == "? 12 30 hello\n42 hello\n", repr(out)


def check_globals_reset():
    """Global variables get their starting values again after a reset
    (the init routines don't rely on RAM being clear)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "g.c"
        path.write_text(r"""
            #include <stdio.h>
            int counter = 5;
            int zeroed;
            int main(void) { printf("%d %d\n", counter++, zeroed++); return 0; }""")
        program, _ = driver.build([str(path)])
    import cpu as cpu_module
    machine = cpu_module.CPU()
    machine.mem.load_rom(program.rom)
    machine.run(1_000_000)
    machine.reset(clear_ram=False)
    machine.run(1_000_000)
    assert machine.bus.display.text == "5 0\n", repr(machine.bus.display.text)


def check_library_override():
    """A program may define its own function with a C library name."""
    out = output(r"""
        #include <stdio.h>
        int puts(const char *s) { while (*s) putchar(*s++ - 32); putchar('!'); return 0; }
        int main(void) { puts("abc"); return 0; }""")
    assert out == "ABC!", repr(out)


def check_names_the_assembler_reserves():
    """C names that are instruction or register names get a _X prefix."""
    out = output(r"""
        #include <stdio.h>
        int add(int a, int b) { return a + b; }
        int r1 = 4, data = 2;
        int main(void) { printf("%d\n", add(r1, data)); return 0; }""")
    assert out == "6\n", out


def check_mixed_with_assembly():
    """C calls an assembly function and the other way round."""
    with tempfile.TemporaryDirectory() as tmp:
        c = Path(tmp) / "main.c"
        asm = Path(tmp) / "twice.asm"
        c.write_text(r"""
            #include <stdio.h>
            int twice(int n);
            int plus_one(int n) { return n + 1; }
            int main(void) { printf("%d\n", twice(20)); return 0; }""")
        asm.write_text("""
                .global twice
                .extern plus_one
        twice:  DATA R1, -2
                STK GET, R1        ; R0 = n
                ADD R0, R0
                STK PUSH
                CALL plus_one, 1   ; 2n + 1
                RET
        """)
        program, _ = driver.build([str(c), str(asm)])
    cpu, out = driver.run_in_simulator(program.rom)
    assert out == "41\n", out


def check_command_line():
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        tmp = Path(tmp)
        src = tmp / "hello.c"
        src.write_text('#include <stdio.h>\nint main(void) { puts("hi"); return 0; }\n')
        assert cli.main(["compile", str(src), "-o", str(tmp / "hello.asm")]) == 0
        assert (tmp / "hello.asm").exists()
        assert cli.main(["build", str(src), "-o", str(tmp / "hello.rom"), "--map"]) == 0
        assert (tmp / "hello.rom").exists() and (tmp / "hello.map").exists()
        bad = tmp / "bad.c"
        bad.write_text("int main(void) { return y; }\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert cli.main(["build", str(bad), "-o", str(tmp / "bad.rom")]) == 1
        assert "'y' undeclared" in err.getvalue() and "bad.c:1:" in err.getvalue()
        assert not (tmp / "bad.rom").exists()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "run.c"
            src.write_text('#include <stdio.h>\nint main(void) { printf("%d", 6 * 7); return 0; }\n')
            assert cli.main(["run", str(src), "-o", str(Path(tmp) / "run.rom")]) == 0
    assert out.getvalue() == "42\n", repr(out.getvalue())


CHECKS = [
    check_preprocessor,
    check_errors,
    check_warnings,
    check_sizes,
    check_exit_and_atexit,
    check_input,
    check_globals_reset,
    check_library_override,
    check_names_the_assembler_reserves,
    check_mixed_with_assembly,
    check_command_line,
    check_programs,
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
