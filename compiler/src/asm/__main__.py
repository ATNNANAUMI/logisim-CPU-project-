"""Command line for the assembler and linker. Run it from the project root:

    python compiler/src/asm assemble prog.asm         -> compiler/ROM/prog.obj
    python compiler/src/asm link prog.obj lib.obj     -> compiler/ROM/prog.rom
    python compiler/src/asm build prog.asm lib.asm    -> compiler/ROM/prog.rom

Everything is written to compiler/ROM/ (found from this file's location, so
it works from any folder). -o picks the output: a bare name (-o demo.rom)
still goes into compiler/ROM/, a path with a folder (-o out/demo.rom,
-o ./demo.rom) is used as written. --map (link and build) also writes a .map
file next to the .rom, listing every label's final address.
"""

import argparse
import sys
from pathlib import Path

import linker as linker
from assembler import assemble
from errors import AsmError, AsmErrors
from objfile import ObjectFile

# compiler/src/asm/__main__.py -> compiler/ROM
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "ROM"


def output_path(given, first_input, suffix):
    """Where to write: -o as written if it names a folder, a bare -o name
    inside OUTPUT_DIR, otherwise OUTPUT_DIR/<first input's name><suffix>.
    Creates the folder (git doesn't keep an empty one)."""
    if given and ("/" in given or "\\" in given):
        out = Path(given)
    elif given:
        out = OUTPUT_DIR / given
    else:
        out = OUTPUT_DIR / (Path(first_input).stem + suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def assemble_file(path):
    """Assemble one .asm file, printing its warnings. Raises AsmErrors."""
    text = Path(path).read_text(encoding="utf-8-sig")
    obj, warnings = assemble(text, str(path))
    for w in warnings:
        print(w.as_warning(), file=sys.stderr)
    return obj


def run_assemble(args):
    obj = assemble_file(args.source)
    out = output_path(args.output, args.source, ".obj")
    obj.save(out)
    print(f"{out}: {len(obj.rom)} words of ROM, {obj.ram_size} words of RAM")


def load_object(path, command):
    """Read an .obj file. Raises AsmError, with a hint when 'link' got a
    file that isn't an .obj."""
    try:
        return ObjectFile.load(path)
    except OSError as e:
        raise AsmError(f"can't read the file ({e.strerror})", str(path)) from None
    except AsmError as e:
        if command == "link" and not path.lower().endswith(".obj"):
            e.message += " (to use .asm files, run 'build' instead of 'link')"
        raise


def run_link(args):
    objects, problems = [], []
    for path in args.inputs:                  # keep going to report every file
        try:
            if args.command == "link" or path.lower().endswith(".obj"):
                objects.append(load_object(path, args.command))
            else:
                objects.append(assemble_file(path))
        except AsmErrors as e:
            problems.extend(e.errors)
        except AsmError as e:
            problems.append(e)
        except (OSError, UnicodeDecodeError) as e:
            problems.append(AsmError(f"can't read the file ({e})", str(path)))
    if problems:
        raise AsmErrors(problems)

    program = linker.link(objects)
    out = output_path(args.output, args.inputs[0], ".rom")
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
    p.add_argument("-o", "--output", help="output file (default: compiler/ROM/<source>.obj)")

    for name, help_text in (
            ("link", "join .obj files into a ROM image"),
            ("build", "assemble and link in one step (.asm and .obj files)")):
        p = commands.add_parser(name, help=help_text)
        p.add_argument("inputs", nargs="+")
        p.add_argument("-o", "--output", help="output file (default: compiler/ROM/<first input>.rom)")
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
