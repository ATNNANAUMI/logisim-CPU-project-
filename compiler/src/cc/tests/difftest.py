"""Compare the C compiler with gcc on the test programs in this folder.

    python compiler/src/cc/tests/difftest.py [names...] [--update]

Each test program is compiled with the host's gcc and run, and compiled with
the tiny C compiler and run in the simulator; the two outputs must be the
same. --update writes gcc's output to <name>.expected, which is what the
self-checks (compiler/src/cc/selftest.py) compare against without needing
gcc. A test with a <name>.keys file reads those keys as its input: such a
test has a hand-written .expected (our input is echoed on the display, a
pipe into gcc's program is not), so it is only run here, not compared.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import driver                     # noqa: E402
from driver import BuildError     # noqa: E402


def gcc_output(path, tmp):
    exe = Path(tmp) / path.stem
    subprocess.run(["gcc", "-std=gnu99", "-w", "-o", str(exe), str(path), "-lm"],
                   check=True, capture_output=True, text=True)
    return subprocess.run([str(exe)], capture_output=True, text=True, timeout=30).stdout


def tiny_output(path):
    program, _ = driver.build([str(path)])
    keys = path.with_suffix(".keys")
    cpu, text = driver.run_in_simulator(program.rom, keys.read_text() if keys.exists() else "",
                                        max_steps=50_000_000)
    if not cpu.halted:
        text += "\n--- did not halt ---\n"
    return text, cpu.instructions


def main(argv):
    update = "--update" in argv
    names = [a for a in argv if not a.startswith("--")]
    tests = sorted(HERE.glob("*.c")) if not names else [HERE / (n.removesuffix(".c") + ".c")
                                                        for n in names]
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for path in tests:
            try:
                got, steps = tiny_output(path)
            except BuildError as e:
                print(f"FAIL  {path.stem}: doesn't build\n      " + "\n      ".join(e.messages))
                failed += 1
                continue
            if path.with_suffix(".keys").exists():
                want = path.with_suffix(".expected").read_text()
                status = "ok  " if got == want else "FAIL"
            else:
                want = gcc_output(path, tmp)
                status = "ok  " if got == want else "FAIL"
                if update and got == want:
                    path.with_suffix(".expected").write_text(want)
            print(f"{status}  {path.stem:<12} {steps:>9} instructions")
            if status == "FAIL":
                failed += 1
                for i, (a, b) in enumerate(zip(want.splitlines(), got.splitlines())):
                    if a != b:
                        print(f"      line {i + 1}: gcc  {a!r}\n      {'':>{len(str(i + 1)) + 5}} tiny {b!r}")
                        break
                else:
                    print(f"      lengths differ: gcc {len(want)}, tiny {len(got)} characters")
    print(f"\n{len(tests) - failed} of {len(tests)} programs give gcc's output")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1:]) else 1)
