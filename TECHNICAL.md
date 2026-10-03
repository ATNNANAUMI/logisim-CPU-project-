# Technical reference

How every part of the project works. The README has the short version; this
file has the details.

1. [Instruction set](#1-instruction-set)
2. [The circuit (`logisim/CPU.circ`)](#2-the-circuit-logisimcpucirc)
3. [The simulator (`cpu_sim/src/`)](#3-the-simulator-cpu_simsrc)
4. [The assembler and linker (`compiler/src/asm/`)](#4-the-assembler-and-linker-compilersrcasm)
5. [Calling convention and the standard library](#5-calling-convention-and-the-standard-library)
6. [ROM image format](#6-rom-image-format)
7. [Tooling: `run.py`, `run_rom.py`, self-checks](#7-tooling)
8. [Simulator vs. circuit: open questions](#8-simulator-vs-circuit-open-questions)
9. [Outdated files and stale information](#9-outdated-files-and-stale-information)

---

## 1. Instruction set

### 1.1 Machine state

| item | size | notes |
| --- | --- | --- |
| `R0`–`R15` | 32 bits each | general purpose; every ALU result is written to `R0` |
| `IAR` | 17 bits | instruction address register (program counter) |
| `IR` | 16 bits | instruction register (low 16 bits of the fetched word) |
| flags | 4 bits | `C A N Z` (bit 3 … bit 0) |
| `ESP`, `EBP` | 14 bits each | stack pointer and frame pointer, indices into the stack area |
| `MAR` | 17 bits | memory address register (inside the `RAM` subcircuit) |
| `ACC`, `TMP` | 32 bits each | internal ALU latches, not visible to programs |

### 1.2 Memory map

One 17-bit address bus. Bit 16 chooses the bank:

```
0x00000 ─ 0x0FFFF   ROM  64K × 32   program and constant data, read only
0x10000 ─ 0x13FFF   RAM  stack area (16K words, indexed by ESP/EBP)
0x14000 ─ 0x1FFFF   RAM  free; the linker puts .ram data here
```

* Reads work on both banks. Writes to ROM are dropped (the circuit raises a
  "tried writing in ROM" error line; the simulator ignores the write and notes
  it in the trace).
* The stack is the first quarter of RAM (`RAM[0x0000..0x3FFF]`). `ESP` and
  `EBP` are 14-bit indices into it, so they wrap at 16K. `STK SET/GET`
  addresses are not limited to the stack area: they wrap across the whole
  RAM (see 1.6).
* The IAR is 17 bits, so the CPU *can* fetch from RAM, but the assembler never
  puts code there.

### 1.3 Instruction word

Instructions live in the low 15 bits of a 32-bit word; higher bits are
ignored.

```
 bit 14     bit 13    bit 12    11..8     7..4    3..0
[ IMM ]   [ FLOAT ]  [ ALU ]  [ opcode ] [  RA  ] [  RB  ]
```

| bits 14..12 | group |
| --- | --- |
| `000` | system instruction (IMM and FLOAT ignored) |
| `001` | integer ALU, register operand |
| `011` | float ALU, register operand |
| `101` | integer ALU, immediate operand (next word) |
| `111` | float ALU, immediate operand (next word) |

`DATA`, `RJMP`, `RJF`, `RJNF` and every immediate ALU instruction are
followed by one 32-bit literal word, so they take 2 words.

### 1.4 System instructions (`0x0nab`)

| op | mnemonic | effect |
| --- | --- | --- |
| 0 | `NOP` | nothing |
| 1 | `LD RA, RB` | `RB = mem[RA]` |
| 2 | `ST RA, RB` | `mem[RA] = RB` |
| 3 | `DATA RB, v` | `RB = v` (v is the next word) |
| 4 | `RJMP off` | `IAR = address_of_offset_word + off` |
| 5 | `RJF flags, off` | jump if **any** listed flag is on: `(F & mask) != 0` |
| 6 | `RJNF flags, off` | jump if **any** listed flag is off: `(F & mask) != mask` |
| 7 | `CLF` | clear all flags |
| 8 | `COMM mode, RB` | I/O, see 1.7 |
| 9 | `ADDR RB` | `RB = IAR` (address of the next instruction) |
| A | `JMRB RB` | `IAR = RB` (absolute jump) |
| B | `STK op, RB` | stack operation, see 1.6 |
| C | `ALD RA, RB` | `R0 = mem[RA + RB]` (array load) |
| D | `AST RA, RB` | `mem[RA + RB] = R0` (array store) |
| E | `CPY RA, RB` | `RB = RA` |
| F | `HALT` | stop until RESUME |

Jumps are **relative to the offset word itself**, not to the word after it.
The flag mask for `RJF`/`RJNF` sits in the RB field (`C=8 A=4 N=2 Z=1`).
Useful combinations: `RJF AZ` = "greater or equal", `RJF NZ` = "less or
equal". System instructions never touch the flags (except `CLF`).

### 1.5 ALU instructions

Every ALU instruction writes `R0` and rewrites all four flags. Two-operand
instructions compute `RA op RB` (or `RA op imm`). One-operand instructions use
`RB` only, but `RA` is still fed to the comparator, so the `A` flag compares
`R(RA field)` (normally `R0`) with `RB`.

| op | integer (`0x1…` / `0x5…`) | float (`0x3…` / `0x7…`) |
| --- | --- | --- |
| 0 | `ADD` | `FADD` |
| 1 | `SUB` (RA − RB) | `FSUB` |
| 2 | `MULT` (low 32 bits) | `FMULT` |
| 3 | `DIV` (signed, truncates) | `FDIV` |
| 4 | `SHL RB` | — (does nothing) |
| 5 | `SHR RB` (logical) | — (does nothing) |
| 6 | `NOT RB` | `FLOAT RB` (int → float) |
| 7 | `AND` | `INT RB` (float → int) |
| 8 | `OR` | undefined |
| 9 | `XOR` | undefined |
| A | `MOD` (sign of dividend) | undefined |
| B | `++ RB` / `INC` | — (does nothing) |
| C | `-- RB` / `DEC` | — (does nothing) |
| D | `NEG RB` | `FNEG RB` |
| E | `TEST RB` (`R0 = RB`) | undefined |
| F | `CMP RA, RB` | `FCMP RA, RB` |

`CMP` and `FCMP` write `0` to `R0`; only the flags carry the result.

**Integer flags**

| flag | meaning |
| --- | --- |
| `C` | carry out of the adder. `ADD`, `++`: unsigned overflow. `SUB`, `CMP`, `--`, `NEG`: set when there is **no** borrow. `SHL`: bit 31 shifted out. `SHR`: bit 0 shifted out. `MULT`: product does not fit in signed 32 bits. Everything else: 0 |
| `A` | `RA > RB`, signed |
| `N` | bit 31 of the result (for `CMP`, of `RA − RB`) |
| `Z` | result is 0 (for `CMP`, `RA == RB`) |

Division or modulo by zero returns the dividend unchanged.

**Float flags:** `C = 0`, `A = fa > fb`, `N = result < 0`, `Z = result == 0`.
For `FCMP` the "result" is `RA − RB` (rounded to float32), so `N` means
`RA < RB` and `Z` means equal, the same as the integer `CMP`.
`INT` truncates toward zero (`INT(1.7) = 1`, `INT(-3.7) = -3`, `INT(0.5) = 0`),
confirmed on the circuit. `FDIV` by zero gives ±infinity with the dividend's sign. `INT` of NaN or
infinity gives 0.

### 1.6 Stack instructions (`STK`, `0x0Bob`)

The sub-operation is in the RA field.

| RA | name | effect |
| --- | --- | --- |
| 0 | `PUSH` | `stack[ESP] = R0; ESP++` |
| 1 | `POP` | `ESP--; R0 = stack[ESP]` |
| 2 | `CALL` | `stack[ESP] = EBP; EBP = ESP; ESP++` (frame only, no jump) |
| 3 | `RET` | `ESP = EBP; EBP = stack[EBP]` (frame only, no jump) |
| 4 | `SET, RB` | `stack[EBP + RB] = R0` |
| 5 | `GET, RB` | `R0 = stack[EBP + RB]` |

The stack grows **upward** from RAM index 0. `SET`/`GET` are relative to
`EBP`; negative `RB` reaches arguments below the frame. On the circuit,
`EBP + RB` goes through the 17-bit address adder, so it wraps across the
**entire RAM**, not just the 16K stack area: with `EBP = 0`, index `-1`
reads or writes the last word of RAM (`0x1FFFF`). The simulator still wraps
this index at 14 bits, so it lands on `0x13FFF` instead (see section 8).

### 1.7 I/O (`COMM`, `0x08mb`)

The mode is in the low 2 bits of the RA field.

| mode | name | effect |
| --- | --- | --- |
| 0 | `INDATA` | `RB =` one word from the selected input device |
| 1 | `INADDR` | select input device number `RB` |
| 2 | `OUTDATA` | send `RB` to the selected output device |
| 3 | `OUTADDR` | select output device number `RB` |

The CPU gets no acknowledgement. Talking to an address with no device does
nothing; `INDATA` with no input device leaves `RB` unchanged.

| address | device | behaviour |
| --- | --- | --- |
| `0x5C` | text display (TTY) | prints the low 7 bits as ASCII; `0x0A` newline, `0x08` backspace |
| `0x3C` | number display | latches the 32-bit word and shows it on 8 hex digits (circuit only) |
| `0xF0` | keyboard | `INDATA` pops one key from the buffer; an empty buffer reads `0`; Enter = `0x0A`, Backspace = `0x08` |

Each device compares the 8 low bits of the selected address against its own
number with a gate decoder (the keyboard: bits 0–3 must be 0, bits 4–7 must
be 1).

---

## 2. The circuit (`logisim/CPU.circ`)

Built for **Logisim-evolution 4.1.0**. The top-level circuit is `PC`. The
design follows the classic "But How Do It Know?" CPU structure — a single
bus, a stepper, `ACC`/`TMP`, `MAR`, `IAR`, `IR`, and control lines named
`*_S` (set: latch from the bus) and `*_E` (enable: drive the bus) — widened to
32 bits and extended with a float unit, a hardware stack, array access and
16 registers.

### 2.1 Hierarchy

```
PC  (top level: the "computer")
├── CPU
│   ├── CONTROL_SECTION ── CLOCK ── buffer (delay line)
│   │                   └─ stepper
│   ├── CPU_REG ── 16 × REGISTER
│   ├── ALU ── FPU
│   ├── ACC
│   ├── TMP
│   ├── FLAG_REG
│   ├── IAR
│   └── INTRUCTION_REGISTER
├── RAM        (memory system: MAR, ROM, RAM, stack pointers)
├── display          → TTY
├── NUMBER_DISPLAY   → 8 × Hex Digit Display
├── KEYBOARD         ← Keyboard
└── buffer
```

`PC` also holds the `HALT`, `RESET` and `RESUME` input pins and the Logisim
`TTY`, `Keyboard` and `Hex Digit Display` components. It also has an
`RGB Video` component (565 colour) that is not wired to anything yet.

### 2.2 Subcircuits

**CPU** — wires the parts together around the 32-bit bus and holds the
Logisim `Clock` component. Exposes the bus to `PC` (to the `RAM` subcircuit
and the I/O devices) together with the control lines they need.

**CONTROL_SECTION** — the instruction decoder and sequencer, built from gates
(≈100 AND, ≈50 OR, decoders and demultiplexers). Inputs: the 16-bit `IR`,
the flags, `CLK`, `HALT`, `RESET`, `RESUME`, `BREAK`. It decodes the group
bits (3-to-8 demultiplexers), the opcode and the stepper count (4-to-16
decoders) and drives:

* set lines: `RAM_S`, `MAR`, `IAR`, `IR`, `ACC_S`, `TMP`, `FLAG`, `STACK_S`,
  `I_O_CLK_S`, and the register-file set lines
* enable lines: `RAM`, `ACC`, `IAR_E`, `STACK_E`, `ARR_E`, `I_O_CLK_E`,
  `bus_1`, and the register-file enable lines
* `STACK_OP` (4 bits) to the memory system
* the 6-bit ALU operation (4-bit opcode + group bits)
* `DATA_ADDRESS` and `INPUT_OUTPUT`, which tell the I/O devices what a `COMM`
  is doing
* two one-hot 16-bit register selects (register A side and register B side),
  plus the `R0` line that routes every ALU result into `R0`

**CLOCK** — turns the raw clock into the three phases the control section
needs: `clk`, `clk_s` (AND of the clock and a delayed copy: the short "set"
pulse) and `clk_e` (OR: the long "enable" window). The delay comes from the
`buffer` subcircuit, a chain of 60 buffers.

**stepper** — a 4-bit counter (steps 0–15) with two D flip-flops that
synchronise its reset; the control section restarts it at the end of every
instruction.

**CPU_REG** — 16 `REGISTER` subcircuits (each one a 32-bit register with a
controlled output buffer). Two 16-bit one-hot inputs choose which register
latches the bus and which one drives it.

**IAR** — a 17-bit counter made from 17 T flip-flops and gate logic, with
`enable` (drive the bus), `set` (load from the bus), `reset` and `clock`.
Incrementing happens inside the counter, so the ALU is not needed to step to
the next word.

**INTRUCTION_REGISTER** — a 16-bit register that latches the low 16 bits of
the bus.

**ACC / TMP** — 32-bit registers. `TMP` holds the ALU's B input; `ACC` holds
the ALU output until it is written to `R0`.

**FLAG_REG** — four 1-bit registers (`C A N Z`) with one shared set line.

**ALU** — inputs `A` and `B` (32 bits) and the 6-bit operation. Integer side:
32-bit adder, two subtractors, multiplier and divider (two's complement, the
divider also gives the remainder for `MOD`), negator, comparator (for the `A`
flag), bitwise gates, and a bit finder. Demultiplexers route the operands to
either the integer side or the `FPU`.

**FPU** — the float side. It contains a hand-built IEEE-754 datapath
(exponent compare, mantissa alignment with shifters, a 24-bit mantissa
multiplier, a 64-bit divider for the mantissa quotient, normalisation with
bit finders, sign logic) next to Logisim's built-in FP components
(`FPAdder`, `FPSubtractor`, `FPMultiplier`, `FPDivider`, `FPComparator`,
`IntToFP`, and `FPToInt` set to truncate). Labelled blocks: INT TO FLOAT,
FLOAT TO INT, NEGATE, SHIFT (0-left / 1-right), ADD/SUB, MULT/DIV, COMP.

**RAM** (the memory system, instantiated in `PC`):

* `MAR`, a 17-bit register; bit 16 selects the RAM or the ROM
* a 64K × 32 `RAM` and a 64K × 32 `ROM`. **The ROM component here is the one
  that holds the program** (`run_rom.py` writes into it)
* `ESP` and `EBP`, two 14-bit registers, with a 14-bit subtractor (`ESP − 1`)
* a 17-bit adder for `EBP + index` (stack `SET`/`GET`) and `RA + RB`
  (`ALD`/`AST`)
* a 4-to-16 demultiplexer that decodes `STACK_OP`
* the stack index is padded to 16 bits with two grounded bits, which is what
  places the stack in RAM `0x0000–0x3FFF`
* a "RAISE ERROR / TRIED WRITING IN ROM" output
* a 17-bit comparator against the constant `0x287` (a debugging watch on one
  address)

**display** — address decoder for `0x5C`, a 7-bit ASCII output and a write
strobe to the `TTY`. It also has a 4096 × 7 RAM addressed by a 12-bit counter.

**NUMBER_DISPLAY** — address decoder for `0x3C`, a 32-bit register, and a
splitter into 8 nibbles feeding 8 hex digit displays.

**KEYBOARD** — address decoder for `0xF0`, takes the 7-bit code from
Logisim's `Keyboard` and drives it onto the bus (zero-extended) through a
controlled buffer. A D flip-flop produces the read strobe that removes the key
from the Keyboard's buffer.

All three devices receive the bus, the `I_O_CLK_S`/`I_O_CLK_E` phases and the
`DATA_ADDRESS` / `INPUT_OUTPUT` lines ("CLOCK S", "CLK E", "D/A", "I/O" in the
schematics). Each device decodes the address sent by `OUTADDR`/`INADDR`,
remembers whether it is selected (a D flip-flop), and only reacts to
`OUTDATA`/`INDATA` while it is.

### 2.3 Running a program on the circuit

* **By hand:** open `CPU.circ` in Logisim-evolution, open the `RAM`
  subcircuit, right-click the ROM → Load Image → pick a `.rom` file. Start the
  clock in `PC`.
* **Headless:** `logisim/run_rom.py` (section 7.2).

---


## 3. The simulator (`cpu_sim/src/`)

A Python model of the ISA that runs one instruction per step (it does not
model clock cycles). Standard library only; the window uses `tkinter`. The
modules import each other by plain name, so run them as scripts
(`python cpu_sim/src/main.py`), not as a package.

### 3.1 Modules

| file | contents |
| --- | --- |
| `config.py` | sizes (`WORD_BITS`, `ADDR_BITS`, `RAM_BIT`, `BANK_WORDS`, `STACK_WORDS`), device addresses, and the **TWEAKS** switches (3.4) |
| `isa.py` | opcode tables, `decode(word) -> Instr`, `disassemble(word, operand)`. `Instr.takes_operand` says whether a literal word follows |
| `alu.py` | `int_op(name, a, b)` and `float_op(name, a, b)`, each returning `(R0 value, flag nibble)`; float32 ↔ bits helpers |
| `memory.py` | `Memory` with two 64K banks, `read`/`write` (ROM writes return `False`), stack helpers, and `parse_logisim` / `load_image` for v2.0 raw files |
| `devices.py` | `Display` (lines of text; `\n` new line, `\r` clears the line, `\b` deletes), `Keyboard` (a deque; empty reads 0), `DeviceBus` (the selected input and output addresses) |
| `cpu.py` | `CPU`: registers, IAR, flags, ESP/EBP, breakpoints, `step()`, `run()`, `reset()`, `resume()` |
| `gui.py` | the Tk window |
| `main.py` | command line, `build_cpu`, headless runner |
| `selftest.py` | 13 checks on the core |

### 3.2 Execution model

`CPU.step()`:

1. If halted or stopped, return `None`.
2. Fetch `mem[IAR]` and increment IAR (wrapping at 17 bits).
3. Decode. If the instruction takes an operand, fetch the next word too and
   remember its address (jumps are relative to it).
4. Execute and return a `Step(address, word, operand, text, note)` for the
   trace.

ALU instructions call `alu.int_op` or `alu.float_op` with `a = R[RA]` and
`b = R[RB]` or the immediate, then store `R0` and the flags. `HALT` sets
`halted`; `resume()` clears it and execution continues after the `HALT`.

### 3.3 Running it

```
python cpu_sim/src/main.py [rom] [--ram RAM_IMAGE] [--headless] [--steps N] [--trace] [--keys TEXT]
```

* without `--headless`: opens the window with the ROM loaded
* `--headless`: runs up to `--steps` instructions (default 100 000), then
  prints the state, the registers and the display
* `--trace`: prints every executed instruction (headless only)
* `--keys`: preloads the keyboard buffer (use `$'...\n'` in bash for Enter)

**The window:**

* left: load ROM/RAM, reset, step, run/pause, resume (after `HALT`), a speed
  dropdown (1 Hz … 1 MHz, or `max`), and a trace toggle. Below them: the 16
  registers, IAR, ESP, EBP, the flags as checkboxes, and a status block (bank,
  selected devices, instruction count, measured rate, run state)
* middle: ROM and RAM tabs, 256 words per page, with optional disassembly and
  "follow IAR"
* right: the display (`0x5C`), the keyboard field (`0xF0`), and the last
  executed instructions

Editing: type into any register/IAR/ESP/EBP box and press Enter, click the
flags, or double-click a memory word. Values accept `0x1F`, `31`, `-5`,
`0b1010`, and `1.5` / `1.5f` (stored as float32 bits). Right-click a memory
word to toggle a breakpoint; a running CPU stops *before* executing that
address. `clear bp` removes them all.

The keyboard field is read-only: every key goes straight into the buffer
(Enter as `0x0A`, Backspace as `0x08`, other printable ASCII as itself).
Pasting types the clipboard one key at a time. The field shows the keys still
waiting to be read.

Speed control: a 20 ms Tk timer runs `hz × elapsed` instructions per tick,
at most 50 000 per tick so the window stays responsive. Trace logging is
skipped when more than 200 instructions run in one tick.

### 3.4 Configurable behaviour (`config.py` TWEAKS)

| switch | default | status on the circuit |
| --- | --- | --- |
| `A_FLAG_SIGNED` | `True`: `A` compares signed | confirmed |
| `SHR_ARITHMETIC` | `False`: `SHR` is logical, the top bit fills with 0 | confirmed |
| `DIV_TRUNCATE` | `True`: `DIV` truncates toward zero, `MOD` keeps the dividend's sign (`-7 MOD 3 = -1`) | confirmed |
| `STOP_ON_STACK_WRAP` | `False`: ESP/EBP wrap at 14 bits | wrapping confirmed; `True` stops the simulated CPU instead, to catch a runaway stack while debugging |
| `FLOAT_NOP_RESULT` | `0`: written to `R0` by float `SHL/SHR/++/--` and the undefined float opcodes | still a guess |

---

## 4. The assembler and linker (`compiler/src/asm/`)

The full language reference is in
[`compiler/assembly_syntax.md`](compiler/assembly_syntax.md). This section
explains how the tools work.

### 4.1 Command line

```
python compiler/src/asm assemble prog.asm            [-o prog.obj]
python compiler/src/asm link     prog.obj lib.obj    [-o prog.rom] [--map]
python compiler/src/asm build    prog.asm lib.asm    [-o prog.rom] [--map]
```

`build` accepts `.asm` and `.obj` files mixed; `link` takes only `.obj` (and
suggests `build` when given something else). The default output name is the
first input with `.rom`. `--map` also writes a `.map` file with every label's
final address:

```
# labels in t.rom
# address  section  label                     file
00000      rom      (entry: RJMP start)
00002      rom      start                     compiler/examples/two_files/main.asm  (global)
0001d      rom      print_newline             compiler/examples/two_files/lib.asm  (global)
...
14000      ram      dashes                    compiler/examples/two_files/main.asm
```

Every input is processed even after a failure, so one run reports the
problems of all files (bad source, unreadable file, broken `.obj`), as
`file:line: message`. Nothing is written if there is any error.

### 4.2 Modules

| file | role |
| --- | --- |
| `__main__.py` | the command line above |
| `parser.py` | splits text only: comments, labels, mnemonics, operand splitting (aware of quotes), registers, strings with escapes, and value expressions (`Expr`: numbers and names joined by `+`/`-`; float literals become float32 bits) |
| `encoding.py` | the ISA as tables: `SYSTEM_OPS`, `ALU_OPS`, `COMM_OPS`, `STK_OPS`, `FLAGS`, operand shapes, `word()`, `jump_offset()`, `sys_word()`, `stk_word()` |
| `assembler.py` | the two-pass assembler, one file → one `ObjectFile` |
| `objfile.py` | `ObjectFile` and `Reloc`, saved as readable JSON |
| `linker.py` | object files → one ROM image, plus `format_raw` and `format_map` |
| `errors.py` | `AsmError` (one message with file and line) and `AsmErrors` (a batch) |
| `selftest.py` | 18 checks for the assembler and linker |
| `asm_grammar.py` | writes railroad diagrams of the grammar to `asm_grammar.html` (needs `pip install railroad-diagrams`) |

### 4.3 Assembling (two passes)

**Pass 1** reads each line, defines labels at the current offset of the
current section (`.rom` or `.ram`), records `.equ` constants and the
`.global` and `.extern` names, and works out each statement's size:

| statement | size in words |
| --- | --- |
| system instructions | 1, or 2 for `DATA`/`RJMP`/`RJF`/`RJNF` |
| ALU | 1, or 2 with `#immediate` |
| `.word a, b, …` | one per value |
| `.string "…"` | one per character + a 0 |
| `.space n` | n (zeros in ROM; only reserves room in RAM) |
| `CALL t` / `CALL t, n` | 7 / 9 + n |
| `RET` | 6 |
| `SAVE r…` | 2 per register |
| `RESTORE r…` | 2 per register, +2 unless `R0` is listed |

Because sizes are fixed in pass 1, any count (`.space`, `CALL`'s `n`) must be
a number or a constant defined **above** it.

Then `check_symbols` checks `.global`/`.extern`: each global must be defined
in the file, no name can be both, and constants can't be either.

**Pass 2** encodes each statement. Known values become words directly. A
value that contains a label becomes a 0 word plus a relocation:

* `abs`: the word must hold a label's final address (from `DATA`, `.word`,
  immediates, `CALL`). A `CALL` target is also marked `rom_only`, so the
  linker rejects calling a RAM label from another file
* `rel`: a jump offset to a label in **another** file

Jumps to labels in the same file are resolved immediately, since the distance
does not change when the file moves.

Checks include: unknown names, labels used as constants, more than one label
in an expression, subtracting a label, values that don't fit in 32 bits,
jumping to or calling a RAM label, code or data in `.ram`, reserved names
(`__x`, register names, mnemonics), duplicate registers in `SAVE`/`RESTORE`.
Warnings (not errors): a float literal in an integer immediate, and a whole
number in a float immediate (`FADD R1, #3` adds the bits `0x3`, not 3.0).

### 4.4 Pseudo-instructions

```
CALL target[, n]                RET
  DATA R0, <after>                CPY  R0, R15     ; keep return value
  STK  PUSH        ; return addr  STK  RET         ; drop frame
  STK  CALL        ; new frame    STK  POP         ; R0 = return address
  DATA R0, target                 CPY  R0, R14
  JMRB R0                         CPY  R15, R0     ; R0 = return value
<after>:                          JMRB R14
  ; only when n > 0:
  CPY R0, R15
  STK POP          ; × n
  CPY R15, R0

SAVE Ra, Rb                     RESTORE Ra, Rb
  CPY Ra, R0 / STK PUSH           CPY R0, R15                 ; keep R0
  CPY Rb, R0 / STK PUSH           STK POP / CPY R0, Rb
                                  STK POP / CPY R0, Ra
                                  CPY R15, R0
```

`CALL` changes `R0` (and `R15` when `n > 0`), `RET` changes `R14` and `R15`.
None of them touch the flags.

### 4.5 Object files (`.obj`)

JSON, written by hand so it stays readable. Here is
`compiler/examples/two_files/main.asm` assembled on its own (words the linker
fills in hold 0):

```json
{
 "format": "cpu-asm object v1",
 "source": "main.asm",
 "rom": [
  "300 0 b00 b20 300 0 a00 303",
  "0 230 302 5c 832 301 6f 821",
  ...
 ],
 "ram_size": 1,
 "labels": {
  "dashes": ["ram", 0],
  "start": ["rom", 0]
 },
 "globals": ["start"],
 "externs": ["print_dashes", "print_newline"],
 "relocs": [
  {"at": 1, "kind": "abs", "section": "rom", "addend": 7, "line": 13},
  {"at": 5, "kind": "abs", "symbol": "print_dashes", "addend": 0, "line": 13, "rom_only": true},
  {"at": 8, "kind": "abs", "section": "ram", "addend": 0, "line": 14},
  ...
 ]
}
```

A relocation names either a `symbol` (another file's global) or a `section`
(a label in this file, with its offset in `addend`). `rom_only` is written
only when true, so older object files still load.

### 4.6 Linking

```
ROM  0x00000   RJMP start           (2 words, added by the linker)
     0x00002   each file's ROM part, in command-line order
RAM  0x10000   stack (never touched by the linker)
     0x14000   each file's RAM part, in command-line order
```

1. Give each file a base in ROM and RAM, and check that the sizes fit.
2. Compute every label's final address and build the table of `.global`s
   (the same global in two files is an error).
3. Write the entry jump to `start`. Exactly one file must have
   `.global start`, and it must be a ROM label.
4. Copy each file's words and fill in the relocations (`abs`: the address;
   `rel`: `target − address of the offset word`). Jumping to or calling a
   RAM label is an error; taking a RAM label's address is fine.
5. Check that every `.extern` is exported by some file, even when it is
   never used (a missing file or a typo).

The output is a v2.0 raw image (section 6).

---

## 5. Calling convention and the standard library

### 5.1 Calling convention

`stdlib.asm` follows this convention, but nothing in the tools enforces it:

* push the arguments in order (first argument first), then `CALL name, N`
* the result comes back in `R0`
* `R0`, `R14`, `R15` are always clobbered by a call; `R1`–`R13` may be
  changed by the callee, so the caller saves what it needs with
  `SAVE`/`RESTORE`
* inside a function with N arguments, read them with `STK GET` and a negative
  index: the first argument is at `EBP − (N+1)`, the last at `EBP − 2`

The stack frame after `CALL` (the stack grows upward):

```
index            contents
EBP − (N+1)      argument 1
 …               …
EBP − 2          argument N
EBP − 1          return address      (pushed by CALL's STK PUSH)
EBP + 0          caller's EBP        (written by STK CALL)
ESP = EBP + 1    next free slot
```

A typical function start:

```asm
print_char:
        DATA R1, -2
        STK GET, R1          ; R0 = c (the only argument)
        ...
        RET
```

### 5.2 `stdlib.asm` (`compiler/examples/stdlib/`)

Build it together with the program, and declare the functions the program
uses with `.extern`:

```
python compiler/src/asm build prog.asm compiler/examples/stdlib/stdlib.asm -o prog.rom
```

| group | functions |
| --- | --- |
| output | `print_char(c)`, `print_string(addr)`, `print_int(n)`, `print_newline()`, `print_float(f)` (4 decimals), `print_hex(v)` (`0x` + 8 digits) |
| input | `read_char()` (waits for a key, **no echo**), `read_line(buf, max)` (echoes, handles backspace, keeps max−1 chars, returns the length), `read_int()`, `read_float()` |
| strings | `str_len(addr)`, `str_copy(dst, src)` (returns the length), `str_eq(a, b)` (1/0) |
| memory | `mem_copy(dst, src, n)`, `mem_set(dst, value, n)` |
| int math | `abs(n)`, `min(a, b)`, `max(a, b)`, `pow(base, exp)` (exp < 0 gives 0) |
| float math | `fabs(f)`, `fmin(a, b)`, `fmax(a, b)` |
| conversion | `int_to_str(n, buf)` (buf: 12 words, returns the length), `str_to_int(addr)` |

Strings end with a 0 word and hold one character per word. The library
uses two RAM buffers: `num_buf` (12 words) and `in_buf` (32 words).
`floor_pos` is a private helper for `print_float`: the whole part of a
float ≥ 0, which is `INT` truncating. In `read_line`, backspace removes the last
character from both the buffer and the display, and does nothing when the
line is empty (so it can't erase the prompt).

### 5.3 Example programs (`compiler/examples/`)

| path | what it shows |
| --- | --- |
| `programs/hello.asm` | prints a `.string` from ROM with `ALD` (`hello, world`) |
| `programs/print_a-z.asm` | the alphabet with a `CMP`/`RJNF` loop |
| `programs/count_0-9.asm` | digits with an immediate `ADD` |
| `programs/sum_1-10.asm` | a loop plus `DIV`/`MOD` to print `55` |
| `programs/abs_value.asm` | `TEST`, `RJNF N`, `NEG` (prints `5`) |
| `programs/stack_reverse.asm` | `STK PUSH`/`POP` to reverse a word (`kcats`) |
| `programs/echo.asm` | keyboard → display until Enter (backspace is echoed too) |
| `stdlib/stdlib_demo.asm` | every stdlib function except input; the expected output is in its header |
| `stdlib/stdlib_input_demo.asm` | `read_line`, `read_int`, `read_float`, `read_char` |
| `two_files/main.asm`, `lib.asm` | two files, `.extern`/`.global`, `CALL` inside a call, a RAM variable |
| `tests/io_test.asm` | minimal keyboard → display loop for probing the circuit |
| `tests/diag10.asm` | `INT` on floats below 1 (diagnostic, resolved: they give 0) |
| `tests/diag11.asm` | measures `STK SET/GET` with a negative index while `EBP = 0` (on the circuit it reaches the last word of RAM), checks that `STK GET` leaves `RB` alone, and `INT` for positive and negative values (it truncates). Link it **first** (with the stdlib) so its 16 results sit in RAM from `0x14000`; they are also printed in hex |

All of these build and run correctly in the simulator. Built images go in
`compiler/rom/`, which git ignores. Rebuild them after changing a source
or the stdlib; an image there can be older than its source.

---

## 6. ROM image format

Logisim's `v2.0 raw`, used by the linker, the simulator and `run_rom.py`:

```
v2.0 raw
400 1 302 5c 832 301 61 821
1b01 e01 5f10 7b 601 fffffffa f00
```

* the first line is `v2.0 raw`, then hex words separated by whitespace,
  starting at word 0
* `count*value` repeats a value (the linker uses it for runs of 4 or more)
* the simulator also accepts `#` comments (used by the hand-written ROMs in
  `cpu_sim/examples/`)

---

## 7. Tooling

### 7.1 `run.py`

One entry point at the project root. With no arguments it shows a menu and
lets you pick files from the project (it skips `.git`, `.venv`,
`__pycache__`). With arguments:

| command | does |
| --- | --- |
| `python run.py asm <files…> [-o out.rom]` | `compiler/src/asm build …` |
| `python run.py sim [rom]` | `cpu_sim/src/main.py [rom]` (the window) |
| `python run.py build <files…> -o out.rom` | assembles, then opens the result in the simulator |
| `python run.py test` | runs both self-checks |

It checks for `tkinter` before opening the window and prints install hints
when it is missing. In the menu, the output of `asm`/`build` is the first
source file with `.rom`.

### 7.2 `logisim/run_rom.py`

Runs a ROM on the **real circuit** without the GUI:

```
python logisim/run_rom.py logisim/CPU.circ prog.rom [--jar logisim-evolution-4.1.0-all.jar]
                          [--seconds 120] [--circuit PC] [--keep patched.circ]
python logisim/run_rom.py logisim/CPU.circ --dump-rom current.rom
```

It parses the `.circ` XML and finds the single `ROM` component inside the
`RAM` subcircuit. It replaces that ROM's contents with the image
(`addr/data: 16 32` header, 8 words per line) and writes
`CPU__patched.circ` to the current directory (or to `--keep`). Then it runs
`java -Djava.awt.headless=true -jar <jar> <patched> --toplevel-circuit PC -t tty,halt`
and prints the TTY output until `HALT` or the timeout. `--dump-rom` instead
writes out the ROM currently stored in the circuit. The jar is not in the
repo.

### 7.3 Self-checks

```
python compiler/src/asm/selftest.py   # 18 checks: encodings, values, strings, jumps,
                                      # CALL/RET, SAVE/RESTORE, linking, link errors
                                      # (RAM calls, unexported externs), warnings,
                                      # raw output, .obj round trip, CLI, examples
python cpu_sim/src/selftest.py        # 13 checks: immediates, flags, DIV by 0, RAM,
                                      # ROM writes, stack, frames, floats, FCMP flags,
                                      # keyboard, backspace, ADDR/JMRB
```

---

## 8. Simulator vs. circuit: open questions

The simulator is the reference for the tools, but it was written from the
ISA, not generated from the circuit. Where they disagree, the circuit wins.

| topic | simulator | circuit |
| --- | --- | --- |
| `A` signed, `SHR` logical, `DIV`/`MOD` truncate, stack wraps | as in 3.4 | confirmed (2026-10-02) |
| `INT` (float → int) | truncates toward zero | confirmed: truncates (`diag10.asm`, `diag11.asm`) |
| `STK SET/GET` with a negative index at `EBP = 0` | wraps at 14 bits, to the top of the stack area (`0x13FFF`) | **differs**: wraps across the entire RAM, to the last word (`0x1FFFF`), measured with `diag11.asm` |
| does `STK GET` also write `RB`? | no | no: fixed in the circuit (STK GET/SET/PUSH no longer misuse RB) |
| float `SHL/SHR/++/--`, undefined float opcodes | write 0 (`FLOAT_NOP_RESULT`) | a guess |
| `SUB` carry (set when there is no borrow), `MULT` overflow carry, float divide by zero | as in 1.5 | not verified |
| number display `0x3C` | not modelled (writes are ignored) | 8 hex digits in `PC` |
| timing | one instruction per step | several clock cycles per instruction (stepper) |

---

## 9. Outdated files and stale information

These are still in the repo but are **not** current. When something here
disagrees with sections 1–8, sections 1–8 are right.

### Paths left over from the move to `compiler/examples/` and `cpu_sim/src/`

| where | what is stale |
| --- | --- |
| headers of `compiler/examples/programs/*.asm`, `tests/diag11.asm`, and the BUILD note in `stdlib/stdlib.asm` | say `compiler/src/asm/examples/…`; the files are now in `compiler/examples/…` |
| `compiler/src/asm/selftest.py` `check_examples_build` | looks for `compiler/src/asm/examples`, which is gone, so it is **always skipped** (it reports "skipped, no examples folder"). Its target should be `compiler/examples` |
| `run.py` `find_roms` | adds files from `cpu_sim/src/examples`, which does not exist; the hand-written ROMs in `cpu_sim/examples/` have no `.rom` extension, so the menu doesn't list them |
| `cpu_sim/src/main.py` docstring | `python main.py print_a-z_fixed`: assumes you run it from inside the examples folder |
| `compiler/src/asm/__main__.py` and `selftest.py` docstrings, `compiler/examples/two_files/main.asm` header | use the even older `python src/asm …` / `examples/asm/…` paths |
| `compiler/assembly_syntax.md`, section 10 | same older paths (`python src/asm`, `python src/main.py`, `examples/asm/…`). The real ones are `python compiler/src/asm …` and `python cpu_sim/src/main.py …` |
| headers of `stdlib_demo.asm`, `stdlib_input_demo.asm`, `diag10.asm`, `io_test.asm` | relative build commands that only work from inside their own folder |

### Documentation

| file | what is outdated |
| --- | --- |
| `compiler/src/asm/assembly_syntax.md` | an older copy of `compiler/assembly_syntax.md`, missing `CALL target, n` and `SAVE`/`RESTORE`. Use `compiler/assembly_syntax.md` |
| `compiler/assembly_syntax.md`, section 4 | lists `STK SET/GET` as `stack[RB]`; they are `stack[EBP + RB]` |
| `logisim/cpu datas/instruction` | marked "up to date", but says `ADD/SUB/MULT/DIV` store in `RB` (they store in `R0`), lists float `SHL/SHR/++/--` as real operations, and calls the `DATA` literal a "byte" |
| `logisim/functions/isa_encoding_reference.md` | an early reverse-engineering note: the "result into RB" rule, guessed flag meanings, no stack/array/float details |
| `logisim/cpu datas/stack_instruction.txt` | internal micro-step notes for the stack hardware, not a description of the instructions |
| `logisim/cpu datas/fixes_circuit.txt` | empty |
| `logisim/cpu datas/TO DO.txt` | personal to-do list (future ideas: loading ROM into RAM at start, BIOS, OS) |
| `asm_grammar.py` | its docstring and footer refer to `02-assembly-language.md`, which does not exist |
| `diag11.asm` header, result 1 | expects the `ebp-1` write to land on `0x13FFF` (its "truncating / as ISA" column); on the circuit it lands on `0x1FFFF`, the last word of RAM |

### Programs and images

| file | status |
| --- | --- |
| `cpu_sim/examples/*` | hand-assembled ROMs, replaced by `compiler/examples/programs/*.asm`. `echo` still selects the keyboard at `0x0F` (now `0xF0`), so it waits forever; `print_a-z` uses `++ R1` expecting the result in `R1` and prints `a` forever (`print_a-z_fixed` works); `abs_value` sends the raw number 5 to the text display, which prints nothing visible |
| `logisim/functions/*` | hand-assembled for the early ISA (results into `RB`, old stack layout); most give wrong results now |
| `compiler/rom/stdlib.rom` (local, ignored by git) | not a build of `stdlib.asm` (the library has no `start` and can't be linked alone); it is an old build of the input demo |
| `compiler/rom/*` (local, ignored by git) | only `io_test.rom` and `print_a-z.rom` match a fresh build; every image linked with the stdlib is older than the current `stdlib.asm`. `lib.rom` is the two-file example, named after its first input |

### Circuit

| item | status |
| --- | --- |
| subcircuits `ROM`, `program_loader`, `sign_controller`, `teste` | not used anywhere. `ROM` is an older memory block (the program now lives in the ROM inside `RAM`); `teste` is the FPU prototype, with π and e as test constants |
| comparator against `0x287` in `RAM` | a debugging watch on one address, not part of the design |
