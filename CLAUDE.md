# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A 32-bit CPU built from logic gates in Logisim-evolution 4.1.0 (`logisim/CPU.circ`), plus its toolchain in Python 3.10+ (standard library only; `tkinter` for the simulator window): an assembler/linker, an assembly standard library, and a simulator that runs the same ROM images as the circuit.

`STRUCTURE.md` is a compact project map written for AI assistants (directory tree, circuit hierarchy, ISA cheat sheet, assembler conventions, gotchas). Read it first. `TECHNICAL.md` is the full reference; `compiler/assembly_syntax.md` is the current assembly language reference (the copy in `compiler/src/asm/` is outdated).

## Commands

```
python run.py test                                   # both self-check suites (assembler 18, simulator 13), then check_docs.py
python compiler/src/asm/selftest.py                  # assembler only
python cpu_sim/src/selftest.py                       # simulator only

# a single check (assembler checks are check_*, simulator ones are test_*)
python -c "import sys; sys.path.insert(0,'compiler/src/asm'); import selftest; selftest.check_linking()"
python -c "import sys; sys.path.insert(0,'cpu_sim/src'); import selftest; selftest.test_keyboard_input()"

python compiler/src/asm build prog.asm compiler/examples/stdlib/stdlib.asm [-o name.rom] [--map]
python cpu_sim/src/main.py compiler/ROM/prog.rom                             # GUI
python cpu_sim/src/main.py compiler/ROM/prog.rom --headless --steps 2000000 [--trace] [--keys $'text\n']
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/prog.rom [--seconds N]   # real circuit, headless
```

`run_rom.py` finds the jar via `$LOGISIM_JAR` or the Arch package path. A circuit run stops at `HALT` (printing `--- halted at HALT ---`) because Logisim's headless mode watches the output pin labelled `halt` in the top-level `PC` circuit; keep that pin and its label if the circuit is reworked. The `circuit-check` skill (`.claude/skills/`) covers comparing the simulator with the circuit.

There is no linter or build step. Assembler output goes to `compiler/ROM/` (git-ignored); an `-o` containing a directory component is used as given.

## Architecture

Pipeline: `.asm` → two-pass assembler (`assembler.py`, with pseudo-op expansion and relocations) → `.obj` (JSON, `objfile.py`) → `linker.py` → `.rom` in Logisim "v2.0 raw" format → either the Python simulator or the real circuit (`run_rom.py` patches the image into the ROM component inside the `RAM` subcircuit and runs Logisim headless).

The ISA is encoded in two independent places that must stay in sync: `compiler/src/asm/encoding.py` (assembler) and `cpu_sim/src/isa.py` (simulator decode/disassemble). An ISA change also touches `alu.py`/`cpu.py`, the docs, and possibly `stdlib.asm`.

Both `compiler/src/asm/` and `cpu_sim/src/` import their sibling modules by plain name, so run files as scripts (or put the directory on `sys.path`), not as packages. The assembler is invoked as a directory (`python compiler/src/asm <cmd>` via `__main__.py`).

**The circuit is the ground truth.** The simulator was written from the ISA, not derived from the circuit. Behaviours not yet verified on the circuit are switches in `cpu_sim/src/config.py` (TWEAKS, each marked confirmed/guess). Known mismatch: a negative `STK SET/GET` index at `EBP = 0` wraps at 14 bits in the simulator (`0x13FFF`) but across all of RAM on the circuit (`0x1FFFF`). Diagnostic programs used to measure circuit behaviour live in `compiler/examples/tests/`.

Key ISA facts that trip people up (details in STRUCTURE.md):
- Every ALU result goes to **R0**, and every ALU op rewrites all flags.
- Jumps are relative to the address of the offset word.
- `STK CALL/RET` only move the stack frame; the `CALL`/`RET` pseudo-ops do the jump and clobber R0/R14/R15.
- The linker puts `RJMP start` at address 0. Exactly one file has `.global start`. Calling or jumping to a RAM label is a link error.

## Keeping the docs in sync

Most facts are written in more than one doc. When you change one of these, update every place in its row (the first one is the full version), then run `python run.py test`; `check_docs.py` catches dead paths, unlisted examples and undocumented TWEAKS, but not wrong descriptions.

| when this changes | update |
| --- | --- |
| an instruction (encoding or behaviour) | `encoding.py` + `isa.py` + `alu.py`/`cpu.py`; TECHNICAL §1, `compiler/assembly_syntax.md` §4, STRUCTURE "ISA cheat sheet", README if it's the one-paragraph summary |
| assembler syntax, directives, pseudo-ops | `compiler/assembly_syntax.md`; TECHNICAL §4, STRUCTURE "Assembler conventions" |
| a command, flag or output path | TECHNICAL §3.3 / §4.1 / §7; README "Quick start", STRUCTURE "Common commands", `assembly_syntax.md` §10, this file's Commands |
| a stdlib function or the calling convention | the header of `stdlib.asm`; TECHNICAL §5.1–5.2, STRUCTURE "Assembler conventions" |
| an example program added, renamed or removed | its own header (build command, expected output); TECHNICAL §5.3, STRUCTURE tree |
| a TWEAKS switch, or a behaviour measured on the circuit | `config.py`; TECHNICAL §3.4 and §8, STRUCTURE "Open questions / gotchas", the diag file's header (see the `circuit-check` skill) |
| a subcircuit, pin or device in `CPU.circ` | TECHNICAL §2; STRUCTURE "Circuit hierarchy" |
| a self-check added or removed | TECHNICAL §7.3; the counts in STRUCTURE's tree and in this file |
| a file or folder added, moved or removed | STRUCTURE tree; README "Layout"; TECHNICAL §9 if it's outdated material |

## Outdated notes

`logisim/cpu datas/` holds old personal notes (stack micro-steps, a TODO list), not a description of the current design. The old hand-assembled programs (`cpu_sim/examples/`, `logisim/functions/`) were removed on 2026-10-06 and are only in git history. Unused subcircuits in `CPU.circ` are listed in `TECHNICAL.md` §9.
