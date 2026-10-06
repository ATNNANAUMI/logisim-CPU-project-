"""Checks for the assembler and linker. Run from the project root:

    python compiler/src/asm/selftest.py
"""

import contextlib
import importlib.util
import io
import tempfile
import traceback
from pathlib import Path
from typing import Any

import linker as linker
from assembler import assemble
from errors import AsmErrors
from objfile import ObjectFile

# The command line lives in __main__.py, which can't be imported by that name
# while this file is the one running, so load it under another name.
_spec = importlib.util.spec_from_file_location(
    "asm_cli", Path(__file__).with_name("__main__.py"))
assert _spec is not None and _spec.loader is not None
cli: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def words_of(text):
    """Assemble one snippet and return its ROM words (no linking)."""
    obj, _ = assemble(text, "test.asm")
    return obj.rom


def build(*texts):
    """Assemble and link snippets named f0.asm, f1.asm, ... Returns the Program."""
    objects = [assemble(t, f"f{i}.asm")[0] for i, t in enumerate(texts)]
    return linker.link(objects)


def expect_error(text, fragment, line=None):
    """Assembling text must fail with a message containing fragment."""
    try:
        assemble(text, "test.asm")
    except AsmErrors as e:
        for err in e.errors:
            if fragment in err.message and (line is None or err.line == line):
                return
        raise AssertionError(f"wrong error for {text!r}: {e}")
    raise AssertionError(f"no error for {text!r}")


def expect_link_error(texts, fragment):
    try:
        build(*texts)
    except AsmErrors as e:
        if any(fragment in err.message for err in e.errors):
            return
        raise AssertionError(f"wrong link error: {e}")
    raise AssertionError("no link error")


def parse_raw(text):
    lines = text.splitlines()
    assert lines[0] == "v2.0 raw"
    words = []
    for item in " ".join(lines[1:]).split():
        if "*" in item:
            count, value = item.split("*")
            words += [int(value, 16)] * int(count)
        else:
            words.append(int(item, 16))
    return words


# ---------------------------------------------------------------- checks

def check_isa_doc_words():
    """The encodings quoted in the ISA document."""
    assert words_of("ADD R1, R2") == [0x1012]
    assert words_of("TEST R1") == [0x1E01]
    assert words_of("HALT") == [0x0F00]


def check_abs_value_example():
    """The ISA document's worked example, written with a label."""
    src = """
            DATA R1, -5
            TEST R1
            RJNF N, positive
            NEG R1
            CPY R0, R1
    positive:
            DATA R0, 0x5C
            COMM OUTADDR, R0
            COMM OUTDATA, R1
            HALT
    """
    assert words_of(src) == [0x0301, 0xFFFFFFFB, 0x1E01, 0x0602, 0x0003, 0x1D01,
                             0x0E01, 0x0300, 0x005C, 0x0830, 0x0821, 0x0F00]


def check_every_system_instruction():
    src = """
        NOP
        LD R1, R2
        ST R3, R4
        CLF
        ADDR R5
        JMRB R6
        ALD R7, R8
        AST R9, R10
        CPY R11, R12
        COMM INDATA, R1
        COMM INADDR R2
        COMM OUTDATA, R3
        COMM OUTADDR,R4
        STK PUSH
        STK POP
        STK CALL
        STK RET
        STK SET, R1
        STK GET R2
        HALT
    """
    assert words_of(src) == [0x0000, 0x0112, 0x0234, 0x0700, 0x0905, 0x0A06,
                             0x0C78, 0x0D9A, 0x0EBC, 0x0801, 0x0812, 0x0823,
                             0x0834, 0x0B00, 0x0B10, 0x0B20, 0x0B30, 0x0B41,
                             0x0B52, 0x0F00]


def check_alu_and_immediates():
    src = """
        SUB R1, R2
        MOD R3, R4
        SHL R5
        ++ R6
        INC R6
        -- R7
        DEC R7
        NOT R8
        ADD R1, #5
        CMP R1, #'z' + 1
        FADD R2, #1.5
        FLOAT R3
        INT R4
        FNEG R5
        FCMP R1, R2
    """
    assert words_of(src) == [0x1112, 0x1A34, 0x1405, 0x1B06, 0x1B06, 0x1C07,
                             0x1C07, 0x1608, 0x5010, 5, 0x5F10, 0x7B,
                             0x7020, 0x3FC00000, 0x3603, 0x3704, 0x3D05, 0x3F12]


def check_values():
    src = """
        .equ SIZE, 3
        .equ BIG, SIZE * 1
    """
    expect_error(src, "can't read")        # no * in expressions
    src = r"""
        .equ SIZE, 3
        .word 0x2A, 0b101, 42, -1, 'a', '\n', '\'', ',', SIZE + 1, 10 - -2, 1.5, -0.25
    """
    assert words_of(src) == [0x2A, 5, 42, 0xFFFFFFFF, 0x61, 0x0A, 0x27, 0x2C, 4,
                             12, 0x3FC00000, 0xBE800000]


def check_strings_and_space():
    src = r"""
        .string "hi\n"
        .string "a;b, c"      ; comment after a string with ; and ,
        .space 2
        .string ""
    """
    assert words_of(src) == [0x68, 0x69, 0x0A, 0, 0x61, 0x3B, 0x62, 0x2C, 0x20,
                             0x63, 0, 0, 0, 0]


def check_jumps_and_flags():
    src = """
    top:    NOP
            RJMP top
            RJF NZ, end
            RJNF CANZ, top
    end:    HALT
    """
    # Offsets count from the offset word:
    # RJMP's is at 2: 0 - 2 = -2.  RJF's at 4: 7 - 4 = 3.  RJNF's at 6: 0 - 6 = -6.
    assert words_of(src) == [0x0000, 0x0400, 0xFFFFFFFE, 0x0503, 3, 0x060F,
                             0xFFFFFFFA, 0x0F00]


def check_call_and_ret():
    obj, _ = assemble("""
    f:      RET
    main:   CALL f
            HALT
    """, "t.asm")
    assert obj.rom[:6] == [0x0E0F, 0x0B30, 0x0B10, 0x0E0E, 0x0EF0, 0x0A0E]
    assert obj.rom[6:13] == [0x0300, 0, 0x0B00, 0x0B20, 0x0300, 0, 0x0A00]
    return_reloc, target_reloc = obj.relocs
    assert (return_reloc.at, return_reloc.section, return_reloc.addend) == (7, "rom", 13)
    assert (target_reloc.at, target_reloc.section, target_reloc.addend) == (11, "rom", 0)


def check_save_restore_and_call_cleanup():
    obj, _ = assemble("""
    f:      RET
            SAVE R2, R5
            CALL f, 2
            RESTORE R2, R5
            RESTORE R0, R3
            CALL f, 0
    """, "t.asm")
    rom = obj.rom[6:]
    assert rom[0:4] == [0x0E20, 0x0B00, 0x0E50, 0x0B00]              # SAVE
    assert rom[4:11] == [0x0300, 0, 0x0B00, 0x0B20, 0x0300, 0, 0x0A00]
    assert rom[11:15] == [0x0E0F, 0x0B10, 0x0B10, 0x0EF0]            # drop 2 args
    assert rom[15:21] == [0x0E0F, 0x0B10, 0x0E05, 0x0B10, 0x0E02, 0x0EF0]
    assert rom[21:25] == [0x0B10, 0x0E03, 0x0B10, 0x0E00]            # R0 listed
    assert len(rom[25:]) == 7                                        # CALL f, 0
    # the return address still points just after JMRB, before the cleanup
    ret = [r for r in obj.relocs if r.at == 6 + 5][0]
    assert (ret.section, ret.addend) == ("rom", 6 + 11)


def check_linking():
    main = """
            .extern helper, table
            .global start
            .ram
    var:    .space 2
            .rom
    start:  DATA R1, var + 1
            CALL helper
            RJMP helper
            DATA R2, table
    """
    lib = """
            .global helper, table
            .ram
    table:  .space 3
            .rom
    helper: RET
    """
    rom = build(main, lib).rom
    # ROM: entry jump 0-1, main 2-14, lib from 15 (helper = 15).
    # RAM: var 0x14000-0x14001, table 0x14002.
    assert rom[0:2] == [0x0400, 1]                    # RJMP start: 2 - 1
    assert rom[2:4] == [0x0301, 0x14001]              # DATA R1, var + 1
    assert rom[5] == 11                               # CALL's return address
    assert rom[9] == 15                               # CALL's target: helper
    assert rom[12] == 15 - 12                         # RJMP helper, from its offset word at 12
    assert rom[13:15] == [0x0302, 0x14002]            # DATA R2, table


def check_entry_when_start_is_not_first():
    lib = "        .global f\nf:      RET\n"
    main = "        .global start\n        .extern f\nstart:  CALL f\n"
    rom = build(lib, main).rom
    assert rom[0:2] == [0x0400, 7]                    # start = 2 + 6 = 8, 8 - 1


def check_errors():
    expect_error("        ADD R1, R16", "not a register", 1)
    expect_error("        FOO R1", "unknown instruction")
    expect_error("        DATA R1, #5", "without '#'")
    expect_error("        RJMP 5", "must be a label")
    expect_error("        RJF Q, x\nx:", "flag list")
    expect_error("        SHL #3", "not an immediate")
    expect_error("        ADD R1", "expected ADD RA, RB")
    expect_error("x: NOP\nx: NOP", "already defined on line 1", 2)
    expect_error("        DATA R1, missing", "unknown name 'missing'")
    expect_error("        .ram\n        HALT", "can't go in RAM")
    expect_error("        .ram\n        .word 1", "RAM holds no starting values")
    expect_error("        .ram\nb: .space 1\n        .rom\n        RJMP b", "RAM label")
    expect_error("        DATA R1, 'ab'", "exactly one character")
    expect_error('        .string "abc', "missing closing quote")
    expect_error("        STK PUSH R1", "takes no register")
    expect_error("        STK GET", "expected STK GET, RB")
    expect_error("        DATA R1, 0x1FFFFFFFF", "doesn't fit in 32 bits")
    expect_error("b: NOP\n        DATA R1, 5 - b", "only be added")
    expect_error("a: NOP\nb: NOP\n        DATA R1, a + b", "only one label")
    expect_error("add: NOP", "is an instruction")
    expect_error("        .equ R3, 4", "is a register")
    expect_error("        .global nothere", "never defined")
    expect_error("        .extern x\nx: NOP", "also defined here")
    expect_error("        .equ X, later\nlater: NOP", "defined above")
    expect_error("        .bogus", "unknown directive")
    expect_error("        DATA R1, 1.5 + 1", "float can't be added")
    expect_error("        SAVE", "expected SAVE register")
    expect_error("        RESTORE R1, R1", "listed twice")
    expect_error("        SAVE R1, 5", "not a register")
    expect_error("f: RET\n        CALL f, -1", "0 or more")
    expect_error("f: RET\n        CALL f, f", "is a label")
    expect_error("f: RET\n        CALL f, 1, 2", "expected CALL label")


def check_warnings():
    _, warnings = assemble("        CMP R1, #1.5\n        FCMP R1, #3\n"
                           "        FADD R1, #0\n        FADD R1, #2.0", "w.asm")
    assert [w.line for w in warnings] == [1, 2], warnings


def check_link_errors():
    expect_link_error(["x: NOP"], "nowhere to begin")
    expect_link_error(["        .global start\nstart: NOP", "        .global start\nstart: NOP"],
                      ".global in both")
    expect_link_error(["        .global start\n        .extern f\nstart:  CALL f"],
                      "isn't .global in any")
    expect_link_error(["        .global start\n        .extern b\nstart:  RJMP b",
                       "        .global b\n        .ram\nb: .space 1"], "RAM label")
    # a CALL to another file's RAM label
    expect_link_error(["        .global start\n        .extern buf\nstart:  CALL buf",
                       "        .global buf\n        .ram\nbuf: .space 1"],
                      "can't call 'buf'")
    # an .extern nobody exports, even when it is never used
    expect_link_error(["        .global start\n        .extern ghost\nstart:  HALT"],
                      "listed in .extern")
    # ...but taking a RAM label's address from another file is fine
    build("        .global start\n        .extern buf\nstart:  DATA R1, buf",
          "        .global buf\n        .ram\nbuf: .space 1")


def check_raw_output():
    words = [1, 2, 0, 0, 0, 0, 0, 7, 0xFFFFFFFF] + [0] * 20
    text = linker.format_raw(words)
    assert text.startswith("v2.0 raw\n")
    assert "5*0" in text and "20*0" in text
    assert parse_raw(text) == words


def check_object_file_round_trip():
    obj, _ = assemble("""
            .global start
            .extern f
            .ram
    v:      .space 2
            .rom
    start:  CALL f
            DATA R1, v
            .string "ok"
    """, "t.asm")
    again = ObjectFile.from_json(obj.to_json())
    assert again == obj
    assert [r.rom_only for r in obj.relocs] == [False, True, False]   # CALL's target only


def check_command_line():
    """build and assemble + link through the real command line, in a temp folder."""
    with tempfile.TemporaryDirectory() as tmp, \
            contextlib.redirect_stdout(io.StringIO()):
        tmp = Path(tmp)
        (tmp / "main.asm").write_text("        .global start\n        .extern f\n"
                                      "start:  CALL f\n        HALT\n")
        (tmp / "lib.asm").write_text("        .global f\nf:      RET\n")
        out = tmp / "prog.rom"
        assert cli.main(["build", str(tmp / "main.asm"), str(tmp / "lib.asm"),
                         "-o", str(out), "--map"]) == 0
        built = parse_raw(out.read_text())
        assert (tmp / "prog.map").exists()
        assert cli.main(["assemble", str(tmp / "main.asm"), "-o", str(tmp / "main.obj")]) == 0
        assert cli.main(["assemble", str(tmp / "lib.asm"), "-o", str(tmp / "lib.obj")]) == 0
        assert cli.main(["link", str(tmp / "main.obj"), str(tmp / "lib.obj"),
                         "-o", str(tmp / "linked.rom")]) == 0
        assert parse_raw((tmp / "linked.rom").read_text()) == built
        # build reports a bad .asm AND a bad .obj, not just the first one
        (tmp / "bad.asm").write_text("        FOO R1\n")
        (tmp / "bad.obj").write_text("not json")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert cli.main(["build", str(tmp / "bad.asm"), str(tmp / "bad.obj")]) == 1
        text = err.getvalue()
        assert "unknown instruction" in text and "not an object file" in text, text
        assert "instead of 'link'" not in text, text
        # output-path rule, with OUTPUT_DIR pointed at the temp folder
        saved = cli.OUTPUT_DIR
        cli.OUTPUT_DIR = tmp / "ROM"
        try:
            ROM = tmp / "ROM"
            assert cli.output_path(None, "x/y/prog.asm", ".rom") == ROM / "prog.rom"
            assert cli.output_path(None, "prog.asm", ".obj") == ROM / "prog.obj"
            assert cli.output_path("demo.rom", "prog.asm", ".rom") == ROM / "demo.rom"
            assert cli.output_path(str(tmp / "out/demo.rom"), "prog.asm", ".rom") == tmp / "out/demo.rom"
            assert cli.output_path("./demo.rom", "prog.asm", ".rom") == Path("./demo.rom")
            assert ROM.is_dir()                       # created when missing
            assert cli.main(["build", str(tmp / "main.asm"), str(tmp / "lib.asm"), "--map"]) == 0
            assert (ROM / "main.rom").exists() and (ROM / "main.map").exists()
            assert parse_raw((ROM / "main.rom").read_text()) == built
            assert not (tmp / "main.rom").exists()    # not next to the source any more
        finally:
            cli.OUTPUT_DIR = saved


def check_examples_build():
    """Every example under compiler/examples/ assembles and links.

    two_files/ is linked as its pair; every other .asm is linked together with
    stdlib/stdlib.asm, which works whether or not it uses the library.
    """
    root = Path(__file__).resolve().parent.parent.parent / "examples"   # compiler/examples
    if not root.is_dir():
        return "skipped, no examples folder"

    def obj(path):
        return assemble(path.read_text(encoding="utf-8-sig"), str(path))[0]

    built = []
    pair = root / "two_files"
    if (pair / "main.asm").is_file() and (pair / "lib.asm").is_file():
        linker.link([obj(pair / "main.asm"), obj(pair / "lib.asm")])
        built.append("two_files")
    stdlib_path = root / "stdlib" / "stdlib.asm"
    stdlib = [obj(stdlib_path)] if stdlib_path.is_file() else []
    for path in sorted(root.rglob("*.asm")):
        if path == stdlib_path or pair in path.parents:
            continue
        try:
            linker.link([obj(path)] + stdlib)
        except AsmErrors as e:
            raise AssertionError(f"{path.relative_to(root)} doesn't build:\n{e}") from None
        built.append(str(path.relative_to(root)))
    return f"{len(built)} built"


CHECKS = [
    check_isa_doc_words,
    check_abs_value_example,
    check_every_system_instruction,
    check_alu_and_immediates,
    check_values,
    check_strings_and_space,
    check_jumps_and_flags,
    check_call_and_ret,
    check_save_restore_and_call_cleanup,
    check_linking,
    check_entry_when_start_is_not_first,
    check_errors,
    check_warnings,
    check_link_errors,
    check_raw_output,
    check_object_file_round_trip,
    check_command_line,
    check_examples_build,
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
