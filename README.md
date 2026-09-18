# logisim-CPU-project-
a complete project starting with a logic gate cpu made in logisim, followed by a compiler made for the especific cpu architecture

# CPU simulator

Simulator for the logic-gate CPU: 32-bit data, 17-bit address bus
(bit 16 on = RAM, off = ROM), 16 registers, C A N Z flags, a stack in the
bottom 25% of RAM, a display at `0x5C` and a keyboard at `0x0F`.

Python 3.10+, standard library only (the window needs `tkinter`; on Linux
that is the `python3-tk` package).

All files sit in one folder, no package, no subfolders. Run from that folder:

```
python main.py                        # empty window
python main.py print_a-z_fixed        # window with a ROM loaded
python main.py abs_value --headless --trace
python selftest.py                    # 11 checks on the core
```

ROM and RAM images are Logisim `v2.0 raw` files (`count*value` runs and
`#` comments are accepted).

## Window

* registers, IAR, flags, ESP/EBP, selected devices, instruction count
* ROM and RAM panes: paged hex, optional disassembly, follows the IAR
* display: takes ASCII from `OUTDATA`, `0x0A` is a newline
* keyboard: what you send goes into the buffer, `INDATA` consumes one character
* controls: load ROM/RAM, reset, step, run/pause, resume (after `HALT`),
  speed dropdown (1 Hz up to 1 MHz, or `max`)
* breakpoints: right-click a word in the ROM or RAM pane to toggle one; a
  running CPU stops before executing that address. `clear bp` removes them all
* editing while paused (or running): type into any register, IAR, ESP or EBP
  box and press Enter, click the flag boxes, double-click a ROM/RAM word.
  Values accept `0x1F`, `31`, `-5`, `0b1010`, and `1.5` or `1.5f` for a
  float32 bit pattern
* trace of the last executed instructions

## Files

| file | what it holds |
| --- | --- |
| `config.py` | sizes, and every behaviour that was a guess (marked TWEAKS) |
| `isa.py` | encoding tables, decoder, disassembler |
| `alu.py` | integer and float ops, flag generation |
| `memory.py` | ROM/RAM banks, Logisim image loader |
| `devices.py` | display, keyboard, COMM bus |
| `cpu.py` | fetch / decode / execute |
| `gui.py` | the window |
| `main.py` | entry point, headless runner |
| `selftest.py` | checks for stack, arrays, immediates, floats, I/O |
| `abs_value`, `print_a-z`, `print_a-z_fixed` | example ROM images |

## Encoding it implements

```
bit14 immediate   bit13 float   bit12 ALU   11..8 opcode   7..4 RA   3..0 RB

000 system      001 int ALU      011 float ALU
                101 int + imm    111 float + imm
```

Every ALU instruction writes R0 and rewrites all four flags.
`CMP` writes 0 to R0 but sets flags from `RA - RB`.

## Assumptions still open

These are in `config.py` where they can be flipped:

* `A_FLAG_SIGNED` - "RA > RB" is compared signed
* `SHR_ARITHMETIC` - `SHR` is logical, carry gets the bit shifted out
* `DIV_TRUNCATE` - integer division truncates toward zero, `MOD` keeps the
  dividend's sign
* `STOP_ON_STACK_WRAP` - the stack wraps (current circuit behaviour)
* `FLOAT_NOP_RESULT` - float `SHL/SHR/++/--` and undefined float opcodes
  write 0

Other choices baked in: `SUB` carry is the adder's carry-out (set when there
is no borrow), `MULT` keeps the low 32 bits and sets C when the product does
not fit, a float divide by zero gives infinity with the dividend's sign, and
instruction bits above bit 14 are ignored.

## Note on the old example

`print_a-z` prints `a` 26 times now: it uses `++ R1` expecting the result in
R1, but ALU results go to R0. `print_a-z_fixed` is the same program with
`CPY R0,R1` after the increment and a `CMP` / `RJNF Z` loop.

## Running the assembler

python cpu_sim/src/asm build cpu_sim/src/asm/examples/hello.asm -o program.rom
for multiple files, just need to add the path of each after the build and before -o
