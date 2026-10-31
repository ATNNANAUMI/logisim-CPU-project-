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
from cerror import CError, CErrors
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


def output_lines(text):
    return text.strip().splitlines()


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
    except CErrors as e:
        if any(fragment in x.message for x in e.errors):
            return
        raise AssertionError(f"wrong errors for {text!r}: {e}")
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
    ins = lambda *a: ("ins", a[0], tuple(a[1:]))        # peephole: STK GET right after STK SET
    import peephole
    got = peephole.optimize([ins("STK", "SET", "R13"), ("comment", "x"), ins("STK", "GET", "R13"),
                             ins("STK", "SET", "R13"), ins("STK", "GET", "R12"),
                             ins("STK", "SET", "R13"), ("label", "L"), ins("STK", "GET", "R13"),
                             ins("STK", "SET", "R13"), ins("ADD", "R1", "R2"), ins("STK", "GET", "R13")])
    assert [(i[1], i[2][0]) for i in got if i[0] == "ins"].count(("STK", "GET")) == 3, got
    with tempfile.TemporaryDirectory() as tmp:          # an editor's UTF-8 BOM is not a token
        bom = Path(tmp) / "bom.c"
        bom.write_bytes(b"\xef\xbb\xbfint x;\n")
        assert [t.text for t in Preprocessor().run_file(str(bom))][:3] == ["int", "x", ";"]


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


def check_several_errors():
    """Errors in different statements and functions are all reported."""
    text = """
        int f(void) { return x; }
        int g(void) { int a = 1; a = ; return a; }
        int main(void) { undeclared(); y = 2; return 0; }
    """
    try:
        parse(Preprocessor().run_text(text, "t.c"))
    except CErrors as e:
        messages = [str(x) for x in e.errors]
        assert len(messages) == 4, messages
        assert "'x' undeclared" in messages[0] and "t.c:2:" in messages[0], messages
        assert "expected an expression" in messages[1], messages
        assert "implicit declaration" in messages[2] and "'y' undeclared" in messages[3], messages
        return
    raise AssertionError("no errors")


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


def check_strtol_limits():
    """Overflow of the 32-bit word is found at the exact digit, in every base."""
    out = output(r"""
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <limits.h>
static void t(const char *s, int base)
{
    char *e;
    unsigned long v;
    errno = 0;
    v = strtoul(s, &e, base);
    printf("%s/%d: %lu %d %d\n", s, base, v, errno == ERANGE, (int)(e - s));
}
int main(void)
{
    t("4294967295", 10); t("4294967296", 10); t("42949672950", 10);
    t("ffffffff", 16); t("100000000", 16); t("0xFFFFFFFFg", 0);
    t("37777777777", 8); t("40000000000", 8);
    t("1z141z3", 36); t("1z141z4", 36); t("11111111111111111111111111111111", 2);
    t("100000000000000000000000000000000", 2); t("", 10); t("zz", 10);
    return 0;
}
""")
    assert output_lines(out) == [
        "4294967295/10: 4294967295 0 10", "4294967296/10: 4294967295 1 10",
        "42949672950/10: 4294967295 1 11", "ffffffff/16: 4294967295 0 8",
        "100000000/16: 4294967295 1 9", "0xFFFFFFFFg/0: 4294967295 0 10",
        "37777777777/8: 4294967295 0 11", "40000000000/8: 4294967295 1 11",
        "1z141z3/36: 4294967295 0 7", "1z141z4/36: 4294967295 1 7",
        "11111111111111111111111111111111/2: 4294967295 0 32",
        "100000000000000000000000000000000/2: 4294967295 1 33", "/10: 0 0 0", "zz/10: 0 0 0"], out


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


def check_big_memory():
    """24-bit banks: a ROM table, a RAM array and a malloc block each larger
    than the old 64K-word banks, and a call to code placed above them."""
    with tempfile.TemporaryDirectory() as tmp:
        main = Path(tmp) / "main.c"
        far = Path(tmp) / "far.c"              # linked after main's table
        main.write_text(r"""
            #include <stdio.h>
            #include <stdlib.h>
            static const int table[70000] = {7, 8};
            int big[70000];
            int twice(int x);
            int main(void)
            {
                int *p = malloc(100000 * sizeof(int));
                big[69999] = 5;
                p[99999] = 6;
                printf("%d %d %d %d %d\n", table[1], table[69999], big[69999],
                       p[99999], twice(21));
                printf("%d %d %d %d\n", (unsigned)&table[69999] > 0xFFFF,
                       (unsigned)twice > 0xFFFF, (unsigned)&big[69999] > 0x1FFFF,
                       (unsigned)p >= 0x1000000);
                return 0;
            }""")
        far.write_text("int twice(int x) { return x * 2; }\n")
        program, _ = driver.build([str(main), str(far)])
    cpu, out = driver.run_in_simulator(program.rom)
    assert out == "8 0 5 6 42\n1 1 1 1\n", out


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


def check_line_info():
    # build writes the C lines into the .map; the simulator window steps by them
    import sys
    if str(driver.SIM_DIR) not in sys.path:
        sys.path.append(str(driver.SIM_DIR))
    from cpu import CPU
    from debuginfo import DebugInfo, step_line, step_out
    from memory import load_image
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        tmp = Path(tmp)
        src = tmp / "lines.c"
        src.write_text("int twice(int x)\n{\n    return x + x;\n}\n"
                       "int main(void)\n{\n    int a = twice(2);\n"
                       "    a = twice(a);\n    return a;\n}\n")
        assert cli.main(["build", str(src), "-o", str(tmp / "lines.rom")]) == 0
        info = DebugInfo.for_rom(tmp / "lines.rom")
        cpu = CPU()
        cpu.mem.load_rom(load_image(tmp / "lines.rom"))
        where = []
        for how in ("over", "over", "into", "out", "over"):
            if how == "out":
                assert step_out(cpu, info) == "line"
            else:
                assert step_line(cpu, info, over=(how == "over")) == "line"
            where.append((info.function_at(cpu.iar), info.line_at(cpu.iar)[1]))
        assert where == [("main", 7), ("main", 8), ("twice", 3), ("main", 8), ("main", 9)], where
        cpu.breakpoints.update(info.addresses_of(str(src.resolve()), 3))
        cpu.reset()
        assert step_line(cpu, info, over=True) == "line"      # main:7
        assert step_line(cpu, info, over=True) == "breakpoint"
        assert info.line_at(cpu.iar)[1] == 3


CHECKS = [
    check_preprocessor,
    check_errors,
    check_several_errors,
    check_warnings,
    check_sizes,
    check_exit_and_atexit,
    check_strtol_limits,
    check_input,
    check_globals_reset,
    check_library_override,
    check_names_the_assembler_reserves,
    check_mixed_with_assembly,
    check_big_memory,
    check_command_line,
    check_line_info,
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
