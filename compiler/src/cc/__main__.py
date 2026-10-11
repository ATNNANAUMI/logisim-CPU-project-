"""Command line for the C compiler. Run it from the project root:

    python compiler/src/cc compile prog.c          -> compiler/ROM/prog.asm
    python compiler/src/cc build prog.c [more]     -> compiler/ROM/prog.rom
    python compiler/src/cc run prog.c [more]       build, then run it in the simulator

build and run take .c, .asm and .obj files together. The C library is
linked in automatically (--no-libc leaves it out; then the program needs
its own 'start'). Output goes to compiler/ROM/ like the assembler's; -o picks
the name (a path with a folder is used as written). build also writes the
.asm of each .c file next to the .rom, for reading.
"""

import argparse
import sys
from pathlib import Path

import driver
from cerror import CError, CErrors
from driver import BuildError


def add_common(p):
    p.add_argument("-I", dest="include", action="append", default=[],
                   help="also look for #include files in this folder")
    p.add_argument("-D", dest="define", action="append", default=[],
                   help="define a macro: -D NAME or -D NAME=value")
    p.add_argument("-w", dest="no_warn", action="store_true", help="hide warnings")


def main(argv=None):
    cli = argparse.ArgumentParser(
        prog="python compiler/src/cc",
        description="C compiler for the logic-gate CPU.")
    commands = cli.add_subparsers(dest="command", required=True)

    p = commands.add_parser("compile", help="turn one .c file into assembly")
    p.add_argument("source")
    p.add_argument("-o", "--output", help="output file (default: compiler/ROM/<source>.asm)")
    add_common(p)

    for name, help_text in (("build", "compile, assemble and link into a ROM image"),
                            ("run", "build, then run in the simulator (no window)")):
        p = commands.add_parser(name, help=help_text)
        p.add_argument("inputs", nargs="+")
        p.add_argument("-o", "--output", help="output file (default: compiler/ROM/<first input>.rom)")
        p.add_argument("--map", action="store_true", help="also write a .map file of label addresses")
        p.add_argument("--no-libc", action="store_true", help="don't link the C library")
        p.add_argument("--lib", action="append", default=[], metavar="FILE",
                       help="link FILE (.asm/.obj) as a library: only what the program uses")
        add_common(p)
        if name == "run":
            p.add_argument("--keys", default="", help="keys typed before the program starts")
            p.add_argument("--steps", type=int, default=50_000_000,
                           help="stop after this many instructions (default 50 000 000)")
            p.add_argument("--trace", action="store_true", help="print every instruction")
            p.add_argument("--stats", action="store_true",
                           help="print the instruction count and the registers at the end")

    args = cli.parse_args(argv)
    warn = None if args.no_warn else driver.print_warning
    try:
        if args.command == "compile":
            text = driver.compile_c(args.source, args.include, args.define, warn=warn)
            out = driver.output_path(args.output, args.source, ".asm")
            out.write_text(text, encoding="utf-8")
            print(f"{out}: {text.count(chr(10))} lines of assembly")
            return 0

        out = driver.output_path(args.output, args.inputs[0], ".rom")
        program, _ = driver.build(args.inputs, args.include, args.define,
                                  asm_dir=out.parent, use_libc=not args.no_libc, warn=warn,
                                  libs=args.lib)
        out.write_text(driver.format_rom(program), encoding="utf-8")
        if args.map:
            out.with_suffix(".map").write_text(driver.format_map(program, out.name),
                                               encoding="utf-8")
        if args.command == "build":
            print(f"{out}: {len(program.rom)} words of ROM, {program.ram_used} words of RAM")
            return 0

        cpu, text = driver.run_in_simulator(program.rom, args.keys, args.steps, args.trace)
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        if not cpu.halted:
            print(f"--- stopped after {cpu.instructions} instructions without halting ---",
                  file=sys.stderr)
            return 2
        if args.stats:
            print(f"--- halted after {cpu.instructions} instructions, R0 = "
                  f"{cpu.regs[0] - (1 << 32) if cpu.regs[0] & 0x80000000 else cpu.regs[0]} ---",
                  file=sys.stderr)
        return 0
    except BuildError as e:
        for m in e.messages:
            print(m, file=sys.stderr)
        print(f"{len(e.messages)} error(s), nothing written", file=sys.stderr)
        return 1
    except CErrors as e:
        for err in e.errors:
            print(err, file=sys.stderr)
        return 1
    except CError as e:
        print(e, file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
