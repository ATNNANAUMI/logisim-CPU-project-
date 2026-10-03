#!/usr/bin/env python3
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASM = ROOT / "compiler" / "src" / "asm"
SIM = ROOT / "cpu_sim" / "src"
SKIP = {".git", ".venv", "venv", "__pycache__", "node_modules"}

MENU = """what do you want to run?
  1) asm    assemble only
  2) sim    open the simulator
  3) build  assemble, then open the simulator
  4) test   both self-checks
"""
NAMES = {"1": "asm", "2": "sim", "3": "build", "4": "test"}


def need_tk():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit("tkinter is missing or broken. On Arch: sudo pacman -Syu && sudo pacman -S tk\n"
                 "Debian/Ubuntu: sudo apt install python3-tk | Fedora: sudo dnf install python3-tkinter")


def find(pattern):
    return sorted(p for p in ROOT.rglob(pattern) if not SKIP & set(p.relative_to(ROOT).parts))


def find_roms():
    roms = set(find("*.rom"))
    examples = SIM / "examples"
    if examples.is_dir():
        roms |= {p for p in examples.iterdir() if p.is_file()}
    return sorted(roms)


def pick(items, what, multi=True, optional=False):
    if not items:
        sys.exit(f"no {what} found")
    for i, p in enumerate(items, 1):
        print(f"  {i}) {p.relative_to(ROOT)}")
    hint = "numbers, e.g. 1 3" if multi else "one number"
    if optional:
        hint += ", Enter = none"
    while True:
        raw = input(f"{what} ({hint}): ").replace(",", " ").split()
        if not raw and optional:
            return []
        try:
            nums = [int(n) for n in raw]
            if nums and all(1 <= n <= len(items) for n in nums) and (multi or len(nums) == 1):
                return [items[n - 1] for n in nums]
        except ValueError:
            pass
        print("invalid, try again")


def run(*cmd):
    print("$ python", *cmd)
    code = subprocess.run([sys.executable, *map(str, cmd)]).returncode
    if code:
        sys.exit(code)


def do(cmd, args):
    if cmd == "asm":
        run(ASM, "build", *args)
    elif cmd == "sim":
        need_tk()
        run(SIM / "main.py", *args)
    elif cmd == "build":
        if "-o" not in args:
            sys.exit("build needs -o <output.rom>")
        need_tk()
        run(ASM, "build", *args)
        run(SIM / "main.py", args[args.index("-o") + 1])
    elif cmd == "test":
        run(ASM / "selftest.py")
        run(SIM / "selftest.py")
    else:
        sys.exit(f"unknown command: {cmd}")


def ask():
    print(MENU)
    choice = input("choice: ").strip().lower()
    cmd = NAMES.get(choice, choice)
    if cmd not in NAMES.values():
        sys.exit("pick 1-4, or asm / sim / build / test")

    if cmd in ("asm", "build"):
        srcs = pick(find("*.asm"), "source files (order = link order)")
        out = srcs[0].with_suffix(".rom")
        print(f"output: {out.relative_to(ROOT)}")
        return cmd, [*map(str, srcs), "-o", str(out)]
    if cmd == "sim":
        rom = pick(find_roms(), "ROM", multi=False, optional=True)
        return cmd, [*map(str, rom)]
    return cmd, []


if len(sys.argv) > 1:
    do(sys.argv[1], sys.argv[2:])
else:
    do(*ask())