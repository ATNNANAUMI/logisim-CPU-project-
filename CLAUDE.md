# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A 32-bit CPU built from logic gates in Logisim-evolution 4.1.0 (`logisim/CPU.circ`), plus its toolchain in Python 3.10+ (standard library only; `tkinter` for the simulator window; the `anthropic` package only for the simulator's Claude device, imported on first use): an assembler/linker, an assembly standard library, a C compiler ("tiny C") with its own C library, and a simulator that runs the same ROM images as the circuit.

`STRUCTURE.md` is a compact project map written for AI assistants (directory tree, circuit hierarchy, ISA cheat sheet, assembler and C conventions, gotchas). Read it first. `TECHNICAL.md` is the full reference; `compiler/assembly_syntax.md` is the current assembly language reference; `compiler/c_language.md` is the C reference and `compiler/c_decisions.md` records why the C compiler is built the way it is, and what is still a guess.

## Commands

```
python run.py test                                   # five self-check suites (assembler 24, simulator 55, C compiler 21, image tool 10, disk tool 28), then check_docs.py
python compiler/src/asm/selftest.py                  # assembler only
python cpu_sim/src/selftest.py                       # simulator only
python compiler/src/cc/selftest.py                   # C compiler only (a few seconds: runs every test program)
python compiler/src/img/selftest.py                  # image converter + gfx_image() only
python compiler/src/disk/selftest.py                 # disk tool + filesystem only
python compiler/src/cc/tests/difftest.py [names] [--update]   # C test programs against gcc (--update rewrites .expected)
python compiler/src/cc/tests/fuzz.py [--count N] [--seed S]   # random C programs, gcc against tiny C
pypy3 cpu_sim/src/bench.py [names] [--repeat N] [--scale F]   # simulator speed (MHz) on nine example programs + end-state digest

# a single check (assembler, C compiler and image tool checks are check_*, simulator ones are test_*)
python -c "import sys; sys.path.insert(0,'compiler/src/asm'); import selftest; selftest.check_linking()"
python -c "import sys; sys.path.insert(0,'cpu_sim/src'); import selftest; selftest.test_keyboard_input()"
python -c "import sys; sys.path.insert(0,'compiler/src/cc'); import selftest; selftest.check_errors()"

python compiler/src/asm build prog.asm compiler/examples/asm/stdlib/stdlib.asm [-o name.rom] [--map]
python compiler/src/asm build prog.asm --lib compiler/examples/asm/stdlib/stdlib.asm   # link only the stdlib functions used
python compiler/src/asm disasm compiler/ROM/prog.rom [--map compiler/ROM/prog.map] [-o out.asm] [--raw]   # a .rom or .exe back to assembly that builds the same words
python compiler/src/asm/isa_page.py [-o isa.html]    # the ISA as one HTML page (default compiler/ROM/isa.html): bits, micro-steps, decoder, encoder
python cpu_sim/src/main.py compiler/ROM/prog.rom                             # GUI
python cpu_sim/src/main.py compiler/ROM/prog.rom --headless --steps 2000000 [--trace] [--keys $'text\n'] [--screen out.png] [--disk disk.img]
python cpu_sim/src/main.py compiler/ROM/prog.rom --headless --steps N --mouse '40,5,1@300000'   # a scripted pointer (x,y,buttons@step;...) for the mouse device 0xBC/0xBD
python cpu_sim/src/main.py compiler/ROM/prog.rom [--screen-fps 30]            # the window: the RGB screen is drawn at most this often while a program runs
python cpu_sim/src/main.py compiler/ROM/prog.rom --headless --steps N --save-state run.state   # the whole machine at the end (snapshot.py)
python cpu_sim/src/main.py --load-state run.state [--headless] [--disk copy.img]   # go on from a snapshot (the window: save state / load state)
python cpu_sim/src/main.py compiler/ROM/kernel.rom --disk tynix/disk.img [--claude-model haiku|sonnet|opus|fable] [--claude-system FILE]   # then `claude` in Tynix (pip install anthropic, a key on the PC)
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/prog.rom [--seconds N]   # real circuit, headless
python logisim/microcode/microcode.py [--list]       # CONTROL_SECTION as a 64K x 32 microcode ROM -> logisim/microcode/microcode.rom
python logisim/microcode/verify.py [--quick]         # that ROM against the circuit's gates, every IR/step/flags (needs javac; minutes)

python compiler/src/cc run prog.c [--keys $'text\n'] [--stats] [--disk disk.img] [--claude-model NAME]   # C: build + run in the simulator
python compiler/src/cc build prog.c [more.c x.asm] [-o name.rom] [--map] [--lib x.asm]   # C: links the C library itself
python compiler/src/cc build prog.c --exe [--region N]   # a program for the OS: prog.exe (TEX2, relocatable), for `disk put`; the kernel runs it
python compiler/src/cc compile prog.c [-o prog.asm]                   # C -> assembly only
python tynix/make_disk.py [IMG] [--new] [--size MB]                  # the OS's disk: tynix/disk.img, /bin/sh (shell.c) and the C examples built --exe in /bin
tynix/run_with_video.sh [clip.h]                     # kernel + disk with video_player in /bin (a clip from img/video.py), opens the window
python compiler/src/cc build tynix/kernel.c && python cpu_sim/src/main.py compiler/ROM/kernel.rom --disk tynix/disk.img   # the OS (kernel, then /bin/sh)

python compiler/src/img pic.png [-o pic.h] [--size WxH] [--colors N] [--dither] [--preview p.png]   # PNG -> compressed pic.h for gfx_image()
python compiler/src/img/video.py clip.mp4 [-o clip.h] [--fps N] [--seconds S] [--colors N] [--tolerance T] [--preview dir/]   # video (ffmpeg) or PNG folder -> frames for video_player.c
pypy3 compiler/src/cc run compiler/examples/c/graphics/video_player.c -I . -D 'VIDEO="clip.h"' --steps 2000000000   # play ./clip.h on time (waiting burns instructions: big --steps)

python compiler/src/disk format disk.img [--size MB]          # empty TFS1 disk image (64 MB, sparse)
python compiler/src/disk put|get|cat|ls|rm|mkdir|rmdir|mv|df|fsck disk.img ...   # edit it from the PC
```

`run_rom.py` finds the jar via `$LOGISIM_JAR` or the Arch package path. A circuit run stops at `HALT` (printing `--- halted at HALT ---`) because Logisim's headless mode watches the output pin labelled `halt` in the top-level `PC` circuit; keep that pin and its label if the circuit is reworked. The `circuit-check` skill (`.claude/skills/`) covers comparing the simulator with the circuit.

There is no linter or build step. Assembler output goes to `compiler/ROM/` (git-ignored); an `-o` containing a directory component is used as given.

## Architecture

Pipeline: `.asm` → two-pass assembler (`assembler.py`, with pseudo-op expansion and relocations) → `.obj` (JSON, `objfile.py`) → `linker.py` → `.rom` in Logisim "v2.0 raw" format → either the Python simulator or the real circuit (`run_rom.py` patches the image into the ROM component inside the `RAM` subcircuit and runs Logisim headless).

The ISA is encoded in two independent places that must stay in sync: `compiler/src/asm/encoding.py` (assembler) and `cpu_sim/src/isa.py` (simulator decode/disassemble). An ISA change also touches `alu.py`/`cpu.py`/`translate.py`, the docs, and possibly `stdlib.asm`.

Simulator speed: `CPU.run()` translates code that execution has jumped to 50 times into Python functions (`translate.py`, TECHNICAL §3.2; a generated if-tree per bank dispatches them, which pypy3 compiles well) and interprets the rest in `_interpret()`; `step()` is the slow, traced path and the reference. Translations survive `reset()` (re-checked against memory); a RAM store drops only the translated RAM blocks made from that word, and only if it changed them; after editing memory from outside during a run, call `cpu.forget_code()`. `bench.py` measures it (pypy3 about 100 MHz over its programs, CPython 15-21).

C: `compiler/src/cc/` (preprocessor → parser/type checker → `codegen.py` + `regalloc.py` + `peephole.py`) writes assembly text, which `driver.py` feeds to `compiler/src/asm`'s assembler and links with a generated crt0 and the C library (`compiler/libc/`, compiled once and cached in `compiler/ROM/libc/`; only the files a program needs are linked). Every program in `compiler/src/cc/tests/` must print exactly what gcc's build prints (`.expected` files come from gcc); keep test programs free of undefined behaviour and of type sizes. `compiler/examples/c/tests/circuit_test.c` checks the compiler's tricky code paths on the circuit.

Pictures: `compiler/src/img/` turns a PNG into a `.h` holding a compressed image (palette + a bit stream of literals and runs, format in `codec.py`'s docstring); `gfx_image()` in `compiler/libc/gfx_image.c` decodes it onto the RGB screen. The two decoders (`codec.decode`, the reference, and the C one) must stay in sync; the img self-check compares them pixel by pixel. Videos: `compiler/src/img/video.py` makes every frame an ordinary picture (one palette shared by all frames, frame 0 whole, later frames only the pixels that changed, the rest transparent) and `compiler/examples/c/graphics/video_player.c` draws frame i when `clock()` reaches i × 1000 / fps. `clock()` reads the timer device `0x7C` (milliseconds since reset; planned wiring, not on the circuit), which the simulator takes from the computer's real clock and the window stops while paused.

Disk: the simulator's disk device (`0x8C`/`0x8D`, `--disk FILE`) is a file of words; `compiler/src/disk/` makes and edits images in the TFS1 filesystem (format in `fs.py`'s docstring: 256-word blocks chained by a FAT, directories are files of 132-word entries, text files packed 4 chars a word). The C library's `fs.c`/`dir.c` (`fopen` and friends, `dirent.h`, `unistd.h`) read and write the same format, and `fs.py` is the reference; the disk self-check runs both against each other. Programs for the OS: `cc build --exe` links a C program at `0x1100000` with a 16K-word stack after its data (`linker.link(base=..., exe_stack=...)`, which keeps the offsets of the words holding addresses) into a TEX2 `.exe` (format in `compiler/libc/include/sys/tynix.h`), against the library of `compiler/libc/tynix/`, whose files replace their namesakes: files, directories, keys, `spawnv` and `wait_ms` are system calls (`TRAP`, R1 = the number).

The OS, Tynix (simulator only, TECHNICAL §11): `tynix/kernel.c` is the ROM, a preemptive multitasking kernel with no memory protection (AmigaOS-like). It boots, runs `fs_reclaim()`, and starts `/bin/sh` (`tynix/shell.c`, built `--exe` by `make_disk.py`). It loads each program into its own region of RAM (first fit above `0x1200000`, 1M words or `--region`; TEX1 programs alone at `0x1100000`), relocates it, and switches programs on the timer (10 ms slices, timer on only when two want the CPU or one sleeps: tickless) through `interrupt.asm`'s `_int_kstack`/`_int_cur`/`_int_next` (its C runs on its own stack with interrupts off; a program's state is its stack). It owns the only `fs.c` (files by number, closed when a program ends; `share()` keeps two opens of one file in step), the keyboard (only the foreground program reads it; waiting calls sleep), the RGB screen (background `gfx_` calls wait; `gfx_lost()` tells a program to redraw) and the NMI menu (Esc: `[NAME: 1 kill, 2 continue, 3 background, 4 tasks]`). The shell has `&`, `jobs`, `fg`, `kill`, `wait`, `run FILE`, `<`, variables (`set`, `export`, `$NAME`, `$?`, `PATH`, `/etc/profile`), and `sh -c LINE` runs one line; a program's environment (`B_ENV`) is a copy of its parent's. A child gets its caller's stdout and stdin (files when the caller's are); `spawn_io()` (`SPAWN_IN(fd)`) gives it a stdin file. `tynix/bin/ed.c` (line editor) and `tynix/bin/edit.c` (full-screen editor on the RGB screen: polls keys, redraws changed cells at most every 33 ms) are `/bin` programs like the examples, and so are the tools `more grep find tree du diff hexdump calc` and `visual_file_manager` (a two-pane file manager on the RGB screen, which opens files with `spawnv()`). `tynix/make_disk.py` builds `tynix/disk.img` (git-ignored) with `sh` and the programs in `PROGRAMS`. A program past its stack ends with status 139, a killed one 130.

Claude (Phase 8, TECHNICAL §11.5): the simulator's Claude device (`0x9C`, `cpu_sim/src/claude.py`) is a terminal to the Claude API on the PC. A worker thread streams the reply (model `claude-haiku-5-5`, effort low, max_tokens 100,000, automatic caching) while the CPU polls; the history, the `/` commands, the costs and the PC-side tools (files under `tynix/claude/` and `tynix/claude_access.conf`, the screenshot) live in Python. `tynix/bin/claude.c` (`/bin/claude`) is the CPU side: it prints the reply, and runs Claude's commands as `sh -c` with stdin and stdout files and a timeout kill. `tynix/cpu_claude.md` is the system prompt. The self-checks use `FakeBackend` (no key or network here); the real backend was only run against a local fake of the API.

`compiler/src/asm/`, `compiler/src/cc/`, `compiler/src/img/`, `compiler/src/disk/` and `cpu_sim/src/` import their sibling modules by plain name, so run files as scripts (or put the directory on `sys.path`), not as packages. The assembler, the C compiler, the image converter and the disk tool are invoked as directories (`python compiler/src/asm <cmd>`, `python compiler/src/cc <cmd>`, `python compiler/src/img pic.png`, `python compiler/src/disk <cmd> disk.img`, via `__main__.py`).

**The circuit is the ground truth.** The simulator was written from the ISA, not derived from the circuit. Behaviours not yet verified on the circuit are switches in `cpu_sim/src/config.py` (TWEAKS, each marked confirmed/guess). The circuit's `NOT` inverted RA until it was rewired to RB on 2026-10-15; the assembler still writes `NOT Rx` with x in both fields, which works either way (see TECHNICAL §8). Diagnostic programs used to measure circuit behaviour live in `compiler/examples/asm/tests/`.

Key ISA facts that trip people up (details in STRUCTURE.md):
- Every ALU result goes to **R0**, and every ALU op rewrites all flags.
- Jumps are relative to the address of the offset word.
- The carry flag: `SUB` sets C on a *borrow* (`RA < RB` unsigned); `CMP`, `--`, `NEG`, `MULT` never set it (measured on the circuit).
- `STK CALL/RET` only move the stack frame; the `CALL`/`RET` pseudo-ops do the jump and clobber R0/R14/R15.
- The linker puts `RJMP start` at address 0. Exactly one file has `.global start`. Calling or jumping to a RAM label is a link error.
- Memory: 16M words of ROM and of RAM (24-bit banks, 25-bit addresses, RAM from `0x1000000`; linker data from `0x1000000`, then the stack (16K words), then the heap; no fixed stack area, ESP/EBP are 24-bit RAM indices set by the start-up code; vectors at ROM 0–9; programs for the OS linked at `0x1100000` and moved by Tynix into regions from `0x1200000`). **The circuit still has 16-bit banks** (RAM from `0x10000`), so programs built now run only in the simulator until it is widened (TECHNICAL §2.4); `run_rom.py` refuses. A simulated CPU holds two 128 MB lists.
- In C, every scalar is one word (`sizeof(char) == 1`, `CHAR_BIT == 32`), `double` is the 32-bit float, and there is no `long long`.

## Keeping the docs in sync

Most facts are written in more than one doc. When you change one of these, update every place in its row (the first one is the full version), then run `python run.py test`; `check_docs.py` catches dead paths, unlisted examples and undocumented TWEAKS, but not wrong descriptions.

| when this changes | update |
| --- | --- |
| an instruction (encoding or behaviour) | `encoding.py` + `asm_grammar.py` + `isa.py` (+ a row in `assembly_syntax.md` §4, which `isa_page.py` and `check_docs.py` read) + `alu.py`/`cpu.py` (both `_execute()` and the `_interpret()` loop) + `translate.py` (the code it writes); TECHNICAL §1 (and 1.8 for group 0x2), `compiler/assembly_syntax.md` §4, STRUCTURE "ISA cheat sheet", README if it's the one-paragraph summary |
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
| the compressed image format | `compiler/src/img/codec.py` (docstring, encode, decode) + `compiler/libc/gfx_image.c`; TECHNICAL §7.4, then remake the `.h` files in `compiler/examples/c/graphics/images/` |
| the memory map (bank width, RAM base, stack, heap) | `compiler/src/asm/linker.py` (the vectors, `_header()`, the stack after the data) + `cpu_sim/src/config.py` + `compiler/libc/malloc.c` (`HEAP_END`) + `stdlib.asm` (`HEAP_START`/`HEAP_END`) + `logisim/run_rom.py` (`BANK_BITS`); TECHNICAL §1.2/§2.4/§4.6, `assembly_syntax.md` §6, `c_language.md` §2 and §4, STRUCTURE "ISA cheat sheet", README one-paragraph summary, this file's key facts |
| interrupts (vectors, the saved word, the controller `0xAC`/`0xAD`, the timer period, NMI, the stack limit) | `cpu_sim/src/cpu.py` (`_enter`, `_return`, `_service`, `step()`, `run()`, `_interpret()`) + `devices.py` + `translate.py` (a block ends before group 0x2, PUSH/CALL check the limit) + `config.py` + `compiler/src/asm/linker.py` + `compiler/libc/interrupt.asm`/`cpu.h`; TECHNICAL §1.8 and §2.6 (the circuit change list), `compiler/c_language.md` §6, `c_decisions.md` |
| the screen's size (256×256, one pixel word: x 31–24, y 23–16, colour 15–0) | `cpu_sim/src/config.py` (`VIDEO_WIDTH`/`VIDEO_HEIGHT`) + `compiler/libc/include/gfx.h` (`GFX_WIDTH`/`GFX_HEIGHT`) + `SCREEN` in `compiler/src/img/__main__.py` + `logisim/CPU.circ` (RGB Video `resolution`, `width`, `height` and `scale`; `RGB_Display`'s two splitters and `X_coord`/`Y_coord` pins); TECHNICAL §2.2 and the device table, STRUCTURE, README, `compiler/c_language.md`; examples that place things by pixel (`snake.c`, `grapher.c`, `gfx_demo.c`) and `tynix/bin/edit.c`'s comments |
| a file or folder added, moved or removed | STRUCTURE tree; README "Layout"; TECHNICAL §9 if it's outdated material |
| a shell command, or the programs put in `/bin` | `tynix/shell.c` (header, `commands[]`), `tynix/make_disk.py` (`PROGRAMS`, `REGIONS`, `README`); TECHNICAL §11, STRUCTURE tree, the disk self-check's `SHELL_OUTPUT` |
| a system call, the block a program gets, or TEX2 | `compiler/libc/include/sys/tynix.h` + `tynix/kernel.c` + the wrapper in `compiler/libc/tynix/` (+ `driver.py`'s crt0 / `exe_bytes()` for the block and TEX2); TECHNICAL §10.4/§10.5/§11, `compiler/c_language.md` §7, STRUCTURE |
| the Claude device (protocol, tools, slash commands, models or prices) | `cpu_sim/src/claude.py` (docstring, `MODELS`, `TOOLS`, `command()`) + `tynix/bin/claude.c` (+ `<cpu.h>`'s `CLAUDE_*`); TECHNICAL §1.7 and §11.5, STRUCTURE, and `tynix/cpu_claude.md` when Claude should know |
| what Claude is told (the machine, the characters, the tools, the commands, what not to run, the limits) | `tynix/cpu_claude.md`; check it again when a shell command, a `/bin` program or a limit changes |
| a phase or feature finished, a choice made, a mistake of the session | the Obsidian vault (next section) |

## The Obsidian vault (outside the repo)

Arthur keeps the project's notes in a private Obsidian vault, `~/Documents/obsidian-notes/logisim-CPU/` (its own git repo, backed up by itself). It is not part of this public repository: never copy its content here, and never put personal notes in the repo. After work that changes the project, update the vault in the same session, not only the repo docs:

- `Output/pages/os_roadmap.md`: the phase checklist and its Log (dated entry with branch/commit names); `Output/pages/os_roadmap.html`: the matching timeline entries (same style as the existing ones).
- The topic notes the change touches, in `Wiki/`: `OS/OS plan.md`, `Project/Roadmap.md`, `Project/Questions for me.md`, `Toolchain/Commands.md`, `Toolchain/Testing and verification.md` (check counts).
- `Wiki/OS/How it works/NN <part>.md` (index `How it works.md`): one note per OS part, following ONE concrete example from the C line to the instructions, machine words, registers and bytes, with numbers from real simulator runs; ends with "Ideas for the video".
- Open A/B choices: a new round in `Wiki/OS/OS questionnaire.md` (one box per option, **(rec)** on yours), linked from `Project/Questions for me.md`; when answered, a `> [!done]` callout.
- Mistakes of the session: `Raw/ai-mistakes/ai_mistakes_<date>_<topic>.md` in the format of `Raw/ai-mistakes/ai_mistakes_prompt.md` (honest, including slips caught before committing); these logs are historical, never rewritten later.

The vault has its own rules in `~/Documents/obsidian-notes/CLAUDE.md` (folders `Raw/`, `Wiki/`, `Output/`; never read or list `_build/`; a new note is linked from the project index note in `Wiki/` and from the vault's `Home.md`). Read them before editing it.

Visual pages stay local files in the vault, not claude.ai artifacts.

## Outdated notes

`logisim/old_notes/` holds old personal notes (stack micro-steps, a TODO list), not a description of the current design. The old hand-assembled programs (`cpu_sim/examples/`, `logisim/functions/`) were removed on 2026-10-06 and are only in git history. Unused subcircuits in `CPU.circ` are listed in `TECHNICAL.md` §9.
