# ISA Encoding Reference (v2 — corrected after testing `abs_value`)

## Word format

Each memory cell is **32 bits wide** (registers are 32-bit, and `DATA`
literals are full 32-bit values, e.g. `-5` = `fffffffb`). Instructions still
only use the low 16 bits of meaning; the raw hex dump just doesn't zero-pad
small positive values, which is why instruction words print as 4 hex digits
while negative/large literals print as 8.

```
bit15        bits14-12     bits11-8      bits7-4       bits3-0
[reserved=0] [ category ]  [  opcode  ]  [    RA    ]  [    RB    ]
```

- category: `000` control, `001` int arithmetic, `011` float arithmetic
  (leading don't-care bit fixed to 0 → nibble1 = 0x0 / 0x1 / 0x3)
- RA/RB: 4-bit register index (R0–R15) — unaffected by the 32-bit data width,
  it's still just a register *selector*.

### Immediate / offset words
`DATA`, `RJMP`, `RJF`, `RJNF` are followed by one literal 32-bit word.

### ⚠️ Relative jump addressing (corrected)
**Target address = (address of the offset word itself) + offset value.**
*Not* "address after the offset word + offset" as I originally assumed —
confirmed by the working `abs_value` fix (`RJNF` at addr 3, offset word at
addr 4, target `DATA R0` at addr 7 → offset = 7 − 4 = **3**).

### Result-register rule (unchanged)
- `ADD, SUB, MULT, DIV` → result into **RB**.
- `AND, OR, XOR, MOD, SHL, SHR, NOT, TEST, ++, --, NEG` → result into **R0**.
- `CMP` → flags only.

### Flags (`CAEZ`) — mostly still unverified
- `TEST RB` (see below) sets the flag tested with mask `0010` when RB is
  zero-or-negative. **This part is confirmed** (from your fix).
- `CMP` presumably sets a "zero/equal" flag tested with mask `0001` for
  loop-termination-on-equality — this is my **original unverified guess**,
  carried forward unchanged; not yet confirmed by you.
- Carry-from-`SHL`/`SHR`, mask `1000` — also still just an assumption from
  the original doc, unconfirmed.

### I/O (`COMM I/O-D/A,RB`) — confirmed against `print_a-z`
RA field = `00yy`: `11` = output address, `10` = output data (`01`/`00` =
input, by symmetry, unconfirmed).

### Console is ASCII
The display expects ASCII byte values, not raw numbers. Any numeric result
you want to *see* as a number needs `+0x30` per digit (and digit-splitting
via `DIV`/`MOD` by 10 for multi-digit results) before sending it to `COMM`.

## Opcode hex values by mnemonic

### Category 000 (control) — nibble1 = 0x0
| opcode | mnemonic |
|---|---|
| 0 | NOP | 1 | LD | 2 | ST | 3 | DATA | 4 | RJMP | 5 | RJF | 6 | RJNF |
| 7 | CLF | 8 | COMM | 9 | ADDR | A | JMRB | B | STK | C | ALD | D | AST |
| E | CPY | F | HALT |

### Category 001 (int arithmetic) — nibble1 = 0x1
| opcode | mnemonic | result |
|---|---|---|
| 0 | ADD RA,RB | → RB |
| 1 | SUB RA,RB | → RB |
| 2 | MULT RA,RB | → RB |
| 3 | DIV RA,RB | → RB |
| 4 | SHL RB | → R0 |
| 5 | SHR RB | → R0 |
| 6 | NOT RB | → R0 |
| 7 | AND RA,RB | → R0 |
| 8 | OR RA,RB | → R0 |
| 9 | XOR RA,RB | → R0 |
| A | MOD RA,RB | → R0 |
| B | ++ RB | → R0 |
| C | -- RB | → R0 |
| D | NEG RB | → R0 |
| **E** | **TEST RB** (new) | sets flag (mask `0010`) if RB ≤ 0, → R0 |
| F | CMP RA,RB | flags only |

(Category `011`, nibble1=0x3, mirrors this for float ops.)

## Status key for the example programs
- ✅ **abs_value** — your exact tested/corrected code, unchanged.
- 🔧 the other five — updated with the same corrected rules (32-bit data,
  correct jump math, ASCII output) but **not yet run/verified**.

---

# Programs

## ✅ abs_value — abs(-5) [user-verified]
```
DATA R1        0301
#-5            fffffffb
TEST R1        1e01      ; flag set if R1<=0
RJNF flag      0602      ; if flag OFF (positive), skip negation
#3             0003
NEG R1         1d01
CPY R0,R1      0e01
DATA R0        0300
#0x5c          005c
COMM OUT-ADDR,R0  0830
COMM OUT-DATA,R1  0821
HALT           0f00
```

## 🔧 sum_a_plus_b — 5+7=12, prints "12"
```
DATA R1 #5     0301 0005
DATA R2 #7     0302 0007
ADD R1,R2      1012      ; R2=12
DATA R4 #0x30  0304 0030 ; ascii base
DATA R5 #10    0305 000a ; divisor
MOD R2,R5      1a25      ; R0 = ones digit
CPY R0,R7      0e07
DIV R2,R5      1325      ; R5 = tens digit
ADD R4,R5      1045      ; R5 = ascii tens
ADD R4,R7      1047      ; R7 = ascii ones
DATA R0 #0x5c  0300 005c
COMM OUT-ADDR,R0  0830
COMM OUT-DATA,R5  0825   ; print tens
COMM OUT-DATA,R7  0827   ; print ones
HALT           0f00
```

## 🔧 max_of_two — max(3,9)=9, prints "9"
```
DATA R1 #3     0301 0003
DATA R2 #9     0302 0009
CPY R1,R4      0e14      ; assume max=a
CPY R2,R3      0e23      ; temp=b
SUB R4,R3      1143      ; temp = a-b
TEST R3        1e03      ; flag set if a-b<=0 (a<=b)
RJNF flag      0602      ; if flag OFF (a>b), skip reassigning max
#2             0002
CPY R2,R4      0e24      ; else max=b
DATA R5 #0x30  0305 0030
ADD R5,R4      1054      ; R4 = ascii digit
DATA R0 #0x5c  0300 005c
COMM OUT-ADDR,R0  0830
COMM OUT-DATA,R4  0824
HALT           0f00
```

## 🔧 countdown_loop — prints "54321"
```
DATA R0 #0x5c  0300 005c
COMM OUT-ADDR,R0  0830
DATA R1 #5     0301 0005
DATA R4 #0x30  0304 0030
--LOOP (addr 7)--
CPY R1,R2      0e12      ; digit copy
ADD R4,R2      1042      ; R2 = ascii digit
COMM OUT-DATA,R2  0822
-- R1          1c01      ; R0 = R1-1
CPY R0,R1      0e01
TEST R1        1e01      ; flag set if R1<=0
RJNF flag      0602      ; loop while R1>0
#-7            fffffff9  ; target = 14 - 7 = 7 (LOOP)
HALT           0f00
```

## 🔧 sum_1_to_n — sum(1..5)=15, prints "15"
```
DATA R1 #5 (N)     0301 0005
DATA R2 #0 (sum)   0302 0000
DATA R3 #0 (i)     0303 0000
--LOOP (addr 6)--
++ R3              1b03
CPY R0,R3          0e03
ADD R3,R2          1032      ; sum += i (stored in R2)
CMP R3,R1          1f31      ; i vs N   [unverified flag assumption]
RJNF zero-flag     0601      ; loop while i != N
#-5                fffffffb  ; target = 11 - 5 = 6 (LOOP)
DATA R4 #0x30      0304 0030
DATA R5 #10        0305 000a
MOD R2,R5          1a25
CPY R0,R7          0e07
DIV R2,R5          1325
ADD R4,R5          1045
ADD R4,R7          1047
DATA R0 #0x5c      0300 005c
COMM OUT-ADDR,R0   0830
COMM OUT-DATA,R5   0825
COMM OUT-DATA,R7   0827
HALT               0f00
```

## 🔧 even_or_odd — 7 AND 1 = 1 (odd), prints "1"
```
DATA R1 #7     0301 0007
DATA R2 #1     0302 0001
AND R1,R2      1712      ; R0 = 1
CPY R0,R3      0e03
DATA R4 #0x30  0304 0030
ADD R4,R3      1043      ; R3 = ascii '1'
DATA R0 #0x5c  0300 005c
COMM OUT-ADDR,R0  0830
COMM OUT-DATA,R3  0823
HALT           0f00
```
