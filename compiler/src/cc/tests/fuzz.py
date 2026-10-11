"""Random C programs, built with gcc and with the tiny C compiler: their
outputs must be the same.

    python compiler/src/cc/tests/fuzz.py [--count N] [--seed S] [--keep]

Each program is free of undefined behaviour (unsigned arithmetic, shift
counts masked to 0..31, divisors that can't be 0 or -1, array indexes
masked to the array, no recursion) and of unspecified evaluation order (a
call is always a whole statement, never part of an expression), and prints
checksums of its variables. Programs gcc's sanitizer or warnings object to
are skipped, as the generator's fault. Float values are kept between -1e6 and 1e6 (sq()), so no
infinity or NaN appears, and are printed as their bits: any difference in
rounding shows. Programs also use a local array whose address is taken,
a global pointer into an array, and a struct passed and returned by value. A program whose outputs differ is saved in compiler/ROM/fuzz/
(git-ignored) for a closer look; --keep saves every program.
"""

import argparse
import random
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import driver                     # noqa: E402
from driver import BuildError     # noqa: E402

OUT = HERE.parent.parent.parent / "ROM" / "fuzz"
ARRAY = 8


class Gen:
    def __init__(self, rng):
        self.r = rng
        self.lines = []
        self.scope = set()

    def const(self):
        r = self.r.random()
        if r < 0.4:
            return str(self.r.randint(0, 9))
        if r < 0.7:
            return str(self.r.randint(10, 1000))
        if r < 0.85:
            return f"{self.r.randint(0, 0xFFFFFFFF)}u"
        return self.r.choice(["0x80000000u", "0xFFFFFFFFu", "0x7FFFFFFFu", "1u", "31u"])

    def fexpr(self, names, depth):
        """A float expression with |value| < 1e6 * 1e6 (callers wrap it in sq())."""
        if depth <= 0 or self.r.random() < 0.3:
            pick = self.r.random()
            if pick < 0.4:
                return self.r.choice(["fv0", "fv1", "g_f"])
            if pick < 0.6:
                return f"({self.r.choice(['', '-'])}{self.r.randint(0, 999)}.{self.r.randint(0, 99)}f)"
            if pick < 0.8:
                return f"(float)({self.expr(names, 1)} & 0xFFFFu)"
            if pick < 0.9:
                return f"sq((float){self.expr(names, 1)})"
            return f"sq((float)(int){self.expr(names, 1)})"
        a = self.fexpr(names, 0 if depth <= 1 else depth - 1)
        b = self.fexpr(names, 0)
        op = self.r.choice(["+", "-", "*", "/", "neg"])
        if op == "/":
            return f"({a} / ({b} * {b} + 1.0f))"
        if op == "neg":
            return f"(-({a}))"
        return f"sq({a} {op} {b})"

    def expr(self, names, depth, fns=()):
        """An unsigned expression."""
        r = self.r.random()
        if depth <= 0 or r < 0.25:
            pick = self.r.random()
            if pick < 0.5 and names:
                return self.r.choice(names)
            if pick < 0.6:
                return f"g_arr[{self.expr(names, 0)} & {ARRAY - 1}]"
            if pick < 0.66:
                return f"g_s.{self.r.choice('abc')}"
            if pick < 0.72 and "la" in self.scope:
                return f"la[{self.expr(names, 0)} & {ARRAY - 1}]"
            if pick < 0.76:
                return "*g_p"
            if pick < 0.8:
                c = self.r.choice(["<", "<=", ">", ">=", "==", "!="])
                return f"(unsigned)({self.fexpr(names, 1)} {c} {self.fexpr(names, 1)})"
            if pick < 0.84:
                return f"(unsigned)(int)sq({self.fexpr(names, 1)})"
            if pick < 0.87:
                return f"sum(mk({self.expr(names, 0)}, {self.expr(names, 0)}))"
            return self.const()
        a = self.expr(names, depth - 1, fns)
        b = self.expr(names, depth - 1, fns)
        op = self.r.choice(["+", "-", "*", "&", "|", "^", "<<", ">>", "/", "%",
                            "<", "<=", ">", ">=", "==", "!=", "&&", "||",
                            "sdiv", "smod", "sshr", "scmp", "?:", "~", "neg", "!", "call",
                            "cast"])
        if op in ("<<", ">>"):
            return f"({a} {op} ({b} & 31u))"
        if op in ("/", "%"):
            return f"({a} {op} (({b} & 0xFFFFu) + 1u))"
        if op in ("sdiv", "smod"):
            o = "/" if op == "sdiv" else "%"
            return f"(unsigned)((int){a} {o} (int)(({b} & 0x7Fu) + 1u))"
        if op == "sshr":
            return f"(unsigned)((int){a} >> ({b} & 31u))"
        if op == "scmp":
            c = self.r.choice(["<", "<=", ">", ">="])
            return f"(unsigned)((int){a} {c} (int){b})"
        if op == "?:":
            c = self.expr(names, depth - 1, fns)
            return f"({c} ? {a} : {b})"
        if op == "~":
            return f"(~{a})"
        if op == "neg":
            return f"(-{a})"
        if op == "!":
            return f"(unsigned)(!{a})"
        if op == "call":
            # A call inside a bigger expression could change a global the
            # rest of the expression reads, and C leaves that order
            # unspecified (gcc and this compiler differ). Calls are whole
            # statements instead (see stmt); here it is just an addition.
            if True:
                return f"({a} + {b})"
            f, n = self.r.choice(fns)
            args = ", ".join(self.expr(names, depth - 1) for _ in range(n))
            return f"{f}({args})"
        if op == "cast":
            return f"(unsigned)(int){a}"
        if op in ("<", "<=", ">", ">=", "==", "!=", "&&", "||"):
            return f"(unsigned)({a} {op} {b})"
        return f"({a} {op} {b})"

    def stmt(self, names, depth, indent, fns, loopvars):
        pad = "    " * indent
        r = self.r.random()
        if depth > 0 and r < 0.15:
            c = self.expr(names, 2, fns)
            self.lines.append(f"{pad}if ({c}) {{")
            self.block(names, depth - 1, indent + 1, fns, loopvars)
            if self.r.random() < 0.5:
                self.lines.append(f"{pad}}} else {{")
                self.block(names, depth - 1, indent + 1, fns, loopvars)
            self.lines.append(f"{pad}}}")
            return
        if depth > 0 and r < 0.27 and len(loopvars) < 3:
            k = f"k{len(loopvars)}"
            n = self.r.randint(1, 5)
            self.lines.append(f"{pad}for ({k} = 0; {k} < {n}u; {k}++) {{")
            self.block(names + [k], depth - 1, indent + 1, fns, loopvars + [k])
            self.lines.append(f"{pad}}}")
            return
        if depth > 0 and r < 0.33:
            c = self.expr(names, 2, fns)
            self.lines.append(f"{pad}switch ({c} & 7u) {{")
            for case in self.r.sample(range(8), self.r.randint(1, 5)):
                self.lines.append(f"{pad}case {case}:")
                self.block(names, depth - 1, indent + 1, fns, loopvars, braces=False)
                if self.r.random() < 0.7:
                    self.lines.append(f"{pad}    break;")
            if self.r.random() < 0.5:
                self.lines.append(f"{pad}default:")
                self.block(names, depth - 1, indent + 1, fns, loopvars, braces=False)
            self.lines.append(f"{pad}}}")
            return
        targets = [n for n in names if n not in loopvars]
        if not targets:
            targets = ["g0"]
        t = self.r.choice(targets)
        r = self.r.random()
        if r < 0.06:
            self.lines.append(f"{pad}{self.r.choice(['fv0', 'fv1', 'g_f'])} = sq({self.fexpr(names, 2)});")
            return
        if r < 0.09 and "la" in self.scope:
            self.lines.append(f"{pad}la[{self.expr(names, 1)} & {ARRAY - 1}] = {self.expr(names, 2, fns)};")
            return
        if r < 0.11:
            self.lines.append(f"{pad}g_p = g_arr + ({self.expr(names, 1)} & {ARRAY - 1});")
            return
        if r < 0.13:
            self.lines.append(f"{pad}*g_p += {self.expr(names, 1)};")
            return
        if r < 0.15 and "la" in self.scope:
            self.lines.append(f"{pad}fill(la, {self.expr(names, 1)});")
            return
        r = self.r.random()
        if r < 0.1:
            self.lines.append(f"{pad}g_arr[{self.expr(names, 1)} & {ARRAY - 1}] = {self.expr(names, 2, fns)};")
        elif r < 0.17:
            self.lines.append(f"{pad}g_s.{self.r.choice('abc')} {self.r.choice(['=', '+=', '^='])} {self.expr(names, 2, fns)};")
        elif r < 0.3:
            op = self.r.choice(["+=", "-=", "*=", "&=", "|=", "^="])
            self.lines.append(f"{pad}{t} {op} {self.expr(names, 2, fns)};")
        elif r < 0.36:
            self.lines.append(f"{pad}{t} <<= ({self.expr(names, 1)} & 31u);")
        elif r < 0.42:
            self.lines.append(f"{pad}{self.r.choice([t + '++', t + '--', '++' + t, '--' + t])};")
        elif r < 0.5 and fns:
            f, n = self.r.choice(fns)
            args = ", ".join(self.expr(names, 1) for _ in range(n))
            self.lines.append(f"{pad}{t} = {f}({args});")
        elif r < 0.55:
            self.lines.append(f"{pad}{t} = {t}++ + {self.expr(names, 1)};".replace(f"{t}++ +", f"{t} +"))
        else:
            self.lines.append(f"{pad}{t} = {self.expr(names, 3, fns)};")

    def block(self, names, depth, indent, fns, loopvars, braces=True):
        for _ in range(self.r.randint(1, 3)):
            self.stmt(names, depth, indent, fns, loopvars)

    def function(self, i, nparams, fns):
        params = [f"p{j}" for j in range(nparams)]
        locs = [f"v{j}" for j in range(self.r.randint(1, 4))]
        sig = ", ".join(f"unsigned {p}" for p in params) or "void"
        self.lines.append(f"static unsigned f{i}({sig})")
        self.lines.append("{")
        self.lines.append("    unsigned k0, k1, k2;")
        self.lines.append("    float fv0 = g_f, fv1 = 0.5f;")
        self.scope = set()
        if self.r.random() < 0.5:
            first = self.expr(params, 1)          # before la exists: it can't read la
            self.lines.append(f"    unsigned la[{ARRAY}];")
            self.lines.append(f"    fill(la, {first});")
            self.scope = {"la"}
        for v in locs:
            self.lines.append(f"    unsigned {v} = {self.expr(params, 2)};")
        names = params + locs + ["g0", "g1"]
        self.block(names, 2, 1, fns, [])
        ret = self.expr(names, 3)
        if self.scope:
            ret = f"({ret}) ^ la[{self.expr(names, 0)} & {ARRAY - 1}]"
        self.lines.append(f"    return {ret} ^ (unsigned)(int)sq(fv0 + fv1);")
        self.scope = set()
        self.lines.append("}")
        self.lines.append("")

    def program(self):
        L = self.lines
        self.scope = set()
        L.append("#include <stdio.h>")
        L.append("")
        L.append(f"unsigned g0 = {self.const()}, g1;")
        L.append(f"unsigned g_arr[{ARRAY}] = {{ " + ", ".join(self.const() for _ in range(ARRAY)) + " };")
        L.append(f"struct {{ unsigned a, b, c; }} g_s = {{ {self.const()}, {self.const()}, {self.const()} }};")
        L.append(f"float g_f = {self.r.randint(-500, 500)}.25f;")
        L.append("unsigned *g_p = g_arr;")
        L.append("struct pt { unsigned a, b; float c; };")
        L.append("")
        L.append("static float sq(float x) { return x > 1e6f ? 1e6f : x < -1e6f ? -1e6f : x; }")
        L.append("static struct pt mk(unsigned a, unsigned b) { struct pt p; p.a = a; p.b = b ^ a; p.c = (float)(a & 0xFFu); return p; }")
        L.append("static unsigned sum(struct pt p) { return p.a * 3u + p.b + (unsigned)(int)p.c; }")
        L.append(f"static void fill(unsigned *a, unsigned v) {{ unsigned i; for (i = 0; i < {ARRAY}u; i++) a[i] = v * i + 7u; }}")
        L.append("static unsigned fbits(float f) { union { float f; unsigned u; } b; b.f = f; return b.u; }")
        L.append("")
        fns = []
        for i in range(self.r.randint(2, 5)):
            n = self.r.randint(0, 3)
            self.function(i, n, list(fns))
            fns.append((f"f{i}", n))
        L.append("int main(void)")
        L.append("{")
        L.append("    unsigned k0, k1, k2, r = 0;")
        L.append("    float fv0 = 1.0f, fv1 = -2.5f;")
        for f, n in fns:
            args = ", ".join(self.expr(["g0", "g1"], 2) for _ in range(n))
            L.append(f"    r ^= {f}({args});")
            L.append("    printf(\"%u %u %u\\n\", r, g0, g1);")
        L.append("    for (k0 = 0; k0 < 8u; k0++)")
        L.append("        printf(\"%u \", g_arr[k0]);")
        L.append("    printf(\"\\n%u %u %u\\n\", g_s.a, g_s.b, g_s.c);")
        L.append("    printf(\"%08x %u\\n\", fbits(g_f), (unsigned)(g_p - g_arr));")
        L.append("    (void)k1;")
        L.append("    (void)fv0;")
        L.append("    (void)fv1;")
        L.append("    (void)k2;")
        L.append("    return 0;")
        L.append("}")
        return "\n".join(L) + "\n"


def well_defined(src, tmp):
    """gcc's view: no uninitialised reads or missing returns it can see, and
    no undefined behaviour its sanitizer catches when the program runs. A
    program that fails this is the generator's fault, not the compiler's."""
    c = Path(tmp) / "chk.c"
    exe = Path(tmp) / "chk"
    c.write_text(src)
    r = subprocess.run(["gcc", "-std=gnu99", "-O1", "-w", "-Werror=uninitialized",
                        "-Werror=return-type", "-fsanitize=undefined,float-cast-overflow",
                        "-fno-sanitize-recover", "-o", str(exe), str(c)], capture_output=True)
    if r.returncode:
        return False
    try:
        return subprocess.run([str(exe)], capture_output=True, timeout=20).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def gcc_run(src, tmp):
    exe = Path(tmp) / "a.out"
    c = Path(tmp) / "f.c"
    c.write_text(src)
    subprocess.run(["gcc", "-std=gnu99", "-w", "-ffp-contract=off", "-o", str(exe), str(c)],
                   check=True, capture_output=True)
    return subprocess.run([str(exe)], capture_output=True, text=True, timeout=20).stdout


def tiny_run(src, tmp):
    c = Path(tmp) / "f.c"
    c.write_text(src)
    program, _ = driver.build([str(c)])
    cpu, out = driver.run_in_simulator(program.rom, max_steps=20_000_000)
    if not cpu.halted:
        out += "\n--- did not halt ---\n"
    return out, cpu.instructions


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    bad = 0
    skipped = 0
    total_steps = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(args.count):
            seed = args.seed + i
            src = Gen(random.Random(seed)).program()
            if not well_defined(src, tmp):
                skipped += 1
                continue
            try:
                want = gcc_run(src, tmp)
            except subprocess.TimeoutExpired:
                continue                      # a program gcc's build doesn't finish: skip it
            try:
                got, steps = tiny_run(src, tmp)
            except BuildError as e:
                got, steps = "BUILD ERROR\n" + "\n".join(e.messages), 0
            total_steps += steps
            if got != want or args.keep:
                OUT.mkdir(parents=True, exist_ok=True)
                (OUT / f"fuzz{seed}.c").write_text(src)
            if got != want:
                bad += 1
                print(f"seed {seed}: DIFFERENT (saved in {OUT / f'fuzz{seed}.c'})")
                for a, b in zip(want.splitlines(), got.splitlines()):
                    if a != b:
                        print(f"   gcc:  {a}\n   tiny: {b}")
                        break
    print(f"{args.count - bad - skipped} of {args.count - skipped} random programs agree "
          f"({total_steps} instructions in all; {skipped} skipped as not well defined)")
    return bad == 0


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1:]) else 1)
