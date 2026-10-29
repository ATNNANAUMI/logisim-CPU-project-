"""The build pipeline: C files -> assembly -> object files -> a ROM image.

    compile_c()   one .c file -> assembly text
    build()       .c / .asm / .obj files + the C library -> a linked Program

The C library (compiler/libc/: .c and .asm files, headers in include/) is
compiled once and cached in compiler/ROM/libc/. Like a static library, only
the files that define something the program needs are linked in, so a
program can define its own function with a library name; and of those files
only the functions and data the program needs (the linker's library mode).

The start-up code (crt0) is generated for each build: it calls every linked
file's _init_ routine (which puts global variables in their starting state),
then main(0, {NULL}), then exit() with main's result. It also holds _Exit
(the CPU stops) and _heap_end (where malloc's heap ends).

A program for the OS (build(..., exe=True)) is linked for RAM at
linker.PROGRAM_BASE and saved as a TEX1 executable (exe_bytes(); the format
is in compiler/libc/spawn.c), which spawnv() loads. Its crt0 takes argc,
argv and the current directory from the block spawnv() passes in R1, and
its _Exit goes back to spawnv() instead of stopping the CPU.
"""

import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent             # compiler/src/cc
ROOT = HERE.parent.parent.parent                    # the project root
ASM_DIR = HERE.parent / "asm"
SIM_DIR = ROOT / "cpu_sim" / "src"
LIBC_DIR = ROOT / "compiler" / "libc"
INCLUDE_DIR = LIBC_DIR / "include"
OUTPUT_DIR = ROOT / "compiler" / "ROM"
CACHE_DIR = OUTPUT_DIR / "libc"

if str(ASM_DIR) not in sys.path:
    sys.path.append(str(ASM_DIR))

import linker                     # noqa: E402  (compiler/src/asm)
from assembler import assemble   # noqa: E402
from errors import AsmError, AsmErrors   # noqa: E402
from objfile import ObjectFile   # noqa: E402

from cerror import CError, CErrors   # noqa: E402
from codegen import generate         # noqa: E402
from cparser import parse            # noqa: E402
from preprocessor import Preprocessor   # noqa: E402

# names crt0 needs from the program and the library
CRT0_NEEDS = ("main", "exit")
EXE_MAGIC = 0x31584554             # "TEX1"; the format is in compiler/libc/spawn.c


class BuildError(Exception):
    """Errors from any stage, already formatted one per line."""

    def __init__(self, messages):
        super().__init__("\n".join(messages))
        self.messages = list(messages)


def unit_name(path, taken=None):
    """A label-safe name for a C file's init routine and template."""
    stem = re.sub(r"\W", "_", Path(path).stem) or "unit"
    if stem[0].isdigit():
        stem = "_" + stem
    name = stem
    n = 2
    while taken is not None and name in taken:
        name = f"{stem}_{n}"
        n += 1
    if taken is not None:
        taken.add(name)
    return name


def compile_c(path, include_dirs=(), defines=(), unit=None, warn=None):
    """Compile one C file to assembly text. Raises CError."""
    pp = Preprocessor(list(include_dirs) + [str(INCLUDE_DIR)], defines, warn=_pp_warn(warn))
    tokens = pp.run_file(str(path))
    program = parse(tokens, warn=warn)
    source = {}
    for f in pp.files:
        try:
            source[f] = Path(f).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            pass
    return generate(program, unit or unit_name(path), source, unit_file=str(path))


def _pp_warn(warn):
    if warn is None:
        return None
    from cerror import error_at

    def report(tok, message):
        warn(error_at(tok, message))
    return report


def print_warning(err):
    print(err.as_warning(), file=sys.stderr)


# ------------------------------------------------------------------ the library

def _compiler_stamp():
    """A hash of the compiler itself, so a changed compiler rebuilds the library."""
    h = hashlib.sha256()
    for p in sorted(HERE.glob("*.py")) + sorted(ASM_DIR.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    for p in sorted(INCLUDE_DIR.rglob("*.h")):         # sys/*.h too
        h.update(str(p.relative_to(INCLUDE_DIR)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def library_sources():
    if not LIBC_DIR.is_dir():
        return []
    return sorted(LIBC_DIR.glob("*.c")) + sorted(LIBC_DIR.glob("*.asm"))


def library_objects(warn=None):
    """Every library file as an ObjectFile, compiled or taken from the cache."""
    stamp = None
    objects = []
    errors = []
    for src in library_sources():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        obj_path = CACHE_DIR / (src.name.replace(".", "_") + ".obj")
        key_path = obj_path.with_suffix(".key")
        if stamp is None:
            stamp = _compiler_stamp()
        key = hashlib.sha256((stamp + src.read_text(encoding="utf-8")).encode()).hexdigest()
        if obj_path.exists() and key_path.exists() and key_path.read_text() == key:
            try:
                objects.append(ObjectFile.load(str(obj_path)))
                continue
            except AsmError:
                pass
        try:
            if src.suffix == ".c":
                text = compile_c(src, unit="libc_" + unit_name(src), warn=warn)
                (CACHE_DIR / (src.stem + ".asm")).write_text(text, encoding="utf-8")
                obj, _ = assemble(text, str(CACHE_DIR / (src.stem + ".asm")))
            else:
                obj, _ = assemble(src.read_text(encoding="utf-8"), str(src))
        except CError as e:
            errors.append(f"(C library) {e}")
            continue
        except AsmErrors as e:
            errors.extend(f"(C library) {x}" for x in e.errors)
            continue
        obj.save(str(obj_path))
        key_path.write_text(key)
        objects.append(obj)
    if errors:
        raise BuildError(errors)
    return objects


def select_library(program_objects, library, needs=CRT0_NEEDS):
    """The library objects that define what the program still needs,
    and what they in turn need (like a linker reading a static library)."""
    defined = set()
    wanted = set(needs)
    for obj in program_objects:
        defined.update(obj.globals)
        wanted.update(obj.externs)
    chosen = []
    providers = {}
    for obj in library:
        for name in obj.globals:
            providers.setdefault(name, obj)
    changed = True
    while changed:
        changed = False
        for name in sorted(wanted - defined):
            obj = providers.get(name)
            if obj is None or obj in chosen:
                continue
            chosen.append(obj)
            defined.update(obj.globals)
            wanted.update(obj.externs)
            changed = True
    return chosen


# linked last: _end is the first RAM word after every variable (malloc's heap)
END_SOURCE = """; the end of the program's RAM (generated by the C compiler)
        .global _end
        .ram
_end:   .space 0
"""


def crt0_source(objects, exe=False, heap_end=linker.RAM_END):
    """The start-up code: init routines, main, exit; _Exit and _heap_end.
    exe: for a program spawnv() runs (R1 = its block: argc, argv, the
    address to go back to, the current directory, a put function for stdout)."""
    globals_ = {name for obj in objects for name in obj.globals}
    inits = [name for obj in objects for name in obj.globals if name.startswith("_init_")]
    inherit = exe and "_fs_inherit" in globals_
    redirect = exe and "_set_stdout" in globals_
    lines = [
        "; crt0: start-up code for a C program (generated by the C compiler)",
        "        .global start, _Exit, _heap_end",
        "        .extern " + ", ".join(list(CRT0_NEEDS) + inits
                                      + (["_fs_inherit"] if inherit else [])
                                      + (["_set_stdout"] if redirect else [])),
        "",
        "start:",
    ]
    if exe:
        lines += [
            "        DATA R0, _crt0_block",
            "        ST R0, R1                   ; the block from spawnv()",
        ]
    lines += [f"        CALL {name}" for name in inits]
    if inherit:
        lines += [
            "        DATA R1, _crt0_block",
            "        LD R1, R2",
            "        DATA R1, 3",
            "        ALD R2, R1",
            "        STK PUSH",
            "        CALL _fs_inherit, 1         ; the caller's current directory",
        ]
    if redirect:
        lines += [
            "        DATA R1, _crt0_block",
            "        LD R1, R2",
            "        DATA R1, 4",
            "        ALD R2, R1",
            "        STK PUSH",
            "        CALL _set_stdout, 1         ; the caller's file for stdout, or 0",
        ]
    if exe:
        lines += [
            "        DATA R1, _crt0_block",
            "        LD R1, R2",
            "        DATA R1, 0",
            "        ALD R2, R1                  ; argc",
            "        STK PUSH",
            "        DATA R1, 1",
            "        ALD R2, R1                  ; argv",
            "        STK PUSH",
        ]
    else:
        lines += [
            "        DATA R0, 0                  ; argc",
            "        STK PUSH",
            "        DATA R0, _crt0_argv         ; argv: { NULL }",
            "        STK PUSH",
        ]
    lines += [
        "        CALL main, 2",
        "        STK PUSH                    ; exit(main's result)",
        "        CALL exit, 1",
        "_Exit:                              ; _Exit(status): R0 = status",
        "        DATA R1, -2",
        "        STK GET, R1",
    ]
    if exe:
        lines += [
            "        CPY R0, R3",
            "        DATA R1, _crt0_block",
            "        LD R1, R2",
            "        DATA R1, 2",
            "        ALD R2, R1",
            "        CPY R0, R2",
            "        CPY R3, R0",
            "        JMRB R2                     ; back to spawnv()",
            "_crt0_block:",
            "        .word 0",
        ]
    else:
        lines += [
            "_crt0_halt:",
            "        HALT",
            "        RJMP _crt0_halt",
            "_crt0_argv:",
            "        .word 0",
        ]
    lines += [
        "_heap_end:",
        f"        .word 0x{heap_end:x}",
    ]
    return "\n".join(lines) + "\n"


def exe_bytes(program):
    """A program linked with a base, as a TEX1 executable: little-endian
    words, as `python compiler/src/disk put` stores a binary file."""
    header = [EXE_MAGIC, program.base, len(program.rom), program.base, program.ram_used]
    return b"".join((w & 0xFFFFFFFF).to_bytes(4, "little") for w in header + program.rom)


# ------------------------------------------------------------------ building

def output_path(given, first_input, suffix):
    """Same rule as the assembler: a bare -o name goes in compiler/ROM/,
    a path with a folder is used as written."""
    if given and ("/" in given or "\\" in given):
        out = Path(given)
    elif given:
        out = OUTPUT_DIR / given
    else:
        out = OUTPUT_DIR / (Path(first_input).stem + suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def build(inputs, include_dirs=(), defines=(), asm_dir=None, use_libc=True, warn=None,
          libs=(), exe=False):
    """Compile, assemble and link. Returns (Program, list of object files).

    asm_dir: where to write the .asm made from each .c (None: don't write).
    libs: more files (.asm, .obj) linked as libraries: only what is used.
    exe: a program for the OS (spawnv() runs it), linked at PROGRAM_BASE."""
    taken = set()
    objects = []
    errors = []
    for path in list(inputs) + list(libs):
        path = str(path)
        try:
            if path.endswith(".c"):
                text = compile_c(path, include_dirs, defines, unit_name(path, taken), warn=warn)
                asm_name = str(Path(asm_dir) / (Path(path).stem + ".asm")) if asm_dir else path
                if asm_dir:
                    Path(asm_name).write_text(text, encoding="utf-8")
                obj, _ = assemble(text, asm_name)
            elif path.endswith(".obj"):
                obj = ObjectFile.load(path)
            else:
                text = Path(path).read_text(encoding="utf-8-sig")
                obj, warnings = assemble(text, path)
                for w in warnings:
                    if warn:
                        warn(w)
            objects.append(obj)
        except CError as e:
            errors.append(str(e))
        except CErrors as e:
            errors.extend(str(x) for x in e.errors)
        except AsmErrors as e:
            errors.extend(str(x) for x in e.errors)
        except AsmError as e:
            errors.append(str(e))
        except OSError as e:
            errors.append(f"{path}: can't read the file ({e.strerror})")
    if errors:
        raise BuildError(errors)

    user_libs = objects[len(inputs):]
    spawns = False
    objects = objects[:len(inputs)]
    if use_libc:
        library = library_objects(warn)
        chosen = select_library(objects + user_libs, library)
        spawns = any("spawnv" in obj.globals for obj in chosen)
        if exe and spawns:
            raise BuildError(["a program built with --exe can't call spawnv(): "
                              "it would load the other program over itself"])
        heap_end = linker.PROGRAM_BASE if spawns else linker.RAM_END
        crt0, _ = assemble(crt0_source(objects + user_libs + chosen, exe, heap_end), "<crt0>")
        end, _ = assemble(END_SOURCE, "<end>")
        all_objects = [crt0] + objects + user_libs + chosen + [end]
    else:
        chosen = []
        all_objects = objects + user_libs
    try:
        program = linker.link(all_objects, user_libs + chosen,
                              base=linker.PROGRAM_BASE if exe else None)
    except AsmErrors as e:
        raise BuildError([str(x) for x in e.errors]) from None
    if use_libc and spawns and linker.RAM_DATA_START + program.ram_used > linker.PROGRAM_BASE:
        raise BuildError([f"the program's RAM data ({program.ram_used} words) runs into the "
                          f"area spawnv() loads programs in (0x{linker.PROGRAM_BASE:x})"])
    return program, all_objects


def format_rom(program):
    return linker.format_raw(program.rom)


def format_map(program, title):
    return linker.format_map(program, title)


# ------------------------------------------------------------------ running

def run_in_simulator(rom_words, keys="", max_steps=50_000_000, trace=False, disk=None):
    """Run a ROM image in the Python simulator. Returns (cpu, display text).
    disk: a disk image file for devices 0x8C/0x8D, created if missing."""
    if str(SIM_DIR) not in sys.path:
        sys.path.append(str(SIM_DIR))
    from cpu import CPU                      # cpu_sim/src

    cpu = CPU()
    cpu.mem.load_rom(rom_words)
    if keys:
        cpu.bus.keyboard.type(keys)
    if disk:
        cpu.bus.attach_disk(disk)
    if trace:
        steps = 0
        while steps < max_steps:
            st = cpu.step()
            if st is None:
                break
            operand = "" if st.operand is None else f" 0x{st.operand:08X}"
            print(f"0x{st.address:07X}  {st.word:08X}{operand:11s} {st.text:<20s} {st.note}")
            steps += 1
    else:
        cpu.run(max_steps)
    cpu.bus.attach_disk(None)
    return cpu, cpu.bus.display.text
