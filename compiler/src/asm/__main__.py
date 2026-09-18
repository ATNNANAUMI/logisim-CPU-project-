"""Command line for the assembler and linker. Run it from the project root:

    python src/asm assemble prog.asm              -> prog.obj
    python src/asm link prog.obj lib.obj          -> prog.rom
    python src/asm build prog.asm lib.asm         -> prog.rom   (both steps)

-o NAME picks the output file. --map (link and build) also writes a .map
file listing every label's final address.
"""

import argparse
import sys
from pathlib import Path

import linker as linker
from assembler import assemble
from errors import AsmError, AsmErrors
from objfile import ObjectFile


def assemble_file(path):
    """Assemble one .asm file, printing its warnings. Raises AsmErrors."""
    text = Path(path).read_text(encoding="utf-8-sig")
    obj, warnings = assemble(text, str(path))
    for w in warnings:
        print(w.as_warning(), file=sys.stderr)
    return obj


def run_assemble(args):
    obj = assemble_file(args.source)
    out = Path(args.output) if args.output else Path(args.source).with_suffix(".obj")
    obj.save(out)
    print(f"{out}: {len(obj.rom)} words of ROM, {obj.ram_size} words of RAM")


def run_link(args):
    objects, problems = [], []
    for path in args.inputs:
        if args.command == "link" or path.endswith(".obj"):
            objects.append(ObjectFile.load(path))
        else:
            try:
                objects.append(assemble_file(path))
            except AsmErrors as e:
                problems.extend(e.errors)     # keep going to report every file
    if problems:
        raise AsmErrors(problems)

    program = linker.link(objects)
    out = Path(args.output) if args.output else Path(args.inputs[0]).with_suffix(".rom")
    out.write_text(linker.format_raw(program.rom), encoding="utf-8")
    print(f"{out}: {len(program.rom)} words of ROM, {program.ram_used} words of RAM")
    if args.map:
        map_path = out.with_suffix(".map")
        map_path.write_text(linker.format_map(program, out.name), encoding="utf-8")
        print(f"{map_path}: label addresses")


def main(argv=None):
    cli = argparse.ArgumentParser(
        prog="python src/asm",
        description="Assembler and linker for the logic-gate CPU.")
    commands = cli.add_subparsers(dest="command", required=True)

    p = commands.add_parser("assemble", help="turn one .asm file into an .obj file")
    p.add_argument("source")
    p.add_argument("-o", "--output", help="output file (default: source name .obj)")

    for name, help_text in (
            ("link", "join .obj files into a ROM image"),
            ("build", "assemble and link in one step (.asm and .obj files)")):
        p = commands.add_parser(name, help=help_text)
        p.add_argument("inputs", nargs="+")
        p.add_argument("-o", "--output", help="output file (default: first input's name .rom)")
        p.add_argument("--map", action="store_true",
                       help="also write a .map file with every label's address")

    args = cli.parse_args(argv)
    try:
        if args.command == "assemble":
            run_assemble(args)
        else:
            run_link(args)
    except AsmErrors as e:
        for err in e.errors:
            print(err, file=sys.stderr)
        print(f"{len(e.errors)} error(s), nothing written", file=sys.stderr)
        return 1
    except AsmError as e:
        print(e, file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
