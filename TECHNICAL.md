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
10. [The C compiler (`compiler/src/cc/`) and the C library (`compiler/libc/`)](#10-the-c-compiler-compilersrccc-and-the-c-library-compilerlibc)
11. [The OS (`os/`)](#11-the-os-os)

---

## 1. Instruction set

### 1.1 Machine state

| item | size | notes |
| --- | --- | --- |
| `R0`–`R15` | 32 bits each | general purpose; every ALU result is written to `R0` |
| `IAR` | 25 bits | instruction address register (program counter) |
| `IR` | 16 bits | instruction register (low 16 bits of the fetched word) |
| flags | 4 bits | `C A N Z` (bit 3 … bit 0) |
| `ESP`, `EBP` | 14 bits each | stack pointer and frame pointer, indices into the stack area |
| `MAR` | 25 bits | memory address register (inside the `RAM` subcircuit) |
| `ACC`, `TMP` | 32 bits each | internal ALU latches, not visible to programs |

### 1.2 Memory map

One 25-bit address bus. Each bank has a 24-bit address (16M words); bit 24
chooses the bank:

```
0x0000000 ─ 0x0FFFFFF   ROM  16M × 32   program and constant data, read only
0x1000000 ─ 0x1003FFF   RAM  stack area (16K words, indexed by ESP/EBP)
0x1004000 ─ 0x1FFFFFF   RAM  free; the linker puts .ram data here
0x1100000 ─ 0x1FFFFFF   RAM  (by convention) where spawnv() loads programs for the OS
```

**The circuit is still the 16-bit version** (17-bit bus, bit 16 = RAM, 64K
words per bank: ROM `0x00000–0x0FFFF`, RAM `0x10000–0x1FFFF`). The toolchain
and the simulator use the 24-bit map above; 2.4 lists what the circuit needs
before it can run these programs, and `logisim/run_rom.py` refuses until then.

* Reads work on both banks. Writes to ROM are dropped (the circuit raises a
  "tried writing in ROM" error line; the simulator ignores the write and notes
  it in the trace).
* The stack is the first 16K words of RAM (`RAM[0x0000..0x3FFF]`). `ESP`
  and `EBP` are 14-bit indices into it, so they wrap at 16K. `STK SET/GET`
  addresses are not limited to the stack area: they wrap across the whole
  RAM (see 1.6).
* The IAR is 25 bits, so the CPU *can* fetch from RAM. The linker puts code
  there only for a program for the OS (`cc build --exe`, 4.6 and 10.4),
  which `spawnv()` loads from the disk at `0x1100000`.

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

`NOT` on the circuit inverted `RA` instead of `RB` (measured with
`diag16.asm`/`diag17.asm`) until it was rewired to `RB` on 2026-10-15
(`diag17.asm` again). The assembler still writes `NOT Rx` with `x` in both
fields (`0x16xx`), which gives `~Rx` either way, with `A` = 0.

| op | integer (`0x1…` / `0x5…`) | float (`0x3…` / `0x7…`) |
| --- | --- | --- |
| 0 | `ADD` | `FADD` |
| 1 | `SUB` (RA − RB) | `FSUB` |
| 2 | `MULT` (low 32 bits) | `FMULT` |
| 3 | `DIV` (signed, truncates) | `FDIV` |
| 4 | `SHL RB` | no mnemonic: writes `RB × 2` (measured) |
| 5 | `SHR RB` (logical) | no defined result (see below) |
| 6 | `NOT RB` | `FLOAT RB` (int → float) |
| 7 | `AND` | `INT RB` (float → int) |
| 8 | `OR` | undefined: writes 0 (measured) |
| 9 | `XOR` | undefined: writes 0 (measured) |
| A | `MOD` (sign of dividend) | undefined: writes 0 (measured) |
| B | `++ RB` / `INC` | no defined result (see below) |
| C | `-- RB` / `DEC` | no defined result (see below) |
| D | `NEG RB` | `FNEG RB` |
| E | `TEST RB` (`R0 = RB`) | undefined: writes 0 (measured) |
| F | `CMP RA, RB` | `FCMP RA, RB` |

Float opcodes 5, B and C read back as `0xFFFFFFFF` on the circuit with `N` and
`Z` both on, which looks like an undriven bus; the simulator writes 0 for
them instead (`FLOAT_NOP_RESULT`).

`CMP` and `FCMP` write `0` to `R0`; only the flags carry the result.

**Integer flags**

| flag | meaning |
| --- | --- |
| `C` | `ADD`, `++`: carry out (unsigned overflow). `SUB`: **borrow**, set when `RA < RB` unsigned. `SHL`: bit 31 shifted out. `SHR`: bit 0 shifted out. Everything else, including `CMP`, `--`, `NEG` and `MULT`: 0. Measured on the circuit with `diag12.asm` and `diag13.asm` |
| `A` | `RA > RB`, signed |
| `N` | bit 31 of the result (for `CMP`, of `RA − RB`) |
| `Z` | result is 0 (for `CMP`, `RA == RB`) |

Division by zero returns the dividend unchanged; modulo by zero returns 0.
`0x80000000 DIV -1` gives `0x80000000` and `MOD` gives 0 (all measured with
`diag16.asm`/`diag17.asm`).

**Float flags:** `C = 0`, `A = fa > fb`, `N = result < 0`, `Z = result == 0`.
For `FCMP` the "result" is `RA − RB` (rounded to float32), so `N` means
`RA < RB` and `Z` means equal, the same as the integer `CMP`. Results round to
nearest, ties to even (measured with `diag16.asm`: `1 + 2^-24 = 1.0`,
`1/3 = 0x3EAAAAAB`).
`INT` truncates toward zero (`INT(1.7) = 1`, `INT(-3.7) = -3`, `INT(0.5) = 0`),
confirmed on the circuit. Measured with `diag14.asm`/`diag15.asm`:

* the float unit follows IEEE-754: `x / 0` is infinity with the sign of `x`
  XOR the zero's sign (`1.0 / -0.0 = -inf`), `0/0`, `inf - inf`, `inf * 0`
  and anything with a NaN give NaN (`0x7FC00000`); subnormals are kept
* `INT` works like Java's `(long)` cast followed by keeping the low 32 bits:
  out-of-range values wrap (`INT(3e9) = 0xB2D05E00`), values at or above
  2^63 and +infinity give `0xFFFFFFFF`, at or below -2^63 and -infinity
  give 0, NaN gives 0
* `FCMP` with a NaN clears every flag, so `<`, `<=`, `==` with a NaN are all
  false when tested on N and Z

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
`EBP`; negative `RB` reaches arguments below the frame. `EBP + RB` wraps at
the RAM's address width, across the **entire RAM**, not just the 16K stack
area: with `EBP = 0`, index `-1` reads or writes the last word of RAM
(`0x1FFFFFF`) and index `0x8000` reaches `0x1008000`; bits of `RB` above 23
are dropped. Measured on the 16-bit circuit with `diag11.asm` and
`diag16.asm` (there it wraps at 16 bits: `-1` reaches `0x1FFFF`); the
simulator wraps at 24, taking the circuit's adder to grow with the RAM.

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
| `0x5C` | text display (TTY) | prints the low 7 bits as ASCII; `0x0A` newline, `0x08` backspace, `0x0C` (form feed) clears it (Logisim's `TTY` does this; read in its code, not run on the circuit) |
| `0x3C` | number display | latches the 32-bit word and shows it on 8 hex digits (the simulator shows it in the window, and as `HEX DISPLAY:` in headless output) |
| `0xF0` | keyboard | `INDATA` pops one key from the buffer; an empty buffer reads `0`; Enter = `0x0A`, Backspace = `0x08`, printable ASCII as itself; simulator only so far: arrows up/down/left/right = 28/29/30/31, Ctrl-A … Ctrl-Z = 1 … 26 (Ctrl-D = 4; Ctrl-H, Ctrl-J, Ctrl-M are Backspace and Enter; Ctrl-C and Ctrl-V stay with the window) |
| `0x6C` | RGB screen | one pixel per word: x in bits 31–24, y in bits 23–16, RGB565 colour in bits 15–0; on the 128×128 RGB Video only the low 7 bits of x and y are wired. Write-only |
| `0x6D` | RGB screen clear (*simulator only*) | any word pulses the RGB Video's reset: all black. Not built on the circuit yet, where it does nothing |
| `0x7C` | timer (*planned*) | `INDATA` reads the milliseconds since reset, wrapping at 32 bits; C's `clock()` |
| `0x8C` | disk seek (*simulator only*) | `OUTDATA` sets the disk's word position; `INDATA` reads the disk's size in words |
| `0x8D` | disk data (*simulator only*) | `OUTDATA` writes the word at the position, `INDATA` reads it; both move the position on by one. Past the end, reads give 0 and writes are dropped |

`0x6C`/`0x6D` were chosen on 2026-10-11; `0x6C` was built on the circuit
(`RGB_Display`, section 2.2) on 2026-10-22. The numbers are `VIDEO_*` in
`config.py` and `GFX_*` in `gfx.h`.

The timer (`0x7C`, 2026-10-22) isn't on the circuit at all yet. The
simulator follows the computer's real clock, so a program that waits on it
runs at the right speed however fast it is simulated; the window stops it
while the simulation is paused (and while single-stepping). On the circuit
it would be a 32-bit counter stepped every millisecond, so its input clock
has to come from a divider matched to the CPU's clock rate.

The disk (`0x8C`/`0x8D`, 2026-10-27) exists only in the simulator, because
Logisim's RAM can't keep its contents in a file. It is attached with
`--disk FILE` (3.3) or the window's `disk` button; without one, both
addresses are empty (`INDATA` leaves the register alone, so C's
`device_in` reads 0). The file is binary, 4 bytes per word, little-endian,
mapped into memory (`mmap`), so every write reaches the file and a big disk
only takes the space actually written: a missing file is created as a
sparse 64 MB file (16M words, `DISK_WORDS`), an existing one keeps its size
(at most 1G words, 4 GB). One position serves both reads and writes, and
moving it on after every word makes block copies a loop of `INDATA`s or
`OUTDATA`s. A reset rewinds it to 0 and keeps the disk. The filesystem on
the disk (TFS1) and the tool that makes images are in 7.6.

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
├── RGB_Display      → RGB Video
└── buffer
```

`PC` also holds the `HALT`, `RESET` and `RESUME` input pins and the Logisim
`TTY`, `Keyboard` and `Hex Digit Display` components. It also has an
`RGB Video` component (565 colour, fed by `RGB_Display`). The
output pin labelled `halt` goes high when the CPU halts; headless runs use it
to stop (section 7.2), so keep its label.

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

**RGB_Display** — address decoder for `0x6C` and the same select flip-flop
and write strobe as `display`. Splitters take the colour from bus bits 15–0,
y from bits 22–16 and x from bits 30–24; they and the strobe (on the clock
input) go to the `RGB Video` in `PC`. The Video's write-enable input is tied
to a constant 1 there: left unconnected, nothing is drawn. There is no clear
(`0x6D`) yet.

All four devices receive the bus, the `I_O_CLK_S`/`I_O_CLK_E` phases and the
`DATA_ADDRESS` / `INPUT_OUTPUT` lines ("CLOCK S", "CLK E", "D/A", "I/O" in the
schematics). Each device decodes the address sent by `OUTADDR`/`INADDR`,
remembers whether it is selected (a D flip-flop), and only reacts to
`OUTDATA`/`INDATA` while it is.

### 2.3 Running a program on the circuit

* **By hand:** open `CPU.circ` in Logisim-evolution, open the `RAM`
  subcircuit, right-click the ROM → Load Image → pick a `.rom` file. Start the
  clock in `PC`.
* **Headless:** `logisim/run_rom.py` (section 7.2).

### 2.4 Widening the circuit to 24-bit banks (not done yet)

The toolchain and the simulator use 24-bit banks (1.2); the circuit is still
16-bit, so programs built now can't run on it. These are the parts that carry
an address (found by width in `CPU.circ`; the 16-bit parts of
`CONTROL_SECTION`, `CPU_REG` and `INTRUCTION_REGISTER` are the instruction,
not an address, and stay):

| subcircuit | part | now | needed |
| --- | --- | --- | --- |
| `IAR` | the counter: 17 T flip-flops with their carry gates, and its two 17-bit splitters (bus in, bus out) | 17 bits | 25: eight more bit cells |
| `RAM` | `MAR` register and the splitters that take its bank bit | 17 bits, bit 16 = RAM | 25 bits, bit 24 = RAM |
| `RAM` | the `RAM` and `ROM` components | 16 address bits | 24 (Logisim's largest) |
| `RAM` | the adder for `EBP + index` and `RA + RB`, and the 17-bit controlled buffers around it | 17 bits | 25 |
| `RAM` | the 16-bit splitters and buffers that feed the memories' addresses | 16 bits | 24 |
| `RAM` | the stack index padding (14-bit `ESP`/`EBP` + grounded bits) | 2 grounded bits | 10, so the stack stays at RAM `0x0000–0x3FFF` |
| `RAM` | the debugging comparator against `0x287` | 17 bits | 25, or remove it (9) |

`ESP`/`EBP` (14 bits) and the 32-bit data paths don't change. Once the ROM
has 24 address bits, `run_rom.py` runs programs again (it writes the
matching `addr/data` header itself). Relative jumps need nothing new: the
offset is added in 32 bits and the IAR keeps its low 25.

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
| `memory.py` | `Memory` with two 16M-word banks (Python lists, 128 MB each), `read`/`write` (ROM writes return `False`), stack helpers, and `parse_logisim` / `load_image` for v2.0 raw files |
| `devices.py` | `Display` (lines of text; `\n` new line, `\r` back to the start of the line (what follows overwrites it), `\b` deletes, `\f` clears it all, so headless output shows only what came after the last `\f`), `Keyboard` (a deque; empty reads 0), `Timer` (milliseconds since reset at `0x7C`, from the computer's clock; `pause()`/`resume()`, which the window calls), `Video` (128×128 RGB565 pixels from `0x6C`, cleared by `0x6D`; `png()` for `--screen`), `Disk` (`0x8C`/`0x8D`, a file mapped with `mmap`), `DeviceBus` (`attach_disk(path)`; (the selected input and output addresses, and `hex_value`, the last word sent to the hex display) |
| `cpu.py` | `CPU`: registers, IAR, flags, ESP/EBP, breakpoints, `step()`, `run()`, `reset()`, `resume()` |
| `gui.py` | the Tk window |
| `debuginfo.py` | reads a `.map` (labels, C source lines): `function_at`, `line_at`, and `step_line` / `step_out` for the window's C stepping |
| `main.py` | command line, `build_cpu`, headless runner |
| `selftest.py` | 25 checks on the core |

### 3.2 Execution model

`CPU.step()`:

1. If halted or stopped, return `None`.
2. Fetch `mem[IAR]` and increment IAR (wrapping at 25 bits).
3. Decode. If the instruction takes an operand, fetch the next word too and
   remember its address (jumps are relative to it).
4. Execute and return a `Step(address, word, operand, text, note)` for the
   trace.

ALU instructions call `alu.int_op` or `alu.float_op` with `a = R[RA]` and
`b = R[RB]` or the immediate, then store `R0` and the flags. `HALT` sets
`halted`; `resume()` clears it and execution continues after the `HALT`.

`CPU.run(max_steps, stop_at=())` does what calling `step()` `max_steps`
times does, without building `Step` records or disassembling: one loop with
the machine state in local variables, about 3 MHz against `step()`'s
~250 kHz. It stops at `HALT`, at a stack wrap that stops the CPU, or before
an address in `stop_at` (not checked for the first instruction, so a run can
leave a breakpoint). It writes out the common integer ALU ops itself and
calls `alu.py` for DIV, MOD and the float group, so an instruction change
touches both `run()` and `_execute()`; the self-check `test_run_matches_step`
compares them on random code. The window (when the trace is off), the
headless runner (without `--trace`) and `python compiler/src/cc run` all use
`run()`; single steps, the trace and C line stepping use `step()`.

### 3.3 Running it

```
python cpu_sim/src/main.py [rom] [--ram RAM_IMAGE] [--headless] [--steps N] [--trace] [--keys TEXT] [--screen FILE.png] [--disk FILE]
```

* without `--headless`: opens the window with the ROM loaded
* `--headless`: runs up to `--steps` instructions (default 100 000), then
  prints the state, the registers and the display
* `--trace`: prints every executed instruction (headless only)
* `--keys`: preloads the keyboard buffer (use `$'...\n'` in bash for Enter)
* `--screen FILE.png`: saves the RGB screen at the end (headless only; drawn
  at twice the size)
* `--disk FILE`: attaches a disk image (devices `0x8C`/`0x8D`, 1.7); a
  missing file is created, 64 MB and sparse

**The window:**

* left: load ROM/RAM, attach a disk (a file dialog; a new name creates one), reset, step, run/pause, resume (after `HALT`), a speed
  dropdown (1 Hz … 1 MHz, or `max`), and a trace toggle. Below them: the 16
  registers, IAR, ESP, EBP, the flags as checkboxes, and a status block (bank,
  selected devices, the disk and its position, instruction count, measured
  rate, run state)
* middle: ROM and RAM tabs, 256 words per page, with optional disassembly and
  "follow IAR"; and a C source tab (below)
* right: the display (`0x5C`) and the RGB screen (`0x6C`, a tab that comes
  forward when a program first draws), the hex display, the keyboard field
  (`0xF0`), and the last executed instructions

Editing: type into any register/IAR/ESP/EBP box and press Enter, click the
flags, or double-click a memory word. Values accept `0x1F`, `31`, `-5`,
`0b1010`, and `1.5` / `1.5f` (stored as float32 bits). Right-click a memory
word to toggle a breakpoint; a running CPU stops *before* executing that
address. `clear bp` removes them all.

C source: when a `.map` with source lines sits next to the ROM (`cc build`
always writes one), the C source tab shows the file of the line being run
with that line highlighted, and the state box shows the function and line.
Right-click a source line for a breakpoint on all of its code. The "C line"
buttons run to the next line: *into* follows calls, *over* runs calls to
the end (lines in a deeper frame, EBP above the current one, don't count),
*out* runs until the function returns. The line table is read by
`debuginfo.py`.

The keyboard field is read-only: every key goes straight into the buffer
(Enter as `0x0A`, Backspace as `0x08`, printable ASCII as itself, the arrows as 28–31, Ctrl+letter as 1–26; `key_code()` in `devices.py`).
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
| `FLOAT_NOP_RESULT` | `0`: written to `R0` by float `SHR/++/--` and the undefined float opcodes | confirmed for the undefined opcodes (`diag16.asm`); on the circuit float `SHR/++/--` read back as `0xFFFFFFFF` with N and Z both on (an undriven bus?), which the simulator doesn't copy |

---

## 4. The assembler and linker (`compiler/src/asm/`)

The full language reference is in
[`compiler/assembly_syntax.md`](compiler/assembly_syntax.md). This section
explains how the tools work.

### 4.1 Command line

```
python compiler/src/asm assemble prog.asm            [-o prog.obj]
python compiler/src/asm link     prog.obj lib.obj    [-o prog.rom] [--map] [--lib lib.obj]
python compiler/src/asm build    prog.asm lib.asm    [-o prog.rom] [--map] [--lib lib.asm]
```

`--lib FILE` (repeatable) links FILE as a library: only the parts the
program needs (4.6). Libraries are placed after the other inputs.

`build` accepts `.asm` and `.obj` files mixed; `link` takes only `.obj` (and
suggests `build` when given something else). The default output name is the
first input with `.rom`. `--map` also writes a `.map` file with every label's
final address, and (when the code has `.loc` lines, as C code does) a
"source lines" section: the address where each source line's code starts.

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
| `selftest.py` | 20 checks for the assembler and linker |
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
| `.part` | 0 (starts a new part) |
| `.loc "file", line` | 0 (records where a source line's code starts) |
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
* `rel`: a jump offset to a label in **another** file, or in another part
  of this file (`section: rom`, the target's offset in `addend`)

**Parts.** After pass 1 the file's ROM is cut into parts: one starts at
offset 0, at every `.global` ROM label and at every `.part` directive. Each
part records whether it can fall through into the next one (its last
statement is not `RJMP`, `JMRB`, `RET`, `.word`, `.string` or `.space`).
Jumps to labels in the same part are resolved immediately, since the
distance does not change when the file moves; a jump into another part
becomes a `rel` relocation, because a library link may move or drop parts.

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

(Since 2026-10-11 an object file also has `"parts": [[start, falls_through], ...]`,
the parts of its ROM; an older file without it is one part.)


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
ROM  0x0000000 RJMP start           (2 words, added by the linker)
     0x0000002 each file's ROM part, in command-line order
RAM  0x1000000 stack (never touched by the linker)
     0x1004000 each file's RAM part, in command-line order
```

0. For a library (`--lib`), choose the parts to keep: starting from every
   part of the other files (and `start`), follow the relocations of each
   kept part (a section-relative target, or a `.global` defined in a
   library) to the part it points into, and keep the next part when a kept
   part falls through. A library none of whose labels is referred to is
   dropped, RAM and all. The kept parts are joined up and every offset
   (labels, relocation positions and targets) is renumbered.
1. Give each file a base in ROM and RAM, and check that the sizes fit.
2. Compute every label's final address and build the table of `.global`s
   (the same global in two files is an error).
3. Write the entry jump to `start`. Exactly one file must have
   `.global start`, and it must be a ROM label.
4. Copy each file's words and fill in the relocations (`abs`: the address;
   `rel`: `target − address of the offset word`). Jumping to or calling a
   RAM label is an error; taking a RAM label's address is fine.
5. Check that every `.extern` is exported by some file, even when it is
   never used (a missing file or a typo). Labels of dropped library parts
   still count as exported.

The output is a v2.0 raw image (section 6).

**A program for the OS** (`linker.link(..., base=PROGRAM_BASE)`, used by
`cc build --exe`, 10.4) is linked all in RAM: the entry jump at the base
(`0x1100000`), the ROM parts after it, then the RAM parts straight after the
code. Every step above is the same; only the bases move, so the checks on
`CALL`s and jumps to RAM labels still apply (they look at the label's
section, not its address). The image must fit below the end of RAM.

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
python compiler/src/asm build prog.asm --lib compiler/examples/stdlib/stdlib.asm   # only what prog uses
```

With `--lib`, only the functions the program calls (and the ones they call)
are linked: `programs/guess.asm` takes 556 words instead of 1669.

| group | functions |
| --- | --- |
| output | `print_char(c)`, `print_string(addr)`, `print_int(n)`, `print_newline()`, `print_float(f)` (4 decimals), `print_hex(v)` (`0x` + 8 digits) |
| input | `read_char()` (waits for a key, **no echo**), `read_line(buf, max)` (echoes, handles backspace, keeps max−1 chars, returns the length), `read_int()`, `read_float()` |
| strings | `str_len(addr)`, `str_copy(dst, src)` (returns the length), `str_eq(a, b)` (1/0) |
| memory | `mem_copy(dst, src, n)`, `mem_set(dst, value, n)` |
| int math | `abs(n)`, `min(a, b)`, `max(a, b)`, `ipow(base, exp)` (exp < 0 gives 0; it was called `pow` until 2026-10-11) |
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
| `stdlib/stdlib_more_demo.asm` | the stdlib functions added on 2026-10-03 that need no typing and no hex display; the expected output is in its header |
| `programs/guess.asm` | guess-the-number game with the stdlib (needs typing) |
| `programs/untested.asm` | `show_hex` and `try_read_char`, the two stdlib functions not yet run on the circuit (needs typing) |
| `two_files/main.asm`, `lib.asm` | two files, `.extern`/`.global`, `CALL` inside a call, a RAM variable |
| `tests/io_test.asm` | minimal keyboard → display loop for probing the circuit |
| `c/hello.c` | C: `printf("hello, world\n")` |
| `c/primes.c` | C: a sieve, `printf` with a width, the hex display (`cpu.h`) |
| `c/gfx_demo.c` | C: the RGB screen with `gfx.h`: gradient, text, shapes, a sine wave (`--screen` saves the picture) |
| `c/image_demo.c` | C: compressed pictures with `gfx_image` (7.4): a 128×128 Mandelbrot picture and a transparent 16×16 sprite from `c/images/` (the PNGs and the `.h` files made from them), clipped at the edges |
| `c/structs.c` | C: an array of structs, `qsort`, `malloc`, `printf("%.2f")` |
| `c/guess.c` | C: guess the number with `scanf`; seeded by how long the first key takes (`key_pressed`); the header has a transcript |
| `c/benchmark.c` | C: twelve square roots (the old bit-by-bit `sqrt` as the reference, Quake III's inverse square root with two constants, one or two Newton steps or a residual correction, Newton's method from `y = x` or from two bit-based first guesses) timed with `clock()` over 20 000 inputs and checked against the reference: max absolute and relative error, how many results differ. `-D ONLY_ALGORITHM=n` runs one; `-D COUNT_ONLY` drops the timing so `--stats` gives that one's instruction count. Needs `--steps 600000000` with `cc run` |
| `c/sqrt_benchmark.c` | C: the library's `sqrt()` (Newton from a bit-based guess, then an exact rounding check) against the bit-by-bit one it replaced, 20 000 inputs 5 times: every result the same, about 1.4× faster. Needs `--steps 400000000` with `cc run` |
| `c/video_player.c` | C: plays a video made by `compiler/src/img/video.py` (7.5) at its own speed, waiting on `clock()` (the timer); prints how many frames were late. Plays `c/videos/demo.h` (from `demo.mp4`, ffmpeg's moving test picture, 4 s); `-I . -D 'VIDEO="clip.h"'` plays `./clip.h` instead. Needs `--steps 2000000000` with `cc run` (waiting runs millions of instructions a second) |
| `c/game_of_life.c` | C: Conway's Game of Life on the RGB screen, a 64×64 world that wraps around (2×2-pixel cells, only changed cells redrawn). First checks itself on well-known patterns (24 checks: still lifes, oscillators' periods, spaceships' moves, the diehard dying at 130, the glider gun), then shows seven scenes in turn: Gosper glider gun + eater, oscillators and still lifes, spaceships, R-pentomino, diehard, acorn, random soup. Keys `1`–`7` pick a scene, `n` next, `r` restart, space pause, `s` one step, `q` quit; the hex display shows the generation. `-D SCENE=n` starts at scene n, `-D FULL_TEST` also checks that the first three scenes repeat. 100 000–330 000 instructions a generation |
| `c/grapher.c` | C: a graphing calculator on the RGB screen. Type a function of x on the bottom line (`+ - * / ^`, implied products like `2x`, `\|x\|`, `sin cos tan sqrt ln log exp ...`, `pi`, `e`) and Enter: it is parsed into a small stack program and drawn, up to six functions in different colours, two pixels thick, over a grid with numbers on the axes; gaps where the value is not a number, jumps like tan's left unjoined. Commands `clear`, `reset`, `zoom f`, `in`, `out`, `move dx dy`, `view x0 x1 y0 y1`, `demo`, `help` (the list of what can be typed, also on the screen at the start). 100–200 ms a function in the simulator |
| `c/qr.c` | C: a QR code encoder written from the standard, drawn on the RGB screen as big as it fits. Starts with this project's GitHub link; type any text and Enter for a new code (an empty line goes back to the link). Byte mode, versions 1–10, levels L/M/Q/H (`-D LEVEL=n`, M by default), Reed-Solomon over GF(256) with the blocks interleaved, and all eight masks scored by the standard's penalty rules (`-D MASK=n` forces one). `-D TEXT="..."` the first text, `-D DARK=c` the module colour. Every version and level decodes with `zbarimg` and matches `qrencode` module for module with the same mask. About 2.6 million instructions for the link (0.9 s in the simulator) |
| `c/snake.c` | C: Snake on the RGB screen, a 16×14 grid of 8×8 cells under a score panel; `W`/`A`/`S`/`D` steer, `R` restarts after a game over, `Q` quits (`key_pressed()`, `wait_ms()`) |
| `c/loader.c` | C: runs programs from the disk (simulator only): type a name and arguments, it runs `/bin/<name>` with `spawnv()` and shows the exit status; an empty line lists `/bin`. The first step towards the OS's shell, `os/shell.c` (11) |
| `c/echo.c` | C: a program for the OS (`cc build --exe`, then `disk put` into `/bin`): prints its arguments, like Unix `echo` |
| `c/disk_notes.c` | C: files on the disk (simulator only, `--disk FILE` on a disk made by `python compiler/src/disk format`): prints `/notes.txt`, then adds each typed line to it (`!help` lists the commands: `!show`, `!ls`, `!clear`, `!quit`), so the next run shows them again |
| `c/circuit_test.c` | C: self-checking program for the compiler's tricky code paths (unsigned division, shifts, `~` on registers, compares, floats, NaN, struct copies, jump tables, big frames); prints ok/FAIL per check, passes on the circuit |
| `tests/diag10.asm` | `INT` on floats below 1 (diagnostic, resolved: they give 0) |
| `tests/diag11.asm` | measures `STK SET/GET` with a negative index while `EBP = 0` (on the circuit it reaches the last word of RAM), checks that `STK GET` leaves `RB` alone, and `INT` for positive and negative values (it truncates). Link it **first** (with the stdlib) so its 16 results sit in RAM from `0x1004000`; they are also printed in hex |
| `tests/diag12.asm` | what the C compiler relies on: reading and setting `ESP`/`EBP` with `STK CALL`/`STK RET`, stack slot `i` being RAM word `i` (address `0x1000000 + i` now, `0x10000 + i` on the 16-bit circuit), the carry flag after `CMP`/`SUB`/`ADD`, the `A` flag after `FCMP` (a float compare), `MULT`'s low 32 bits, `DIV` by `0x80000000`. Link it first; 30 results from `0x1004000`, also printed |
| `tests/diag13.asm` | the carry flag (and A N Z) after `SUB`, `--`, `++`, `NEG`, `SHL`, `SHR`, `MULT`, `ADD`, `AND`, `TEST`: on the circuit `SUB` sets C on a borrow and `CMP`/`--`/`NEG`/`MULT` never set it. Link it first; 24 results from `0x1004000`, also printed |
| `tests/diag14.asm` | float special cases: division by ±0, NaN, infinity, `INT` out of range, overflow, subnormals. Link it first; 22 results from `0x1004000`, also printed |
| `tests/diag15.asm` | more of the same after diag14: `INT` of -infinity and of large values, the remaining divisions by zero. Link it first; 15 results from `0x1004000`, also printed |
| `tests/diag16.asm` | where `STK SET/GET` put `EBP + RB` (on the 16-bit circuit it wraps at 16 bits, across all of RAM), R0 and flags after `DIV`, `MOD` and `NOT` (`MOD` by 0 gives 0; `NOT` inverts RA), the float opcodes with no defined result, float rounding (to nearest, ties to even). Link it first; 52 results from `0x1004000`, also printed |
| `tests/diag17.asm` | follow-up to diag16: `NOT` encoded with RA and RB both set (it inverts RA, not RB), `DIV`/`MOD` by 0 and `0x80000000` by -1, float opcodes 4, 5, B, C with other inputs (4 doubles RB). Link it first; 30 results from `0x1004000`, also printed |
| `tests/diag18.asm` | the flags after `OR` and `XOR`, and `NOT` as the assembler writes it now (register in both fields: `~Rx`, `A` = 0); all as the simulator. Link it first; 16 results from `0x1004000`, also printed |

All of these build and run correctly in the simulator. The `c/` programs
are C: build them with `python compiler/src/cc build <file>` (or `run`,
section 10.1), which links the C library instead of `stdlib.asm`. Built
images go in `compiler/ROM/`, which git ignores. Rebuild them after changing
a source or the stdlib; an image there can be older than its source.

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
* the simulator also accepts `#` comments

---

## 7. Tooling

### 7.1 `run.py`

One entry point at the project root. With no arguments it shows a menu and
lets you pick files from the project (it skips `.git`, `.venv`,
`__pycache__`). With arguments:

| command | does |
| --- | --- |
| `python run.py asm <files…> [-o out.rom]` | `compiler/src/asm build …`, or `compiler/src/cc build …` when a `.c` file is among them |
| `python run.py sim [rom]` | `cpu_sim/src/main.py [rom]` (the window) |
| `python run.py build <files…> -o out.rom` | the same build, then opens the result in the simulator |
| `python run.py test` | runs the four self-check suites, then `check_docs.py` |
| `python run.py img <picture.png> [options]` | `compiler/src/img …`: the PNG -> a compressed `picture.h` for `gfx_image()` (7.4) |
| `python run.py video <clip> [options]` | `compiler/src/img/video.py …`: a video (or a folder of PNG frames) -> `clip.h` for `video_player.c` (7.5) |

It checks for `tkinter` before opening the window and prints install hints
when it is missing. In the menu, the output of `asm`/`build` is the first
source file with `.rom`; the menu offers `.asm` and `.c` files, leaving
out the C library's own, the C compiler's test programs (`compiler/src/`)
and build output (`compiler/ROM/`). For `img` it offers the project's `.png` files, then asks
for the converter's options (Enter for none); `video` does the same with the
project's video files (`.mp4`, `.mkv`, `.webm`, `.mov`, `.avi`, `.gif`).

### 7.2 `logisim/run_rom.py`

Runs a ROM on the **real circuit** without the GUI:

```
python logisim/run_rom.py logisim/CPU.circ prog.rom [--jar path/to/logisim-evolution.jar]
                          [--seconds 120] [--circuit PC] [--keep patched.circ]
python logisim/run_rom.py logisim/CPU.circ --dump-rom current.rom
```

It parses the `.circ` XML and finds the single `ROM` component inside the
`RAM` subcircuit. If that ROM has fewer than 24 address bits it stops with a
message: programs are now laid out for 24-bit banks and the circuit is still
16-bit (2.4). Otherwise it replaces the ROM's contents with the image
(`addr/data: <the ROM's width> 32` header, 8 words per line) and writes
`CPU__patched.circ` to the current directory (or to `--keep`). Then it runs
`java -Djava.awt.headless=true -jar <jar> <patched> --toplevel-circuit PC -t tty,halt`
and prints the TTY output. Without `--jar` it uses `$LOGISIM_JAR`, then
`/usr/share/java/logisim-evolution/logisim-evolution.jar` (the Arch package).

Logisim's `halt` mode stops the simulation when an output pin labelled
exactly `halt` in the top-level circuit goes high. `PC` has one, driven by the
CPU's halt signal, so a run ends at `HALT` and prints `--- halted at HALT ---`
(Logisim logs this as an `ERROR` line, which `run_rom.py` hides). A run that
reaches `--seconds` first prints `--- exit: timeout ---`. For scale,
`stdlib_demo` takes about 40 seconds.

`--dump-rom` instead writes out the ROM currently stored in the circuit. The jar is not in the
repo.

### 7.3 Self-checks

```
python compiler/src/asm/selftest.py   # 20 checks: encodings, values, strings, jumps,
                                      # CALL/RET, SAVE/RESTORE, linking, a program past
                                      # 64K words and the size limits, link errors
                                      # (RAM calls, unexported externs), warnings,
                                      # library parts (--lib), raw output, .obj
                                      # round trip, CLI, examples
python cpu_sim/src/selftest.py        # 25 checks: immediates, flags, carry flag, DIV/MOD by 0, RAM,
                                      # ROM writes, stack, STK SET/GET across RAM, frames,
                                      # floats, FCMP flags, keyboard, backspace, key codes (arrows, Ctrl), the display's
                                      # backspace and form feed, ADDR/JMRB,
                                      # float specials, float SHL, run() against step()
                                      # on random code, run() stopping at breakpoints,
                                      # the top of both 16M-word banks, the timer,
                                      # the disk (kept in its file, size, past the end)
python compiler/src/cc/selftest.py    # 15 checks: preprocessor, error messages (several per run), warnings,
                                      # type sizes, exit/atexit, keyboard input, globals
                                      # after a reset, library override, reserved names,
                                      # mixing C and assembly, memory past 64K words (ROM
                                      # table, RAM array, malloc, far code), CLI, C line
                                      # stepping, and every test program
                                      # in compiler/src/cc/tests/ against gcc's output
python compiler/src/img/selftest.py   # 10 checks: gamma codes, encode/decode round trips
                                      # (both forms), the packed fallback,
                                      # bad input, PNG reading (every filter, colour type
                                      # and bit depth), resizing, palettes, CLI, and
                                      # gfx_image() on the simulator against codec.decode(),
                                      # and video.py: frames land on the screen as it says,
                                      # PNG folder via the CLI, video_player.c on the
                                      # simulator, a 1 s video through ffmpeg (if installed)
python compiler/src/disk/selftest.py  # 15 checks: format (sparse, the superblock), text and
                                      # binary round trips (block edges), overwriting frees
                                      # blocks, a directory past one block (entries reused),
                                      # subdirectories, . and .., mv, name rules, disk full, CLI,
                                      # fsck, the C library on the simulator against fs.py, `stat()` against fs.py,
                                      # the shell and the `ed` editor run on a disk,
                                      # (each reads what the other wrote; fsck clean after),
                                      # and spawnv(): a --exe program put on the disk, run
                                      # three times (arguments, exit status, fresh variables,
                                      # the caller's directory and heap, load errors), and
                                      # os/shell.c on a disk from os/make_disk.py: a session
                                      # of every built-in, > and >>, quotes, a /bin program's
                                      # arguments and exit status, the error messages
python check_docs.py                  # 3 checks on the docs: every repo path they name
                                      # exists, every example (.asm, .c) and os/*.c is
                                      # listed (5.3, 11), every TWEAKS switch is in 3.4
```

`check_docs.py` checks only mechanical facts. It skips build output under
`compiler/ROM/`, `diagNN`-style placeholders, and paragraphs that mention
files as removed.

### 7.4 Pictures for the RGB screen (`compiler/src/img/`)

```
python compiler/src/img picture.png [-o picture.h] [--name NAME] [--size WxH] [--colors N] [--dither] [--preview FILE.png]
```

turns a PNG into a compressed image that `gfx_image(x, y, img)` (`gfx.h`,
`compiler/libc/gfx_image.c`) draws. It writes `picture.h` next to the PNG,
holding `static const unsigned int picture[] = {...};`, which a C program
`#include`s (so the words end up in ROM). It won't overwrite a file it
didn't write. The defaults: the array is named after the file; a picture
bigger than the screen is shrunk to fit 128×128 (area average), `--size`
picks the size (`64x` or `x48` keeps the shape); pixels with alpha below
128 become transparent. `--preview` saves what the screen will show (2×).

Colours: each pixel becomes RGB565, dropping the low bits like `GFX_RGB`
(rounding would split the dark noise of photos into two levels and make
them much bigger). Up to `--colors` (default 256) colours are kept exactly;
more are reduced by median cut plus three rounds of k-means, mapped to the
nearest colour (`--dither`: Floyd–Steinberg, which looks smoother with few
colours but compresses worse).

The format (in full at the top of `codec.py`): a header (width, height,
number of palette colours, transparent index), the palette two colours per
word, then a bit stream of tokens over the pixels in reading order: `0` +
a palette index, or `1` + a kind + an Elias gamma length for a run of
pixels copied from the previous pixel, the one above, above-left or
above-right (outside the image counts as palette colour 0). The encoder is
greedy. A picture with few runs (dithered, noisy) would cost more than b
bits a pixel that way (each lone pixel is a flag bit + b), so the converter
also writes the **packed** form, just b bits a pixel with no tokens, and
keeps the smaller one (header word 2 then has `0x10000` added). So a picture
is never bigger than b bits a pixel: black and white is at most 32 pixels a
word, 512 words for 128×128. Measured on 128×128 pictures (16 384 words at
one word per pixel):

| picture | colours | words |
| --- | --- | --- |
| `gfx_demo.c`'s screen | 22 | 268 |
| a logo | 194 | 516 |
| the Mandelbrot picture of `image_demo.c` | 230 | 1734 |
| a cartoon, reduced to 256 / 16 colours | 1096 | 1359 / 469 |
| a logo / a cartoon, thresholded to black and white | 2 | 106 / 155 |
| a page of text, black on white | 2 | 306 |
| a photo, black and white, dithered (packed) | 2 | 517 (550 with runs) |

The decoder keeps two rows of colours on the stack, decodes a row, then
sends it (clipped, transparent pixels skipped) to device `0x6C`; a run can
go on into the next row. A packed picture is read by `unpack_row` instead,
or `unpack_bits_row` for 1 bit a pixel (the top bit picks one of two
colours: about 32 instructions a pixel in all, against 48 through the
general one). It is about 1500 words of code and takes 32–50 instructions a
pixel (about 0.5–1 million for a full screen: 3–10 seconds in the
simulator, far too slow for the circuit's 160 a second). About 15 of those
go to sending the pixel; the rest is spread over small functions so that
their loops keep their variables in registers (see the file's comment). `codec.decode()` is the reference: the self-check draws images
with `gfx_image()` in the simulator and compares every pixel.

### 7.5 Videos for the RGB screen (`compiler/src/img/video.py`)

```
python compiler/src/img/video.py clip.mp4 [-o clip.h] [--fps 10] [--size WxH] [--colors 32]
                                 [--tolerance 16] [--start S] [--seconds S] [--max-frames N]
                                 [--preview DIR]
python compiler/src/img/video.py frames/ ...      (a folder of PNGs, in name order)
```

turns a video into a `.h` of compressed frames that
`compiler/examples/c/video_player.c` plays at the video's speed. `ffmpeg`
and `ffprobe` read the video (they must be installed; a folder of PNG frames
needs neither): `--fps` frames a second (1–60), shrunk to fit 128×128 unless
`--size` says otherwise, `--start`/`--seconds` take a part.

* **One palette for every frame:** `--colors` (default 32) chosen over all
  the frames' pixels (median cut + k-means, `palette.fit_colors`), no
  dithering (it would flicker), so a pixel that keeps its colour keeps its
  palette entry.
* **Only what changed:** frame 0 is drawn whole. In every later frame a
  pixel is transparent unless its colour is more than `--tolerance` (about
  that much per channel, 0–255; 0 = any change) away from what the screen
  shows there; the encoder keeps that screen as it goes. Transparent runs
  cost a few bits.
* **Each frame is an ordinary picture** in the 7.4 format, with its own
  palette holding only the colours it draws (transparent first, then by
  use), so a frame that changes little has few colours and few bits a pixel.
  Every frame is decoded back and checked as it is written.
* **The `.h`:** `VIDEO_FRAMES`, `VIDEO_FPS`, `VIDEO_WIDTH`, `VIDEO_HEIGHT`,
  `video_data[]` (all frames, one after another) and `video_start[]` (where
  each frame begins). One video per program. More than half the ROM (8M
  words) is refused. `--preview DIR` saves every frame as the screen will
  show it (PNG, 2×).

The player clears the screen, then draws frame `i` with `gfx_image` when
`clock()` reaches `i * 1000 / VIDEO_FPS` (the timer, 1.7), and waits out the
last frame. A frame can't be skipped, since each one draws only what changed,
so a player that falls behind stays behind until frames get cheaper; it
counts the frames drawn more than one frame late.

Measured on 4 s clips, 128×96 (12 288 words a frame at one word per pixel):

| clip | fps | colours | words a frame | instructions a frame |
| --- | --- | --- | --- | --- |
| ffmpeg's `testsrc2` (moving test picture): `videos/demo.h` | 12 | 32 | 220 | 352 000 |
| the same | 10 | 32 | 222 | 354 000 |
| the same, `--tolerance 0` / `--colors 16` | 10 | 32 / 16 | 232 / 198 | |
| ffmpeg's `life` (Game of Life, much of it changing) | 10 | 31 | 523 | 462 000 |

Drawing costs about 28 instructions a pixel even where nothing changed
(`gfx_image` decodes and walks every pixel), so 10 frames a second needs
about 4 million instructions a second: `pypy3` keeps up (0 frames late on
the demo), plain `python` (about 2.7 MHz) doesn't, and the circuit (about
2 kHz) would take minutes a frame. Skipping transparent runs without
walking their pixels would be the next speed-up.

---

### 7.6 Disk images (`compiler/src/disk/`)

The disk device (1.7) is a file of words; the TFS1 filesystem on it is
written down in `compiler/src/disk/fs.py` (the docstring is the reference;
the C library's `fs.c` reads and writes the same format, `c_language.md`
§7). In words, with 256-word blocks:

| where | what |
| --- | --- |
| block 0 | superblock: `0x31534654` ("TFS1" as bytes), version 1, block size 256, block count N, FAT start block (1), FAT block count F = ceil(N / 256), the root directory's first block and length |
| blocks 1 … F | the FAT, one word per block: 0 free, `0xFFFFFFFF` the last block of a chain, else the next block. Blocks 0 … F are marked used |
| block F + 1 … | the root directory's first block, then data |

A file is a chain of blocks; a directory is a file of 132-word entries
(name: 128 words, one char per word, 0-terminated, 1–127 chars, no `/`,
spaces or control characters; first block, 0 = empty; length; flags: 1 in
use, 2 directory, 4 packed text; a reserved word). Deleted entries (flags 0)
are reused; directories never shrink; `.` and `..` are resolved in the
path. A text file holds 4 chars a word, char k in bits 8(k mod 4) of word
k / 4, so the image's bytes read as plain text on the PC, and its length
counts chars; a binary file's length counts words. A 64 MB disk has 65,536
blocks (256 for the FAT) and 65,278 free when new.

```
python compiler/src/disk format disk.img [--size MB] [--force]   # new disk (64 MB, sparse); --force wipes one
python compiler/src/disk ls disk.img [PATH]                      # a directory: size (chars/words) and name
python compiler/src/disk put disk.img HOST [PATH] [--binary]     # copy in (text unless --binary, or a TEX1
                                                                 # program from cc build --exe); PATH: a
                                                                 # name or a directory, default /HOST's name
python compiler/src/disk get disk.img PATH [HOST|-]              # copy out (- = the terminal)
python compiler/src/disk cat disk.img PATH
python compiler/src/disk rm|mkdir|rmdir disk.img PATH            # rmdir: empty directories only
python compiler/src/disk mv disk.img OLD NEW                     # rename or move (files and directories)
python compiler/src/disk df disk.img                             # blocks used and free
python compiler/src/disk fsck disk.img                           # every block in exactly one file?
```

## 8. Simulator vs. circuit: open questions

The simulator is the reference for the tools, but it was written from the
ISA, not generated from the circuit. Where they disagree, the circuit wins.

| topic | simulator | circuit |
| --- | --- | --- |
| keyboard codes 28–31 (arrows) and 1–26 (Ctrl+letter) | buffered (`devices.key_code`) | **not measured**: the Logisim `Keyboard` gives 7-bit ASCII, but whether it buffers control characters, or arrow keys at all, is unknown (a diagnostic that echoes `INDATA` as hex would tell) |
| `A` signed, `SHR` logical, `DIV`/`MOD` truncate, stack wraps | as in 3.4 | confirmed (2026-10-02) |
| `INT` (float → int) | truncates toward zero | confirmed: truncates (`diag10.asm`, `diag11.asm`) |
| `STK SET/GET`: where `EBP + RB` lands | wraps at 16 bits, across all of RAM | confirmed (`diag11.asm`, `diag16.asm`, 2026-10-13). The simulator used to wrap it at 14 bits, inside the stack area; it now matches the circuit |
| does `STK GET` also write `RB`? | no | no: fixed in the circuit (STK GET/SET/PUSH no longer misuse RB) |
| float opcodes 4, 5, B, C (`SHL/SHR/++/--`) and the undefined ones | 4 writes `RB × 2`; the others write 0 (`FLOAT_NOP_RESULT`) | measured (`diag16.asm`, `diag17.asm`, 2026-10-13): 4 doubles RB (normal numbers tried), 8/9/A/E write 0, **5, B and C differ**: `0xFFFFFFFF` with N and Z both on, which looks like an undriven bus |
| `NOT` | inverts `RB`, as designed | confirmed (`diag17.asm`, 2026-10-15) after the circuit was rewired. Before that it inverted `RA` (`diag16.asm`, `diag17.asm`, 2026-10-13), which is why the assembler writes `NOT Rx` with `x` in both fields |
| `DIV`/`MOD` by 0, `0x80000000` by -1 | `DIV` gives the dividend, `MOD` gives 0; `0x80000000`, 0 | confirmed (`diag16.asm`, `diag17.asm`, 2026-10-13). The simulator used to give the dividend for `MOD` by 0 too |
| float rounding | to nearest, ties to even (Python's float32 packing) | confirmed (`diag16.asm`, 2026-10-13): ties to even, not truncated or rounded up |
| carry flag | as in 1.5 | confirmed (`diag12.asm`, `diag13.asm`, 2026-10-10). The simulator used to set C on `SUB`/`CMP` when there was *no* borrow, and on `MULT` overflow; it now matches the circuit |
| float division by zero, NaN, `INT` out of range | as in 1.5 | confirmed (`diag14.asm`, `diag15.asm`, 2026-10-10). The simulator used to give `0.0/0.0 = +inf`, `1.0/-0.0 = +inf` and `INT(inf) = 0`; it now matches the circuit |
| number display `0x3C` | shows the last word sent (window and headless output) | 8 hex digits in `PC` |
| RGB screen `0x6C`/`0x6D` | 128×128 RGB565, the "RGB screen" tab, `--screen` | `RGB_Display` → RGB Video in `PC` (2026-10-22); the `0x6D` clear isn't built |
| disk `0x8C`/`0x8D` | a file, `--disk` or the window's `disk` button | none (Logisim's RAM can't save itself) |
| text display `0x5C`: control characters | `\n` new line, `\r` a carriage return (back to the start of the line; what follows overwrites it), `\b` deletes at the end of a line (after `\r` it moves back one), `\f` clears it all; others are printed | the `display` subcircuit gives the TTY 7 data bits and a write strobe (its clear pin isn't wired). Logisim 4.1.0's `TTY` (read in its code, `TtyState.add`, not run): `\n` and `\r` both start a new line, `\b` deletes, `\f` clears; other control characters are dropped. **`\r` differs, on purpose** (decided 2026-10-28, OS questionnaire round 4 Q25): a real carriage return is worth having apart from `\n`, even though the circuit's TTY can't do it. Nothing in the toolchain prints it |
| timing | one instruction per step | several clock cycles per instruction (stepper) |

---

## 9. Outdated files and stale information

These are still in the repo but are **not** a description of the current
design. When something here disagrees with sections 1–8, sections 1–8 are
right.

The old hand-assembled programs (`cpu_sim/examples/`, `logisim/functions/`),
the outdated `logisim/cpu datas/instruction` table and the old copy of
`assembly_syntax.md` in `compiler/src/asm/` were removed on 2026-10-06; they
are still in the git history.

### Notes

| file | status |
| --- | --- |
| `logisim/cpu datas/stack_instruction.txt` | internal micro-step notes for the stack hardware, not a description of the instructions |
| `logisim/cpu datas/TO DO.txt` | personal to-do list (future ideas: loading ROM into RAM at start, BIOS, OS) |

### Circuit

| item | status |
| --- | --- |
| subcircuits `ROM`, `program_loader`, `sign_controller`, `teste` | not used anywhere. `ROM` is an older memory block (the program now lives in the ROM inside `RAM`); `teste` is the FPU prototype, with π and e as test constants |
| comparator against `0x287` in `RAM` | a debugging watch on one address, not part of the design |

---

## 10. The C compiler (`compiler/src/cc/`) and the C library (`compiler/libc/`)

The language as a user sees it (what C is accepted, type sizes, the
library, mixing with assembly) is in
[`compiler/c_language.md`](compiler/c_language.md). The choices made while
building it, and what is still a guess, are in
[`compiler/c_decisions.md`](compiler/c_decisions.md). This section explains
how the compiler works.

### 10.1 Command line

```
python compiler/src/cc compile prog.c [-o prog.asm]                 # C -> assembly
python compiler/src/cc build prog.c [more.c x.asm y.obj] [-o prog.rom] [--map] [--no-libc] [--lib x.asm] [--exe]
python compiler/src/cc run   prog.c [...] [--keys TEXT] [--steps N] [--stats] [--trace] [--screen FILE.png] [--disk FILE]
        common options: -I dir, -D NAME[=value], -w (no warnings)
```

Output paths follow the assembler's rule (4.1): `compiler/ROM/<first
input>.rom`, `-o name` inside `compiler/ROM/`, an `-o` with a folder as
written. `build` and `run` also write `<name>.asm` for each `.c` next to the
`.rom`; `build` always writes the `.map` too (with the C source lines, for
the simulator window's C view; `.loc` directives carry them). `run` builds, runs the image in the simulator without a window and
prints the display; it exits with 2 if the program doesn't halt within
`--steps` (default 50 million). `build --exe` writes `<name>.exe` instead,
a program for the OS (10.4) for `python compiler/src/disk put`.

### 10.2 Modules

| file | role |
| --- | --- |
| `__main__.py` | the command line above |
| `cerror.py` | `CError` (`file:line:col: error: ...`), `CErrors` (several), `error_at(token, message)` |
| `lexer.py` | text -> preprocessing tokens (line splicing, comments, pp-numbers, literals with prefixes), and `parse_number` / `decode_literal` for after preprocessing |
| `preprocessor.py` | `#include`, `#define`, `#if`..., macro expansion with hide sets (Prosser's algorithm), predefined macros, `#if` arithmetic; then keywords, numbers and string joining |
| `typesys.py` | `Type` (sizes in words, all alignment 1), integer promotion, usual arithmetic conversions, compatibility, `type_name` for messages |
| `nodes.py` | `Node` (one expression or statement; the kinds are listed in the file) and `Obj` (a variable or function) |
| `cparser.py` | recursive-descent parser that type-checks as it builds (in the style of chibicc): declarations, initializers, constant folding, constant evaluation for static data, implicit conversions as `cast` nodes |
| `regalloc.py` | which locals live in registers, and which of them each call must keep |
| `codegen.py` | syntax tree -> assembly text, one function at a time |
| `peephole.py` | clean-ups on each function's instructions |
| `driver.py` | compiles files, caches and selects the C library, writes crt0, links (with `compiler/src/asm`'s assembler and linker), runs the simulator |
| `selftest.py` | the self-checks (7.3) |
| `tests/` | the test programs, their gcc outputs (`.expected`) and `difftest.py` |

Like the assembler, the modules import each other by plain name; the
driver puts `compiler/src/asm/` on `sys.path` to use `assembler`, `linker`
and `objfile` (the module names don't overlap).

### 10.3 Code generation

**Registers.** R0 takes every ALU result. R1-R12 hold expression
temporaries and register variables (the temporaries get the low numbers,
at least five of them). R13 is scratch for frame indexes and addresses.
R14 and R15 are left to the `CALL`/`RET`/`RESTORE` pseudo-instructions and
the runtime helpers.

**Values.** Each expression evaluates to a `Val`: a constant (used directly
as `#imm` or `DATA`), a temporary register, a variable's register (read but
not changed), R0 (moved out before anything else uses the ALU), or the
address of an aggregate. An lvalue is an `Addr`: a frame slot
(`EBP + offset`, maybe plus a register), a memory address (label + offset,
maybe plus a register), or a register variable. Loads and stores pick the
cheapest instruction: `STK GET/SET` for frame slots, `LD`/`ST` for a known
address, `ALD`/`AST` for base + index (array elements). A local's address is
needed only when it escapes (`&x`, an array passed to a function): then the
function computes `FP = 0x1000000 + EBP` (`RAM_BASE + EBP`) once in its prologue (`STK CALL`,
`STK GET 0`, `STK RET` read EBP) and keeps it in a frame slot.

**Evaluation order.** Of two operands, the one that needs no code goes
last, the one with a call goes first (fewer registers to keep across the
call), otherwise the deeper one first.

**Comparisons and jumps.** Conditions compile straight to jumps (`&&`,
`||`, `!` without making 0/1 values). Signed: `CMP` and the A flag
(`a < c` is "not A after `CMP a, #c-1`"). Unsigned: `SUB` and C, which is a
borrow. Floats: `FCMP` and N/Z only, so a NaN compares false (`a <= b` is
"N or Z after `FCMP a, b`"). Pointers compare as signed (addresses are below
2^17).

**Arithmetic.** `x << k` is `MULT x, #2^k`; logical `x >> k` is `SHR x` then
`DIV R0, #2^(k-1)`; arithmetic `>>` of a negative number is
`NOT(NOT x >> k)`. By a variable count, `2^n` comes from the `_pow2` table.
Unsigned `/` and `%` by a power of two are shifts and masks, otherwise a call
to `_udiv`/`_umod`. Conversions: `FLOAT`/`INT` (truncation, as C wants),
with corrections for unsigned values of 2^31 and above.

**Calls.** Arguments are pushed with `STK PUSH` (structs word by word); the
call is the `CALL` pseudo-instruction's sequence written out, with `RJMP f`
for a direct call (or `JMRB` through a function pointer) in place of
`DATA R0, f` + `JMRB R0`. Afterwards the arguments are popped and the saved
registers put back in one sequence, keeping R0 (in R15) only when the result
is used. A `void` function returns with `STK RET`, `STK POP`, `JMRB R0`
instead of the 6-word `RET`. Live temporaries and the register variables still
needed after the call are kept with `SAVE`/`RESTORE`; a register variable
that the arguments themselves change is written to its stack slot before
the call and read back after. Variadic calls push the variadic arguments,
then the fixed ones, then the variadic word count; `va_start` computes
`FP - (fixed words + 2) - count`.

**Frames.** Parameters are at negative offsets from EBP, locals (and
struct-result buffers, and the slots of register variables a call keeps in
memory) at EBP+1 up. The prologue
reserves the frame with `STK PUSH`es, or above 15 words sets ESP directly
(two `STK RET`s, as `setjmp.asm` explains), then loads the register
parameters. Every return jumps to one `RET`.

**Register variables** (`regalloc.py`): scalar locals and parameters whose
address is never taken. Uses count 8 times more per enclosing loop; a
variable gets a register if 2 instructions per use outweigh 4 for every call
where it must be kept (and 3 to load a parameter). A call keeps a variable
if it is used later in the function, in the same statement, or anywhere in
a loop around the call; with labels and `goto` in the function, at every
call.

**Other statements.** A `switch` with 5 or more cases spread over at most 3
slots per case becomes a jump table (`ALD` + `JMRB` through a `.word` list);
others a chain of `CMP`/`RJF`. Struct copies up to 8 words are unrolled,
longer ones a loop. Bit-fields are read and written with `MULT`, the shift
sequences and `AND`/`OR` on their word.

**Peephole pass** (`peephole.py`): drops a `DATA` or `CPY` that would
reload a value a register already has (within straight-line code), a `TEST`
whose flags the previous integer ALU instruction already set (before a jump
on Z/N), jumps to the next instruction and jump chains, and code no label
leads to after an unconditional jump.

### 10.4 Data and start-up

* Functions, string literals, `const` data, jump tables and the starting
  values of initialised variables go in `.rom`. Variables go in `.ram`
  (`.space`): the initialised ones together, then the zeroed ones.
* Each C file gets an `_init_<file>` routine (only when it has RAM data): it
  copies its starting values from the `_T_<file>` template in ROM, and
  clears the rest. `driver.crt0_source` writes the start-up code for each
  build: `start` calls every linked `_init_` routine, then
  `main(0, {NULL})`, then `exit` with main's result. crt0 also holds
  `_Exit` (HALT, in a loop) and `_heap_end`, the word where malloc's heap
  ends: the end of RAM, or `0x1100000` when `spawnv` is linked (the build
  then also checks that the program's variables end below it). The build
  links, in order: crt0, the given files, the library files they need, and
  a last object whose `.ram` label `_end` marks the end of all variables
  (where malloc's heap starts).
* **Programs for the OS** (`build --exe`) are linked at `0x1100000` (4.6)
  and saved as a TEX1 executable: a 5-word header (`0x31584554` "TEX1",
  load address, n, entry, words to zero after the image) and the n words,
  little-endian, so `disk put` stores it as a binary file (it spots the
  magic). `spawnv()` (`spawn.c`) checks the header, copies the words with
  `_fs_read` (one seek a block, about 14 instructions a word), zeroes the
  variables, and jumps to the entry with R1 = a block: argc, argv, the
  address to go back to, its current directory, and a `put` function for
  stdout (0: the display; `spawnv_to(path, argv, out)` gives one that writes
  to the caller's open `FILE`, which is how the shell's `>` works for
  programs). That crt0 keeps the block, calls the `_init_` routines,
  `_fs_inherit(cwd)` (when `fs.c` is linked) and `_set_stdout(put)` (when
  `file.c` is), then `main(argc, argv)`; its `_Exit` jumps back to `spawn.asm`'s
  `_spawn_return` with R0 = the status, which `longjmp`s to the stack
  `spawnv()` had, so `exit()` works at any depth. The program has its own
  copy of the library (its own heap, from its `_end` to the end of RAM, and
  its own open files); afterwards `spawnv()` calls `_fs_forget()` so the
  caller re-reads the disk. A `--exe` program can't link `spawnv` (it would
  load over itself).
* Labels: C names as they are (or `_X` + name, 5 in `c_language.md`);
  compiler labels `_K<n>` (code), `_L<n>` (statements), `_S<n>` (strings),
  `_F<n>` (`__func__`), `_V<n>_<name>` (static locals), `_C<n>`, `_G<n>`.

### 10.5 The C library

`compiler/libc/` holds the headers (`include/`), the library in C (one file
per group of functions: `printf.c`, `format.c`, `fdigits.c`, `scanf.c`,
`string.c`, `malloc.c`, `math.c`, `gfx.c`, `gfx_text.c` and `gfx_image.c` for the RGB
screen, `fs.c` (files on the disk, TFS1 as in 7.6, `stat` and `statvfs`) and `dir.c`
(directories), ...), `local.h` (shared by the library
files only) and three assembly files: `runtime.asm` (`_pow2`, `_udiv`,
`_umod`), `setjmp.asm`, and `spawn.asm` (the jumps of `spawn.c`'s `spawnv`,
10.4). `_Exit` is in the generated crt0.

* The driver compiles each library file the first time it is needed and
  keeps the `.obj` (and the `.asm`, for reading) in `compiler/ROM/libc/`,
  with a key made from the file, the compiler's sources and the headers
  (`include/sys/` too): a change to any of them rebuilds it.
* `driver.select_library` links a library file only when it defines a name
  that is still missing, repeating until nothing is: like a static library,
  so a program's own `puts` wins. The chosen files are then linked as
  libraries (4.6): the compiler starts a `.part` at every function and data
  object, so only the functions and data actually used go in.
* `runtime.asm`'s helpers are called with `DATA R14, back` / `RJMP _udiv`
  and return with `JMRB R14`; they change only R0, R13, R14, R15.
* `FILE` (in `local.h`) carries `get`/`put`/`flush` pointers that `fopen`
  sets; `file.c`, `getchar.c`, `format.c` and `scanf.c` call them for
  files on the disk, so `fs.c` is linked only into programs that call
  `fopen`, `stat` or `statvfs` (c_decisions 33–35).
* `format.c` prints floats exactly: `fdigits.c` turns the float's exact
  value into decimal digits (base-10000 pieces for big integer parts, a
  160-bit binary fraction for the rest) and rounds ties to even.

### 10.6 Checking it

* `compiler/src/cc/selftest.py` (part of `python run.py test`, 7.3).
* `compiler/src/cc/tests/*.c`: programs whose output must match gcc's,
  stored in `<name>.expected`. `python compiler/src/cc/tests/difftest.py`
  builds each one with gcc and with this compiler and compares;
  `--update` rewrites the `.expected` files from gcc. A test reading input
  would have a `<name>.keys` file and a hand-written `.expected` (the echo
  of typed keys makes gcc's output differ).
* `python compiler/src/cc/tests/fuzz.py [--count N] [--seed S]` writes
  random programs free of undefined behaviour and of unspecified evaluation
  order (unsigned arithmetic, masked shift counts, divisors that can't be 0;
  loops, switches, arrays, struct members, a local array whose address is
  taken, a global pointer, structs by value, calls between functions; floats
  kept in range and printed as bits), builds each with gcc and with this
  compiler and compares their output; programs gcc's sanitizer objects to
  are skipped, one that differs is saved in `compiler/ROM/fuzz/`. 246
  programs with floats and pointers agreed on 2026-10-11.
* `compiler/examples/c/circuit_test.c` runs the compiler's tricky code
  paths on the circuit (all lines `ok` on 2026-10-10, again on 2026-10-11
  after the call changes, and on 2026-10-13 with the new "bitwise not of a
  register" line, which says FAIL on the circuit when `NOT` is encoded the
  old way, with RA = 0). On 2026-10-11 eight test programs (`c99`,
  `jumps`, `preproc`, `arrays`, `features`, `globals`, `structs`,
  `control`) also ran on the circuit and printed exactly their
  `.expected` (gcc's) output.

---

## 11. The OS: Tynix (`os/`)

The OS is called Tynix (after tiny C; the shell's banner says `Tynix
shell`). Simulator only (it needs the disk, 1.7 and 7.6). One program at a time,
like CP/M or MS-DOS: there are no interrupts and no memory protection, so
no multitasking.

| file | what it is |
| --- | --- |
| `os/shell.c` | the OS's ROM: a command shell, built like any C program (18,793 words of ROM, 2,925 of RAM) |
| `os/ed.c` | a line editor for text files, a program for `/bin` (15.8K words; section 11.1) |
| `os/make_disk.py` | makes `os/disk.img` (git-ignored) when it is missing or with `--new` (TFS1, 64 MB or `--size`), builds every program in its `PROGRAMS` list (from `os/` or `compiler/examples/c/`) with `cc build --exe` into `/bin` (replacing the old copies) and writes `/readme.txt`; other files on the disk are kept. Twelve C examples and `ed`, 2.8K–17.4K words each, in under a second |

```
python os/make_disk.py [IMG] [--new] [--size MB]
python compiler/src/cc build os/shell.c
python cpu_sim/src/main.py compiler/ROM/shell.rom --disk os/disk.img
python compiler/src/cc run os/shell.c --disk os/disk.img --keys $'ls /bin\nprimes\nhalt\n'
```

At start the shell prints a line and checks for a formatted disk
(`opendir("/")`). Without one it says how to attach one and goes on: the
commands that need no disk still work, the others say `No such device`.
Then it prompts with the current directory (`/docs> `), reads a line with
`fgets` (the C library echoes it and handles backspace), splits it into
words at spaces (`"..."` and `'...'` keep spaces in one word; the quotes go)
and takes out `> FILE` or `>> FILE`. The first word picks the command.

Built-in commands (the `commands[]` table, which `help` also prints):

| command | what it does |
| --- | --- |
| `help` | the commands, then the programs in `/bin` |
| `ls [-l] [path...]` | the names (directories end in `/`), two spaces apart, wrapped at 64 columns (the circuit's TTY); `-l`: one a line with its size (chars for a text file, words for a binary one) or `<dir>`. A file's path prints its name |
| `cd [dir]`, `pwd` | `chdir` (no argument: `/`), `getcwd` |
| `cat [file...]` | the files; it stops at a char over 255, which only a binary file has ("a binary file (a program?)"). With no file, the keyboard up to Ctrl-D, then `clearerr(stdin)` so the prompt reads again: `cat > notes.txt` writes a file |
| `echo [word...]` | the words, one space apart |
| `rm path...` | `remove`: files and empty directories |
| `mv from to` | `rename`; into `to` when that is a directory |
| `cp from to` | a copy; into `to` when that is a directory. `stat()` says whether the source is a text file or binary (`fopen` `"r"`/`"w"` or `"rb"`/`"wb"`), so a program in `/bin` copies and still runs. Not a directory |
| `mkdir dir...`, `rmdir dir...` | |
| `df` | `statvfs("/")`: 1 KB blocks, used, free (it reads the whole FAT: 0.9 million instructions on 64 MB) |
| `clear` | a form feed (12) to the text display, `gfx_clear()` for the RGB screen |
| `halt` | `exit(0)`: the CPU halts. Ctrl-D at the prompt does the same |

A built-in writes to `out`: the display, or the file after `>` (`fopen`
`"w"`, a text file) or `>>` (`"a"`), closed after the command. Error
messages always go to the display. A command with the wrong arguments
prints its usage.

Any other first word is a program: a word with a `/` is a path (relative
ones start at the current directory), else `/bin/NAME`. `spawnv(path,
words)` (10.4) loads it at `0x1100000` and runs it in the current
directory with the words as `argv`; the shell's variables and heap stay
below `0x1100000`. When it ends, the shell prints `[NAME: exit status N]`
if N isn't 0. If it can't be loaded the shell says `NAME: no such command`
(a plain name not in `/bin`) or the path and `strerror` (`Exec format
error` for a text file, `Is a directory`). `>` and `>>` work after a
program too: the shell opens the file and passes it to `spawnv_to()`, and
whatever the program writes to `stdout` (`printf`, `putchar`, `puts`,
`fputs(stdout)`) goes to the file; its errors (`stderr`) and the echo of the
keys it reads stay on the display. The program must not rewrite that file
itself (the shell's `FILE` would not see it). If the program can't be
loaded the file has been made (empty) anyway, as in a Unix shell.

A program that never ends keeps the CPU: nothing can stop it from the
outside. The examples `make_disk.py` puts in `/bin` end by themselves, on
Ctrl-D (`grapher`, `qr`) or on `q` (`snake`, `game_of_life`).

### 11.1 The editor: `ed` (`os/ed.c`)

A line editor in the style of Unix's `ed`, a program in `/bin` (the text
display is a teletype: append only, no cursor positioning, so a screen
editor needs the RGB screen instead). `ed notes.txt` loads the file into
memory a line at a time (`malloc`), the commands change that copy and `w`
writes it back. A missing file starts empty and `w` makes it; a binary file
(`stat()` without `S_ISTEXT`, 10.5) is refused, so a program can't be damaged
by saving it as text.

| command | what it does |
| --- | --- |
| `p [range]` | lines with numbers (no range: all); the last one becomes the current line |
| `n` | the current line number, the line count, the file name |
| `a [n]`, `i [n]` | type lines after / before line `n` (default: the current), end with a line holding only `.` or Ctrl-D |
| `c [range]` | replace the lines with typed ones |
| `d [range]` | delete the lines |
| `[range]s/old/new/` | replace the first plain-text `old` in each line (the delimiter can be any char) |
| `/text` | the next line containing `text`, wrapping round |
| `N` | go to line `N` and print it |
| `w [file]` | save (to `file`, which becomes the name), prints the chars written |
| `q` | quit; with unsaved changes it warns once and a second `q` quits. Ctrl-D at the prompt does the same |
| `h` | the list |

A range is `N`, `N,M`, `.` (the current line), `$` (the last), or `,`
(everything). Unlike ed's `?`, an error says what is wrong (`no such line`,
`not found: x`). Lines are at most 255 chars (the same limit as the shell's
line). The self-check `editor` (disk suite) drives it through the shell and
reads the file back with `fs.py`.

