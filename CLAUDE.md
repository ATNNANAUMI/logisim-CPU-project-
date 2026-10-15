# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A 32-bit CPU built from logic gates in Logisim-evolution 4.1.0 (`logisim/CPU.circ`), plus its toolchain in Python 3.10+ (standard library only; `tkinter` for the simulator window): an assembler/linker, an assembly standard library, a C compiler ("tiny C") with its own C library, and a simulator that runs the same ROM images as the circuit.

`STRUCTURE.md` is a compact project map written for AI assistants (directory tree, circuit hierarchy, ISA cheat sheet, assembler and C conventions, gotchas). Read it first. `TECHNICAL.md` is the full reference; `compiler/assembly_syntax.md` is the current assembly language reference (the copy in `compiler/src/asm/` is outdated); `compiler/c_language.md` is the C reference and `compiler/c_decisions.md` records why the C compiler is built the way it is, and what is still a guess.

## Commands

```
python run.py test                                   # three self-check suites (assembler 19, simulator 18, C compiler 14), then check_docs.py
python compiler/src/asm/selftest.py                  # assembler only
python cpu_sim/src/selftest.py                       # simulator only
python compiler/src/cc/selftest.py                   # C compiler only (~40 s: runs every test program)
python compiler/src/cc/tests/difftest.py [names] [--update]   # C test programs against gcc (--update rewrites .expected)
python compiler/src/cc/tests/fuzz.py [--count N] [--seed S]   # random C programs, gcc against tiny C

# a single check (assembler and C compiler checks are check_*, simulator ones are test_*)
python -c "import sys; sys.path.insert(0,'compiler/src/asm'); import selftest; selftest.check_linking()"
python -c "import sys; sys.path.insert(0,'cpu_sim/src'); import selftest; selftest.test_keyboard_input()"
python -c "import sys; sys.path.insert(0,'compiler/src/cc'); import selftest; selftest.check_errors()"

python compiler/src/asm build prog.asm compiler/examples/stdlib/stdlib.asm [-o name.rom] [--map]
python compiler/src/asm build prog.asm --lib compiler/examples/stdlib/stdlib.asm   # link only the stdlib functions used
python cpu_sim/src/main.py compiler/ROM/prog.rom                             # GUI
python cpu_sim/src/main.py compiler/ROM/prog.rom --headless --steps 2000000 [--trace] [--keys $'text\n'] [--screen out.png]
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/prog.rom [--seconds N]   # real circuit, headless

python compiler/src/cc run prog.c [--keys $'text\n'] [--stats]       # C: build + run in the simulator
python compiler/src/cc build prog.c [more.c x.asm] [-o name.rom] [--map] [--lib x.asm]   # C: links the C library itself
python compiler/src/cc compile prog.c [-o prog.asm]                   # C -> assembly only
```

`run_rom.py` finds the jar via `$LOGISIM_JAR` or the Arch package path. A circuit run stops at `HALT` (printing `--- halted at HALT ---`) because Logisim's headless mode watches the output pin labelled `halt` in the top-level `PC` circuit; keep that pin and its label if the circuit is reworked. The `circuit-check` skill (`.claude/skills/`) covers comparing the simulator with the circuit.

There is no linter or build step. Assembler output goes to `compiler/ROM/` (git-ignored); an `-o` containing a directory component is used as given.

## Architecture

Pipeline: `.asm` → two-pass assembler (`assembler.py`, with pseudo-op expansion and relocations) → `.obj` (JSON, `objfile.py`) → `linker.py` → `.rom` in Logisim "v2.0 raw" format → either the Python simulator or the real circuit (`run_rom.py` patches the image into the ROM component inside the `RAM` subcircuit and runs Logisim headless).

The ISA is encoded in two independent places that must stay in sync: `compiler/src/asm/encoding.py` (assembler) and `cpu_sim/src/isa.py` (simulator decode/disassemble). An ISA change also touches `alu.py`/`cpu.py`, the docs, and possibly `stdlib.asm`.

C: `compiler/src/cc/` (preprocessor → parser/type checker → `codegen.py` + `regalloc.py` + `peephole.py`) writes assembly text, which `driver.py` feeds to `compiler/src/asm`'s assembler and links with a generated crt0 and the C library (`compiler/libc/`, compiled once and cached in `compiler/ROM/libc/`; only the files a program needs are linked). Every program in `compiler/src/cc/tests/` must print exactly what gcc's build prints (`.expected` files come from gcc); keep test programs free of undefined behaviour and of type sizes. `compiler/examples/c/circuit_test.c` checks the compiler's tricky code paths on the circuit.

`compiler/src/asm/`, `compiler/src/cc/` and `cpu_sim/src/` import their sibling modules by plain name, so run files as scripts (or put the directory on `sys.path`), not as packages. The assembler and the C compiler are invoked as directories (`python compiler/src/asm <cmd>`, `python compiler/src/cc <cmd>`, via `__main__.py`).

**The circuit is the ground truth.** The simulator was written from the ISA, not derived from the circuit. Behaviours not yet verified on the circuit are switches in `cpu_sim/src/config.py` (TWEAKS, each marked confirmed/guess). The circuit's `NOT` inverted RA until it was rewired to RB on 2026-10-15; the assembler still writes `NOT Rx` with x in both fields, which works either way (see TECHNICAL §8). Diagnostic programs used to measure circuit behaviour live in `compiler/examples/tests/`.

Key ISA facts that trip people up (details in STRUCTURE.md):
- Every ALU result goes to **R0**, and every ALU op rewrites all flags.
- Jumps are relative to the address of the offset word.
- The carry flag: `SUB` sets C on a *borrow* (`RA < RB` unsigned); `CMP`, `--`, `NEG`, `MULT` never set it (measured on the circuit).
- `STK CALL/RET` only move the stack frame; the `CALL`/`RET` pseudo-ops do the jump and clobber R0/R14/R15.
- The linker puts `RJMP start` at address 0. Exactly one file has `.global start`. Calling or jumping to a RAM label is a link error.
- In C, every scalar is one word (`sizeof(char) == 1`, `CHAR_BIT == 32`), `double` is the 32-bit float, and there is no `long long`.

## Keeping the docs in sync

Most facts are written in more than one doc. When you change one of these, update every place in its row (the first one is the full version), then run `python run.py test`; `check_docs.py` catches dead paths, unlisted examples and undocumented TWEAKS, but not wrong descriptions.

| when this changes | update |
| --- | --- |
| an instruction (encoding or behaviour) | `encoding.py` + `isa.py` + `alu.py`/`cpu.py`; TECHNICAL §1, `compiler/assembly_syntax.md` §4, STRUCTURE "ISA cheat sheet", README if it's the one-paragraph summary |
| assembler syntax, directives, pseudo-ops | `compiler/assembly_syntax.md`; TECHNICAL §4, STRUCTURE "Assembler conventions" |
| a command, flag or output path | TECHNICAL §3.3 / §4.1 / §7; README "Quick start", STRUCTURE "Common commands", `assembly_syntax.md` §10, this file's Commands |
| a stdlib function or the calling convention | the header of `stdlib.asm`; TECHNICAL §5.1–5.2, STRUCTURE "Assembler conventions" |
| an example program added, renamed or removed (`.asm` or `.c`) | its own header (build command, expected output); TECHNICAL §5.3, STRUCTURE tree |
| a TWEAKS switch, or a behaviour measured on the circuit | `config.py`; TECHNICAL §3.4 and §8, STRUCTURE "Open questions / gotchas", the diag file's header (see the `circuit-check` skill) |
| a subcircuit, pin or device in `CPU.circ` | TECHNICAL §2; STRUCTURE "Circuit hierarchy" |
| a self-check added or removed | TECHNICAL §7.3; the counts in STRUCTURE's tree and in this file |
| the C language or the C compiler's conventions | `compiler/c_language.md`; TECHNICAL §10, STRUCTURE "C compiler conventions", `compiler/c_decisions.md` when it is a design decision or a guess |
| a C library function or header | the header and its `compiler/libc/*.c`; `compiler/c_language.md` §7; TECHNICAL §10.5 for library structure |
| a C test program | `compiler/src/cc/tests/<name>.c`, then `difftest.py <name> --update` (needs gcc) to write its `.expected` |
| a file or folder added, moved or removed | STRUCTURE tree; README "Layout"; TECHNICAL §9 if it's outdated material |

## Outdated notes

`logisim/cpu datas/` holds old personal notes (stack micro-steps, a TODO list), not a description of the current design. The old hand-assembled programs (`cpu_sim/examples/`, `logisim/functions/`) were removed on 2026-10-06 and are only in git history. Unused subcircuits in `CPU.circ` are listed in `TECHNICAL.md` §9.
