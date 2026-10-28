# logisim-CPU-project

A 32-bit CPU built from logic gates in Logisim-evolution, with the tools to
program it: an assembler and linker, a small standard library, a C compiler
with a C library, and a Python simulator that runs the same ROM images as the
circuit.

```
  .c files ──► C compiler ──► .asm files (and the C library)
  .asm files ──► assembler ──► .obj ──► linker ──► .rom (Logisim "v2.0 raw")
                                                     │
                                ┌────────────────────┴───────────────┐
                                ▼                                    ▼
                  cpu_sim/src  (Python, GUI or headless)    logisim/CPU.circ  (the real circuit)
```

## The machine in one paragraph

32-bit words, 16 registers (`R0`–`R15`), a 25-bit address bus where bit 24
picks RAM (`0x1000000`–`0x1FFFFFF`) over ROM (`0x0000000`–`0x0FFFFFF`), 16M
words each (the circuit itself still has the 16-bit version), four flags
(`C A N Z`), a hardware stack in the first 16K words of RAM, integer and
IEEE-754 float ALUs, and I/O through a single `COMM` instruction: a text
display at `0x5C`, a hex number display at `0x3C` and a keyboard at `0xF0`
(plus a 128×128 RGB screen at `0x6C`, drawn on from C with `gfx.h`, and a
millisecond timer at `0x7C`, wiring planned, which C's `clock()` reads,
and, in the simulator only, a disk kept in a file at `0x8C`/`0x8D`, with a
filesystem that C's `fopen` reads and writes and `compiler/src/disk` edits
from the PC, and programs that C's `spawnv` loads from it into RAM and runs).
Every ALU result goes to **R0**.

## Requirements

* Python 3.10+, standard library only
* `tkinter` for the simulator window (Arch: `tk`, Debian/Ubuntu: `python3-tk`,
  Fedora: `python3-tkinter`)
* Logisim-evolution 4.1.0 to open or run the circuit (not included)

## Quick start

Everything can be driven from `run.py` at the project root:

```
python run.py                     # interactive menu
python run.py test                # assembler, simulator, C compiler and image tool self-checks, docs check
python run.py asm   prog.asm lib.asm            # -> compiler/ROM/prog.rom
python run.py sim   compiler/ROM/prog.rom
python run.py build prog.asm lib.asm            # assemble, then open the simulator
python run.py img   picture.png                 # -> picture.h, a compressed picture for gfx_image()
python run.py video clip.mp4 --fps 10           # -> clip.h, frames for video_player.c (needs ffmpeg)
```

Or call the tools directly:

```
# assemble + link a program with the standard library
python compiler/src/asm build compiler/examples/stdlib/stdlib_demo.asm \
                              compiler/examples/stdlib/stdlib.asm -o demo.rom
# (--lib compiler/examples/stdlib/stdlib.asm instead links only the functions used)
# (written to compiler/ROM/demo.rom; an -o with a folder, like ./demo.rom, is used as is)

# run it in the simulator (window, or terminal only)
python cpu_sim/src/main.py compiler/ROM/demo.rom
python cpu_sim/src/main.py compiler/ROM/demo.rom --headless --steps 2000000
python cpu_sim/src/main.py compiler/ROM/demo.rom --disk disk.img     # with a disk (a file, created if missing)

# run it on the real circuit, headless (finds an installed Logisim-evolution; --jar or $LOGISIM_JAR otherwise)
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/demo.rom
```

C programs go through the C compiler, which links the C library on its own:

```
python compiler/src/cc run compiler/examples/c/hello.c          # build + run in the simulator, print the display
python compiler/src/cc build compiler/examples/c/primes.c       # -> compiler/ROM/primes.rom (+ primes.asm to read)
python compiler/src/cc build compiler/examples/c/echo.c --exe   # -> echo.exe, a program for the disk (see c/loader.c)
python run.py build compiler/examples/c/guess.c                 # build, then open the simulator window
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/primes.rom
```

Pictures for the RGB screen are stored compressed (about 10–60 times
smaller than one word per pixel):

```
python compiler/src/img picture.png             # -> picture.h; #include it, then gfx_image(x, y, picture)
python compiler/src/img/video.py clip.mp4           # -> clip.h next to it (needs ffmpeg)
python compiler/src/disk format disk.img            # an empty disk for --disk; then put/get/ls/cat/rm/mkdir/mv/df
pypy3 compiler/src/cc run compiler/examples/c/video_player.c -I . -D 'VIDEO="clip.h"' --steps 2000000000
python compiler/src/cc run compiler/examples/c/image_demo.c --screen out.png
```

## A taste of the assembly

```asm
        .equ DISPLAY, 0x5C
        .global start

start:  DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R1, 'a'
loop:   COMM OUTDATA, R1
        ++ R1               ; R0 = R1 + 1
        CPY R0, R1
        CMP R1, #'z' + 1
        RJNF Z, loop
        HALT
```

More in `compiler/examples/programs/`. And in C:

```c
#include <stdio.h>

int main(void)
{
    for (int i = 1; i <= 5; i++)
        printf("%d squared is %d\n", i, i * i);
    return 0;
}
```

The C is standard C99 (with a few C11 and GNU additions); every scalar type
is one 32-bit word (`sizeof(char) == 1`, `CHAR_BIT == 32`) and `double` is
32 bits. See `compiler/c_language.md`.

## Layout

| path | what it is |
| --- | --- |
| `logisim/CPU.circ` | the circuit (top level: `PC`) |
| `logisim/run_rom.py` | load a ROM into the circuit and run Logisim headless |
| `compiler/src/asm/` | assembler, linker, self-checks |
| `compiler/src/cc/` | C compiler, self-checks, test programs compared with gcc (`tests/`) |
| `compiler/src/disk/` | disk tool: makes and edits disk images (TFS1 filesystem) for the simulator's `--disk` |
| `compiler/src/img/` | image converter: PNG -> compressed picture for `gfx_image()` (`gfx.h`); `video.py`: a video -> frames for `video_player.c` |
| `compiler/libc/` | the C library: headers (`include/`), C and assembly sources |
| `compiler/examples/` | example programs (assembly, and C in `c/`), the standard library (`stdlib/stdlib.asm`), circuit diagnostics |
| `compiler/ROM/` | build output for ROM images (ignored by git) |
| `compiler/assembly_syntax.md` | full assembly language reference |
| `compiler/c_language.md` | the C language and library reference |
| `compiler/c_decisions.md` | the C compiler's design decisions, guesses and open questions |
| `cpu_sim/src/` | Python simulator (core, GUI, self-checks) |
| `run.py` | one entry point for all of the above |

## Documentation

* [TECHNICAL.md](TECHNICAL.md) — how every part works in detail (ISA,
  circuit, simulator, assembler, linker, stdlib), what is still unconfirmed
  on the circuit, and a list of outdated files.
* [STRUCTURE.md](STRUCTURE.md) — a compact map of the project, written to be
  pasted into a chat with an AI assistant.
* [compiler/assembly_syntax.md](compiler/assembly_syntax.md) — the assembly
  language reference.
* [compiler/c_language.md](compiler/c_language.md) — the C language (tiny C)
  and its library; [compiler/c_decisions.md](compiler/c_decisions.md) — why
  the C compiler works the way it does.
