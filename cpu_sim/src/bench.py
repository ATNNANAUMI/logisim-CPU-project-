"""How fast the simulator runs: python cpu_sim/src/bench.py [names] [--scale F] [--repeat N]

Builds a few example programs (once, into compiler/ROM/bench/), runs each
headless in CPU.run() and prints the speed in MHz (millions of simulated
instructions a second; only run() is timed, not the building or loading).
Each program runs --repeat times on one CPU, reset in between: "first" is
the first run (the translation of the program's code, and pypy3's JIT
warm-up, are in it), "best" the fastest of the others. The digest is a hash
of the machine state at the end (registers, flags, count, display, screen):
an optimisation of the simulator must leave it unchanged. The timer is
stopped at 0 (clock() returns 0), so every run does the same work.

    pypy3 cpu_sim/src/bench.py                  every program
    python cpu_sim/src/bench.py life sqrt --scale 0.1
                                                CPython is about ten times
                                                slower: --scale shortens the
                                                fixed-length runs
    --rebuild                                   build the programs again
"""

import argparse
import hashlib
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent                  # cpu_sim/src
ROOT = HERE.parent.parent
OUT = ROOT / "compiler" / "ROM" / "bench"
sys.path.insert(0, str(HERE))

from cpu import CPU                     # noqa: E402
from devices import Timer               # noqa: E402
from memory import load_image           # noqa: E402

EXAMPLES = ROOT / "compiler" / "examples"

# name: (sources, keys, steps). steps None: run to HALT (the --scale doesn't
# shorten it); a number: that many instructions (a program that doesn't end).
WORKLOADS = {
    "life":    (["c/games/game_of_life.c"], "", 20_000_000),        # integer, arrays
    "sqrt":    (["c/tests/benchmark.c"], "", 20_000_000),           # floats, calls
    "qr":      (["c/graphics/qr.c"], "\x04", None),                 # bytes, tables, screen
    "grapher": (["c/graphics/grapher.c"], "demo\n\x04", None),      # float library, screen
    "image":   (["c/graphics/image_demo.c"], "", None),             # gfx_image (bit stream)
    "queens":  (["../src/cc/tests/queens.c"], "", None),            # recursion, printf
    "asm":     (["asm/stdlib/stdlib_demo.asm", "asm/stdlib/stdlib.asm"], "", None),
    "shell":   (["../../tynix/shell.c"],                            # the OS: commands, the disk
                "ls -l /\nhelp\necho hi > /a.txt\ncat /a.txt /readme.txt\n"
                + "/bin/echo a b c\n/bin/echo x > /b.txt\ncp /readme.txt /c.txt\ncat /c.txt\n" * 4
                + "cp /bin/echo /e2\n/e2 copy\nls\ndf\nhalt\n", None),
    "os":      (["../../tynix/shell.c"], "game_of_life\n", 20_000_000),  # a program in RAM (/bin)
}
DISKS = {"shell": ["echo"], "os": ["game_of_life"]}         # what the disk's /bin holds


def build(name, sources, rebuild):
    """The program's ROM words (built into OUT/name.rom the first time)."""
    rom = OUT / f"{name}.rom"
    if rebuild or not rom.exists():
        sys.path.append(str(ROOT / "compiler" / "src" / "cc"))
        import driver                                   # compiler/src/cc (and src/asm)
        import linker
        paths = [str((EXAMPLES / s).resolve()) for s in sources]
        if paths[0].endswith(".c"):
            program, _ = driver.build(paths)
        else:
            from assembler import assemble
            objects = [assemble(Path(p).read_text(), p)[0] for p in paths]
            program = linker.link(objects)
        OUT.mkdir(parents=True, exist_ok=True)
        rom.write_text(linker.format_raw(program.rom))
    return load_image(str(rom))


def disk_image(name, rebuild):
    """A pristine 1 MB disk for the shell: TFS1, DISKS[name] in /bin, /readme.txt."""
    image = OUT / f"{name}.img"
    if rebuild or not image.exists():
        sys.path.append(str(ROOT / "tynix"))
        import make_disk
        OUT.mkdir(parents=True, exist_ok=True)
        make_disk.make(image, programs=DISKS[name], new=True, size_mb=1, log=lambda _: None)
    return image


def digest(cpu):
    state = repr((cpu.regs, cpu.iar, cpu.flags, cpu.esp, cpu.ebp, cpu.halted, cpu.stopped,
                  cpu.instructions, cpu.bus.display.text, cpu.bus.hex_value,
                  cpu.bus.video.pixels, cpu.bus.out_addr, cpu.bus.in_addr))
    return hashlib.sha1(state.encode()).hexdigest()[:10]


def measure(name, rom, keys, steps, repeat, disk):
    cpu = CPU()
    cpu.mem.load_rom(rom)
    cpu.bus.timer = Timer(clock=lambda: 0.0)    # clock() stays at 0: the same run every time
    times, counts, digests = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        for _ in range(repeat):
            cpu.reset()
            cpu.bus.keyboard.type(keys)
            if disk:
                shutil.copy(disk, os.path.join(tmp, "disk.img"))
                cpu.bus.attach_disk(os.path.join(tmp, "disk.img"))
            start = time.perf_counter()
            count = cpu.run(steps or 200_000_000)
            times.append(time.perf_counter() - start)
            counts.append(count)
            digests.append(digest(cpu))
            cpu.bus.attach_disk(None)
            if steps is None and not cpu.halted:
                raise SystemExit(f"{name}: did not halt")
    if len(set(digests)) != 1 or len(set(counts)) != 1:
        raise SystemExit(f"{name}: the runs ended differently: {digests}")
    rates = [c / t / 1e6 for c, t in zip(counts, times)]
    best = max(rates[1:]) if len(rates) > 1 else rates[0]
    return counts[0], rates[0], best, digests[0]


def main(argv=None):
    p = argparse.ArgumentParser(description="Simulator speed, in MHz.")
    p.add_argument("names", nargs="*", help=f"some of: {' '.join(WORKLOADS)}")
    p.add_argument("--scale", type=float, default=None,
                   help="multiply the fixed run lengths (default 1, 0.1 on CPython)")
    p.add_argument("--repeat", type=int, default=3, help="runs of each program (default 3)")
    p.add_argument("--rebuild", action="store_true", help="build the programs again")
    args = p.parse_args(argv)
    names = args.names or list(WORKLOADS)
    for n in names:
        if n not in WORKLOADS:
            p.error(f"no program {n!r}: {' '.join(WORKLOADS)}")
    pypy = platform.python_implementation() == "PyPy"
    scale = args.scale if args.scale is not None else (1.0 if pypy else 0.1)
    print(f"{platform.python_implementation()} {platform.python_version()}, "
          f"scale {scale}, {args.repeat} runs each")
    print(f"{'program':8s} {'instructions':>12s} {'first MHz':>9s} {'best MHz':>9s}  digest")
    total_count = total_time = 0.0
    for name in names:
        sources, keys, steps = WORKLOADS[name]
        rom = build(name, sources, args.rebuild)
        disk = disk_image(name, args.rebuild) if name in DISKS else None
        if steps:
            steps = max(1, int(steps * scale))
        count, first, best, dig = measure(name, rom, keys, steps, args.repeat, disk)
        print(f"{name:8s} {count:12d} {first:9.2f} {best:9.2f}  {dig}", flush=True)
        total_count += count
        total_time += count / (best * 1e6)
    print(f"{'all':8s} {int(total_count):12d} {'':9s} {total_count / total_time / 1e6:9.2f}"
          "  (the best runs together)")


if __name__ == "__main__":
    main()
