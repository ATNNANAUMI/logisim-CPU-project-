# Assembly language - syntax

Source files end in `.asm`. The assembler turns each one into an object file
(`.obj`), and the linker joins object files into one ROM image in Logisim
`v2.0 raw` format, the same format the simulator already loads.

The tools live in `src/asm/`; section 10 shows how to run them.


## 1. Lines

One statement per line:

```
[label:]   [instruction or directive]   [; comment]
```

All three parts are optional, so a line can be just a label, just a comment,
or blank.

* Mnemonics, register names, flag letters and directives are case-insensitive
  (`add`, `ADD`, `Add` are the same).
* Labels and `.equ` names are case-sensitive (`Loop` and `loop` differ).
* Operands are separated by commas. Spaces and tabs are free.


## 2. Values

Anywhere a value is expected:

| form | example | meaning |
| --- | --- | --- |
| decimal | `42`, `-5` | negative numbers are stored as 32-bit two's complement |
| hex | `0x2A`, `0xFFFFFFFB` | |
| binary | `0b101010` | |
| character | `'a'`, `'\n'` | the ASCII code |
| float | `1.5`, `-0.25`, `2.0f` | the IEEE-754 float32 bit pattern |
| constant | `DISPLAY` | a name from `.equ` |
| label | `loop`, `msg` | the label's final address, filled in by the linker |

Character escapes: `\n` (0x0A), `\t`, `\0`, `\\`, `\'`, `\"`.

Values must fit in 32 bits (`-2147483648` to `0xFFFFFFFF`).

**Simple arithmetic** is allowed with `+` and `-`:

```
'z' + 1        buffer + 4        DISPLAY - 1
```

An expression may contain **at most one label**, and it must be added, not
subtracted. No brackets, no `*` or `/`.


## 3. Registers

`R0` to `R15`.

Remember the ISA rule: every ALU instruction writes its result to **R0**, never
to RB.

`R14` and `R15` are used by the `RET` pseudo-instruction (section 7), so
don't keep values in them across a `RET`.


## 4. Instructions

`RA` and `RB` are registers, `v` is a value, `target` is a label (optionally
`label + n`). Size is in words.

### System

| syntax | effect | size | encoding |
| --- | --- | --- | --- |
| `NOP` | nothing | 1 | `0x0000` |
| `LD RA, RB` | `RB = mem[RA]` | 1 | `0x01ab` |
| `ST RA, RB` | `mem[RA] = RB` | 1 | `0x02ab` |
| `DATA RB, v` | `RB = v` | 2 | `0x030b`, v |
| `RJMP target` | jump | 2 | `0x0400`, offset |
| `RJF flags, target` | jump if any listed flag is on | 2 | `0x050f`, offset |
| `RJNF flags, target` | jump if any listed flag is off | 2 | `0x060f`, offset |
| `CLF` | clear all flags | 1 | `0x0700` |
| `COMM INDATA, RB` | read a word from the input device | 1 | `0x080b` |
| `COMM INADDR, RB` | select input device RB | 1 | `0x081b` |
| `COMM OUTDATA, RB` | send RB to the output device | 1 | `0x082b` |
| `COMM OUTADDR, RB` | select output device RB | 1 | `0x083b` |
| `ADDR RB` | `RB = address of the next word` | 1 | `0x090b` |
| `JMRB RB` | jump to the address in RB | 1 | `0x0A0b` |
| `STK PUSH` | `stack[esp] = R0; esp++` | 1 | `0x0B00` |
| `STK POP` | `esp--; R0 = stack[esp]` | 1 | `0x0B10` |
| `STK CALL` | build a stack frame (no jump) | 1 | `0x0B20` |
| `STK RET` | drop the stack frame (no jump) | 1 | `0x0B30` |
| `STK SET, RB` | `stack[RB] = R0` | 1 | `0x0B4b` |
| `STK GET, RB` | `R0 = stack[RB]` | 1 | `0x0B5b` |
| `ALD RA, RB` | `R0 = mem[RA + RB]` | 1 | `0x0Cab` |
| `AST RA, RB` | `mem[RA + RB] = R0` | 1 | `0x0Dab` |
| `CPY RA, RB` | `RB = RA` | 1 | `0x0Eab` |
| `HALT` | stop | 1 | `0x0F00` |

`a` and `b` stand for the register numbers.

The comma after a `COMM` or `STK` sub-operation is optional, so
`STK GET R1` and `STK GET, R1` are both accepted.

**Jump targets.** You write a label and the assembler computes the offset
(`target - address of the offset word`). You never count words by hand.

**Flags** for `RJF` and `RJNF` are written as letters, in any order:

```
RJF  Z, done        ; jump if Z is on
RJNF Z, loop        ; jump if Z is off
RJF  NZ, not_pos    ; jump if N or Z is on (result <= 0)
```

The letters are `C`, `A`, `N` and `Z`. At least one is required.

### Integer ALU (result in R0, all flags rewritten)

Two-operand, with a register or an immediate:

| syntax | immediate form | effect | encoding (reg / imm) |
| --- | --- | --- | --- |
| `ADD RA, RB` | `ADD RA, #v` | `RA + RB` | `0x10ab` / `0x50a0`, v |
| `SUB RA, RB` | `SUB RA, #v` | `RA - RB` | `0x11ab` / `0x51a0`, v |
| `MULT RA, RB` | `MULT RA, #v` | `RA * RB` | `0x12ab` / `0x52a0`, v |
| `DIV RA, RB` | `DIV RA, #v` | `RA / RB` | `0x13ab` / `0x53a0`, v |
| `AND RA, RB` | `AND RA, #v` | `RA & RB` | `0x17ab` / `0x57a0`, v |
| `OR RA, RB` | `OR RA, #v` | `RA \| RB` | `0x18ab` / `0x58a0`, v |
| `XOR RA, RB` | `XOR RA, #v` | `RA ^ RB` | `0x19ab` / `0x59a0`, v |
| `MOD RA, RB` | `MOD RA, #v` | `RA % RB` | `0x1Aab` / `0x5Aa0`, v |
| `CMP RA, RB` | `CMP RA, #v` | flags from `RA - RB`, R0 = 0 | `0x1Fab` / `0x5Fa0`, v |

`#` marks an immediate: the value goes in the next word and the instruction
is 2 words long instead of 1.

One-operand (register only):

| syntax | alias | effect | encoding |
| --- | --- | --- | --- |
| `SHL RB` | | `RB << 1` | `0x140b` |
| `SHR RB` | | `RB >> 1` | `0x150b` |
| `NOT RB` | | `~RB` | `0x160b` |
| `++ RB` | `INC RB` | `RB + 1` | `0x1B0b` |
| `-- RB` | `DEC RB` | `RB - 1` | `0x1C0b` |
| `NEG RB` | | `-RB` | `0x1D0b` |
| `TEST RB` | | `R0 = RB`, sets N and Z | `0x1E0b` |

### Float ALU (result in R0, all flags rewritten)

Float mnemonics start with `F`, except the two conversions.

| syntax | immediate form | effect | encoding (reg / imm) |
| --- | --- | --- | --- |
| `FADD RA, RB` | `FADD RA, #v` | `RA + RB` | `0x30ab` / `0x70a0`, v |
| `FSUB RA, RB` | `FSUB RA, #v` | `RA - RB` | `0x31ab` / `0x71a0`, v |
| `FMULT RA, RB` | `FMULT RA, #v` | `RA * RB` | `0x32ab` / `0x72a0`, v |
| `FDIV RA, RB` | `FDIV RA, #v` | `RA / RB` | `0x33ab` / `0x73a0`, v |
| `FCMP RA, RB` | `FCMP RA, #v` | flags only, R0 = 0 | `0x3Fab` / `0x7Fa0`, v |
| `FNEG RB` | | `-RB` | `0x3D0b` |
| `FLOAT RB` | | int to float | `0x360b` |
| `INT RB` | | float to int | `0x370b` |

The float opcodes the ISA marks "nothing" or "undefined" have no mnemonic.

A float literal always becomes float32 bits, so `FADD R1, #1.5` is right. The
assembler warns about the two easy mix-ups:

* a float in an integer instruction: `ADD R1, #1.5` adds the bit pattern, not 1.5
* a whole number in a float instruction: `FADD R1, #3` adds the bits `0x3`
  (a tiny number), not 3.0. Write `#3.0`. `#0` is fine, its bits are 0.0.


## 5. Directives

| directive | effect |
| --- | --- |
| `.rom` | following lines go in ROM (the default) |
| `.ram` | following lines go in RAM |
| `.global name, ...` | make labels visible to other files |
| `.extern name, ...` | use labels defined in another file |
| `.equ NAME, v` | a named constant (takes no space, can be a float) |
| `.word v, ...` | one word per value (ROM only) |
| `.string "text"` | one character per word, then a 0 word (ROM only) |
| `.space n` | n words: zeros in ROM, reserved space in RAM |

A constant used by `.equ` or `.space` must be defined above that line.

**RAM holds no code or initial data.** Inside `.ram` only labels and
`.space` are allowed. Everything else is an error.

**Labels are private to their file** unless listed in `.global`. Using a
label from another file without `.extern` is an error, which catches typos.


## 6. How the linker lays things out

```
ROM  0x00000   RJMP start           (2 words, added by the linker)
     0x00002   first file's ROM part
               second file's ROM part
               ...                  (in the order given on the command line)

RAM  0x10000 - 0x13FFF   stack (never touched by the linker)
     0x14000   first file's RAM part
               second file's RAM part ...
```

Exactly one file must define `.global start`. That's where the program begins.


## 7. Pseudo-instructions

These look like instructions but expand into several real ones.

### `CALL target`

Calls a function. It expands to:

```
DATA R0, <return label>   ; return address
STK PUSH                  ; save it
STK CALL                  ; new frame
DATA R0, target
JMRB R0
<return label>:           ; execution continues here after RET
```

* Size: 7 words.
* Changes: R0 only. Flags are untouched.
* The linker fills in both addresses, so nothing is counted by hand.

### `RET`

Returns from a function. The value in R0 is kept as the return value. It
expands to:

```
CPY R0, R15               ; save the return value
STK RET                   ; drop the frame
STK POP                   ; R0 = return address
CPY R0, R14
CPY R15, R0               ; R0 = return value again
JMRB R14
```

* Size: 6 words.
* Changes: R14 and R15. Flags are untouched.

`CALL` and `RET` are not the same as `STK CALL` and `STK RET`: the `STK` forms
only move the stack frame and never jump.


## 8. Names

Labels and constants start with a letter or `_`, followed by letters, digits
or `_`. They can't be a register name (`R3`) or a mnemonic (`add`, `int`,
`call`), in any capitalisation.

Names beginning with `__` are reserved for the assembler.


## 9. Examples

### Print a-z (one file)

```
; print a-z
        .equ DISPLAY, 0x5C
        .global start

start:  DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R1, 'a'
loop:   COMM OUTDATA, R1
        ++ R1               ; R0 = R1 + 1
        CPY R0, R1          ; move it back into R1
        CMP R1, #'z' + 1
        RJNF Z, loop        ; keep going until R1 passes 'z'
        HALT
```

### Two files, a function, and RAM

`lib.asm`:

```
        .global print_newline

print_newline:
        DATA R1, 0x5C
        COMM OUTADDR, R1
        DATA R1, '\n'
        COMM OUTDATA, R1
        RET
```

`main.asm`:

```
        .extern print_newline
        .global start

        .ram
count:  .space 1            ; one word of RAM

        .rom
start:  DATA R3, count
        DATA R1, 7
        ST R3, R1           ; count = 7
        CALL print_newline
        HALT
```


## 10. Using the tools

Run everything from the project root. `python src/asm` works the same way as
`python src/main.py` does for the simulator.

Build a program in one step (assemble every file, then link):

```
python src/asm build examples/asm/hello.asm
python src/asm build main.asm lib.asm -o program.rom
```

The ROM image is written next to the first file with a `.rom` ending, or to the
name given with `-o`. Load it in the simulator like any other ROM:

```
python src/main.py examples/asm/hello.rom
```

Or do the two steps separately, for example to keep a library assembled:

```
python src/asm assemble lib.asm              # writes lib.obj
python src/asm link main.obj lib.obj -o program.rom
python src/asm build main.asm lib.obj        # build takes .asm and .obj
```

Add `--map` to `build` or `link` to also write a `.map` file listing every
label's final address, which helps when stepping through the simulator.

Errors report the file and line, and nothing is written when there are any:

```
main.asm:12: unknown name 'prnt_newline' (a typo, or a missing .extern?)
1 error(s), nothing written
```

Object files (`.obj`) are JSON, so you can open one to see the words, labels
and the relocations the linker will fill in.

Check the tools themselves with:

```
python src/asm/selftest.py
```
