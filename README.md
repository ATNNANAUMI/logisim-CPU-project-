# logisim-CPU-project

A 32-bit CPU built from logic gates in Logisim-evolution, with the tools to
program it: an assembler and linker, a small standard library, and a Python
simulator that runs the same ROM images as the circuit.

```
  .asm files ──► assembler ──► .obj ──► linker ──► .rom (Logisim "v2.0 raw")
                                                     │
                                ┌────────────────────┴───────────────┐
                                ▼                                    ▼
                  cpu_sim/src  (Python, GUI or headless)    logisim/CPU.circ  (the real circuit)
```

## The machine in one paragraph

32-bit words, 16 registers (`R0`–`R15`), a 17-bit address bus where bit 16
picks RAM (`0x10000`–`0x1FFFF`) over ROM (`0x00000`–`0x0FFFF`), four flags
(`C A N Z`), a hardware stack in the first 16K words of RAM, integer and
IEEE-754 float ALUs, and I/O through a single `COMM` instruction: a text
display at `0x5C`, a hex number display at `0x3C` and a keyboard at `0xF0`.
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
python run.py test                # assembler + simulator self-checks
python run.py asm   prog.asm lib.asm            # -> compiler/ROM/prog.rom
python run.py sim   compiler/ROM/prog.rom
python run.py build prog.asm lib.asm            # assemble, then open the simulator
```

Or call the tools directly:

```
# assemble + link a program with the standard library
python compiler/src/asm build compiler/examples/stdlib/stdlib_demo.asm \
                              compiler/examples/stdlib/stdlib.asm -o demo.rom
# (written to compiler/ROM/demo.rom; an -o with a folder, like ./demo.rom, is used as is)

# run it in the simulator (window, or terminal only)
python cpu_sim/src/main.py compiler/ROM/demo.rom
python cpu_sim/src/main.py compiler/ROM/demo.rom --headless --steps 2000000

# run it on the real circuit, headless (needs the Logisim-evolution jar)
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/demo.rom --jar path/to/logisim-evolution-4.1.0-all.jar
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

More in `compiler/examples/programs/`.

## Layout

| path | what it is |
| --- | --- |
| `logisim/CPU.circ` | the circuit (top level: `PC`) |
| `logisim/run_rom.py` | load a ROM into the circuit and run Logisim headless |
| `compiler/src/asm/` | assembler, linker, self-checks |
| `compiler/examples/` | example programs, the standard library (`stdlib/stdlib.asm`), circuit diagnostics |
| `compiler/rom/` | build output for ROM images (ignored by git) |
| `compiler/assembly_syntax.md` | full assembly language reference |
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
