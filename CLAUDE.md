# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A 32-bit CPU built from logic gates in Logisim-evolution 4.1.0 (`logisim/CPU.circ`), plus its toolchain in Python 3.10+ (standard library only; `tkinter` for the simulator window): an assembler/linker, an assembly standard library, a C compiler ("tiny C") with its own C library, and a simulator that runs the same ROM images as the circuit.

`STRUCTURE.md` is a compact project map written for AI assistants (directory tree, circuit hierarchy, ISA cheat sheet, assembler and C conventions, gotchas). Read it first. `TECHNICAL.md` is the full reference; `compiler/assembly_syntax.md` is the current assembly language reference (the copy in `compiler/src/asm/` is outdated); `compiler/c_language.md` is the C reference and `compiler/c_decisions.md` records why the C compiler is built the way it is, and what is still a guess.

## Commands

```
python run.py test                                   # five self-check suites (assembler 20, simulator 25, C compiler 15, image tool 10, disk tool 15), then check_docs.py
python compiler/src/asm/selftest.py                  # assembler only
python cpu_sim/src/selftest.py                       # simulator only
python compiler/src/cc/selftest.py                   # C compiler only (a few seconds: runs every test program)
python compiler/src/img/selftest.py                  # image converter + gfx_image() only
python compiler/src/disk/selftest.py                 # disk tool + filesystem only
python compiler/src/cc/tests/difftest.py [names] [--update]   # C test programs against gcc (--update rewrites .expected)
python compiler/src/cc/tests/fuzz.py [--count N] [--seed S]   # random C programs, gcc against tiny C

# a single check (assembler, C compiler and image tool checks are check_*, simulator ones are test_*)
python -c "import sys; sys.path.insert(0,'compiler/src/asm'); import selftest; selftest.check_linking()"
python -c "import sys; sys.path.insert(0,'cpu_sim/src'); import selftest; selftest.test_keyboard_input()"
python -c "import sys; sys.path.insert(0,'compiler/src/cc'); import selftest; selftest.check_errors()"

python compiler/src/asm build prog.asm compiler/examples/stdlib/stdlib.asm [-o name.rom] [--map]
python compiler/src/asm build prog.asm --lib compiler/examples/stdlib/stdlib.asm   # link only the stdlib functions used
python cpu_sim/src/main.py compiler/ROM/prog.rom                             # GUI
python cpu_sim/src/main.py compiler/ROM/prog.rom --headless --steps 2000000 [--trace] [--keys $'text\n'] [--screen out.png] [--disk disk.img]
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/prog.rom [--seconds N]   # real circuit, headless

python compiler/src/cc run prog.c [--keys $'text\n'] [--stats] [--disk disk.img]   # C: build + run in the simulator
python compiler/src/cc build prog.c [more.c x.asm] [-o name.rom] [--map] [--lib x.asm]   # C: links the C library itself
python compiler/src/cc build prog.c --exe            # a program for the OS: prog.exe (TEX1), for `disk put`; spawnv() runs it
python compiler/src/cc compile prog.c [-o prog.asm]                   # C -> assembly only
python os/make_disk.py [IMG] [--new] [--size MB]                     # the OS's disk: os/disk.img, C examples built --exe in /bin
python compiler/src/cc build os/shell.c && python cpu_sim/src/main.py compiler/ROM/shell.rom --disk os/disk.img   # the OS (shell)

python compiler/src/img pic.png [-o pic.h] [--size WxH] [--colors N] [--dither] [--preview p.png]   # PNG -> compressed pic.h for gfx_image()
python compiler/src/img/video.py clip.mp4 [-o clip.h] [--fps N] [--seconds S] [--colors N] [--tolerance T] [--preview dir/]   # video (ffmpeg) or PNG folder -> frames for video_player.c
pypy3 compiler/src/cc run compiler/examples/c/video_player.c -I . -D 'VIDEO="clip.h"' --steps 2000000000   # play ./clip.h on time (waiting burns instructions: big --steps)

python compiler/src/disk format disk.img [--size MB]          # empty TFS1 disk image (64 MB, sparse)
python compiler/src/disk put|get|cat|ls|rm|mkdir|rmdir|mv|df|fsck disk.img ...   # edit it from the PC
```

`run_rom.py` finds the jar via `$LOGISIM_JAR` or the Arch package path. A circuit run stops at `HALT` (printing `--- halted at HALT ---`) because Logisim's headless mode watches the output pin labelled `halt` in the top-level `PC` circuit; keep that pin and its label if the circuit is reworked. The `circuit-check` skill (`.claude/skills/`) covers comparing the simulator with the circuit.

There is no linter or build step. Assembler output goes to `compiler/ROM/` (git-ignored); an `-o` containing a directory component is used as given.

## Architecture

Pipeline: `.asm` → two-pass assembler (`assembler.py`, with pseudo-op expansion and relocations) → `.obj` (JSON, `objfile.py`) → `linker.py` → `.rom` in Logisim "v2.0 raw" format → either the Python simulator or the real circuit (`run_rom.py` patches the image into the ROM component inside the `RAM` subcircuit and runs Logisim headless).

The ISA is encoded in two independent places that must stay in sync: `compiler/src/asm/encoding.py` (assembler) and `cpu_sim/src/isa.py` (simulator decode/disassemble). An ISA change also touches `alu.py`/`cpu.py`, the docs, and possibly `stdlib.asm`.

C: `compiler/src/cc/` (preprocessor → parser/type checker → `codegen.py` + `regalloc.py` + `peephole.py`) writes assembly text, which `driver.py` feeds to `compiler/src/asm`'s assembler and links with a generated crt0 and the C library (`compiler/libc/`, compiled once and cached in `compiler/ROM/libc/`; only the files a program needs are linked). Every program in `compiler/src/cc/tests/` must print exactly what gcc's build prints (`.expected` files come from gcc); keep test programs free of undefined behaviour and of type sizes. `compiler/examples/c/circuit_test.c` checks the compiler's tricky code paths on the circuit.

Pictures: `compiler/src/img/` turns a PNG into a `.h` holding a compressed image (palette + a bit stream of literals and runs, format in `codec.py`'s docstring); `gfx_image()` in `compiler/libc/gfx_image.c` decodes it onto the RGB screen. The two decoders (`codec.decode`, the reference, and the C one) must stay in sync; the img self-check compares them pixel by pixel. Videos: `compiler/src/img/video.py` makes every frame an ordinary picture (one palette shared by all frames, frame 0 whole, later frames only the pixels that changed, the rest transparent) and `compiler/examples/c/video_player.c` draws frame i when `clock()` reaches i × 1000 / fps. `clock()` reads the timer device `0x7C` (milliseconds since reset; planned wiring, not on the circuit), which the simulator takes from the computer's real clock and the window stops while paused.

Disk: the simulator's disk device (`0x8C`/`0x8D`, `--disk FILE`) is a file of words; `compiler/src/disk/` makes and edits images in the TFS1 filesystem (format in `fs.py`'s docstring: 256-word blocks chained by a FAT, directories are files of 132-word entries, text files packed 4 chars a word). The C library's `fs.c`/`dir.c` (`fopen` and friends, `dirent.h`, `unistd.h`) read and write the same format, and `fs.py` is the reference; the disk self-check runs both against each other. Programs for the OS: `cc build --exe` links a C program for RAM at `0x1100000` (`linker.link(base=...)`) into a TEX1 `.exe` (format in `compiler/libc/spawn.c`), and `spawnv()` (`spawn.c`/`spawn.asm`) loads it from the disk, runs it with argc/argv through the block crt0 gets in R1, and comes back by longjmp when it exits.

The OS, Tynix (simulator only, TECHNICAL §11): `os/shell.c` is an ordinary C program in ROM; its built-in commands use the C library's file functions, and any other name is a `cc build --exe` program that `spawnv()` loads from `/bin` on the disk, runs at `0x1100000` and returns from. `os/make_disk.py` builds `os/disk.img` (git-ignored) with the examples in `PROGRAMS`. A program in `/bin` must end by itself (no interrupts): the examples quit on Ctrl-D or `q`.

`compiler/src/asm/`, `compiler/src/cc/`, `compiler/src/img/`, `compiler/src/disk/` and `cpu_sim/src/` import their sibling modules by plain name, so run files as scripts (or put the directory on `sys.path`), not as packages. The assembler, the C compiler, the image converter and the disk tool are invoked as directories (`python compiler/src/asm <cmd>`, `python compiler/src/cc <cmd>`, `python compiler/src/img pic.png`, `python compiler/src/disk <cmd> disk.img`, via `__main__.py`).

**The circuit is the ground truth.** The simulator was written from the ISA, not derived from the circuit. Behaviours not yet verified on the circuit are switches in `cpu_sim/src/config.py` (TWEAKS, each marked confirmed/guess). The circuit's `NOT` inverted RA until it was rewired to RB on 2026-10-15; the assembler still writes `NOT Rx` with x in both fields, which works either way (see TECHNICAL §8). Diagnostic programs used to measure circuit behaviour live in `compiler/examples/tests/`.

Key ISA facts that trip people up (details in STRUCTURE.md):
- Every ALU result goes to **R0**, and every ALU op rewrites all flags.
- Jumps are relative to the address of the offset word.
- The carry flag: `SUB` sets C on a *borrow* (`RA < RB` unsigned); `CMP`, `--`, `NEG`, `MULT` never set it (measured on the circuit).
- `STK CALL/RET` only move the stack frame; the `CALL`/`RET` pseudo-ops do the jump and clobber R0/R14/R15.
- The linker puts `RJMP start` at address 0. Exactly one file has `.global start`. Calling or jumping to a RAM label is a link error.
- Memory: 16M words of ROM and of RAM (24-bit banks, 25-bit addresses, RAM from `0x1000000`; stack `0x1000000–0x1003FFF`, linker data from `0x1004000`, programs for the OS from `0x1100000`). **The circuit still has 16-bit banks** (RAM from `0x10000`), so programs built now run only in the simulator until it is widened (TECHNICAL §2.4); `run_rom.py` refuses. A simulated CPU holds two 128 MB lists.
- In C, every scalar is one word (`sizeof(char) == 1`, `CHAR_BIT == 32`), `double` is the 32-bit float, and there is no `long long`.

## Keeping the docs in sync

Most facts are written in more than one doc. When you change one of these, update every place in its row (the first one is the full version), then run `python run.py test`; `check_docs.py` catches dead paths, unlisted examples and undocumented TWEAKS, but not wrong descriptions.

| when this changes | update |
| --- | --- |
| an instruction (encoding or behaviour) | `encoding.py` + `isa.py` + `alu.py`/`cpu.py` (both `_execute()` and the fast `run()` loop); TECHNICAL §1, `compiler/assembly_syntax.md` §4, STRUCTURE "ISA cheat sheet", README if it's the one-paragraph summary |
| assembler syntax, directives, pseudo-ops | `compiler/assembly_syntax.md`; TECHNICAL §4, STRUCTURE "Assembler conventions" |
| a command, flag or output path | TECHNICAL §3.3 / §4.1 / §7; README "Quick start", STRUCTURE "Common commands", `assembly_syntax.md` §10, this file's Commands |
| a stdlib function or the calling convention | the header of `stdlib.asm`; TECHNICAL §5.1–5.2, STRUCTURE "Assembler conventions" |
| an example program added, renamed or removed (`.asm` or `.c`) | its own header (build command, expected output); TECHNICAL §5.3, STRUCTURE tree |
| a TWEAKS switch, or a behaviour measured on the circuit | `config.py`; TECHNICAL §3.4 and §8, STRUCTURE "Open questions / gotchas", the diag file's header (see the `circuit-check` skill) |
| a subcircuit, pin or device in `CPU.circ` | TECHNICAL §2; STRUCTURE "Circuit hierarchy" |
| the disk filesystem format (TFS1) | `compiler/src/disk/fs.py` (docstring + code) + `compiler/libc/fs.c`/`dir.c`; TECHNICAL §7.6 |
| a self-check added or removed | TECHNICAL §7.3; the counts in STRUCTURE's tree and in this file |
| the C language or the C compiler's conventions | `compiler/c_language.md`; TECHNICAL §10, STRUCTURE "C compiler conventions", `compiler/c_decisions.md` when it is a design decision or a guess |
| a C library function or header | the header and its `compiler/libc/*.c`; `compiler/c_language.md` §7; TECHNICAL §10.5 for library structure |
| a C test program | `compiler/src/cc/tests/<name>.c`, then `difftest.py <name> --update` (needs gcc) to write its `.expected` |
| the compressed image format | `compiler/src/img/codec.py` (docstring, encode, decode) + `compiler/libc/gfx_image.c`; TECHNICAL §7.4, then remake the `.h` files in `compiler/examples/c/images/` |
| the memory map (bank width, RAM base, stack, heap) | `compiler/src/asm/linker.py` + `cpu_sim/src/config.py` + `compiler/libc/malloc.c` (`HEAP_END`) + `stdlib.asm` (`HEAP_START`/`HEAP_END`) + `logisim/run_rom.py` (`BANK_BITS`); TECHNICAL §1.2/§2.4/§4.6, `assembly_syntax.md` §6, `c_language.md` §2 and §4, STRUCTURE "ISA cheat sheet", README one-paragraph summary, this file's key facts |
| a file or folder added, moved or removed | STRUCTURE tree; README "Layout"; TECHNICAL §9 if it's outdated material |
| a shell command, or the programs put in `/bin` | `os/shell.c` (header, `commands[]`), `os/make_disk.py` (`PROGRAMS`, `README`); TECHNICAL §11, STRUCTURE tree, the disk self-check's `SHELL_OUTPUT` |

## Outdated notes

`logisim/cpu datas/` holds old personal notes (stack micro-steps, a TODO list), not a description of the current design. The old hand-assembled programs (`cpu_sim/examples/`, `logisim/functions/`) were removed on 2026-10-06 and are only in git history. Unused subcircuits in `CPU.circ` are listed in `TECHNICAL.md` §9.
