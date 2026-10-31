"""The control section of CPU.circ as a microcode ROM.

    python logisim/microcode/microcode.py [-o microcode.rom] [--list]

writes a 64K x 32 Logisim ROM image ("v2.0 raw") that replaces the gates of
CONTROL_SECTION: its decoders, its 4-to-16 step decoder and its ~150 AND/OR
gates. The table below was read off the circuit and verify.py checks the
image against the circuit's gates (every IR, step and flag value). --list
prints the table, one line per instruction and step.

Address (16 bits)
    A15..A9  IR[14:8]  IMM, FLOAT, ALU, opcode
    A8..A6   IR[6:4]   low 3 bits of RA (the STK / COMM sub-operation)
    A5..A2   step      the stepper count
    A1       JF        OR of (IR[3:0] AND flags)       flags as C=8 A=4 N=2 Z=1
    A0       JNF       OR of (IR[3:0] AND NOT flags)
IR[15] and IR[7] are not used by the control section. JF and JNF only matter
for RJF and RJNF.

Data (32 bits). Outside the ROM every bit is ANDed with the stepper's enable
output (what enables the step decoder today), the set lines also with clk_s
and the enable lines with clk_e (the CLOCK subcircuit's short and long phases):

    bit  name      pin of CONTROL_SECTION   gated by
    0    MAR       MAR                      clk_s
    1    IAR       IAR                      clk_s   IAR loads the bus
    2    IAR_INC   IAR_136508e1             clk_s   IAR counts up
    3    IR        IR                       clk_s
    4    TMP       TMP                      clk_s
    5    ACC_S     ACC_S                    clk_s
    6    FLAG      FLAG                     clk_s
    7    RAM_S     RAM_S                    clk_s
    8    STACK_S   STACK_S                  clk_s
    9    IO_S      I_O_CLK_S                clk_s
    10   IAR_E     IAR_E                    clk_e
    11   RAM       RAM                      clk_e
    12   ACC       ACC                      clk_e
    13   ARR_E     ARR_E                    clk_e
    14   STACK_E   STACK_E                  clk_e
    15   IO_E      I_O_CLK_E                clk_e
    16   BUS_1     bus_1                    clk_e
    17-18 W        16-bit register set      clk_s   0 none, 1 RA, 2 RB, 3 R0
    19-20 R        16-bit register enable   clk_e   0 none, 1 RA, 2 RB, 3 R0
    21   STEP_RST  stepper reset input      -       end of the instruction
    22   BUS_IN    in                       -
    23   BUS_OUT   out                      -
    24-27 STK      STACK_OP (4 bits)        -
    28   ALU       ALU operation bit 5      -       ORed with IR[14] and IR[12] after the gate
    29   OP        ALU operation bits 3..0 = IR[11:8] (else 0)
    30   HALT_SET  preset of the halt flip-flop
    31   STEP0     step 0 (the IAR reset gate: RESET AND NOT (halt AND step 0))

The register codes go through a 4-bit multiplexer (RA = IR[7:4], RB = IR[3:0],
R0 = 0) into a 4-to-16 decoder whose enable is "code != 0". ALU operation bit 5
is (bit 28 AND the stepper enable) OR IR[14] OR IR[12]: the ALU groups ask for
the ALU straight from the IR, the ROM only for the jumps' step 3. Bit 4 is
IR[13] (FLOAT) straight from the IR. DATA_ADDRESS is IR[4] and INPUT_OUTPUT
is IR[5]. Kept as gates: CLOCK, the stepper, the halt flip-flop and the OR that
makes halt_output (HALT pin, RESET, flip-flop), the clock gate in front of
CLOCK, and the IAR reset gate.

Each instruction is a list of steps after the two fetch steps; a step is a
string of the names above, plus W=RA/RB/R0, R=RA/RB/R0 and STK=n. Steps after
STEP_RST never run, so the table leaves them empty (verify.py does not
compare them).
"""
import argparse
import os
import sys

SET = ["MAR", "IAR", "IAR_INC", "IR", "TMP", "ACC_S", "FLAG", "RAM_S", "STACK_S", "IO_S"]
ENABLE = ["IAR_E", "RAM", "ACC", "ARR_E", "STACK_E", "IO_E", "BUS_1"]
BIT = {name: i for i, name in enumerate(SET + ENABLE)}
BIT.update(STEP_RST=21, BUS_IN=22, BUS_OUT=23, ALU=28, OP=29, HALT_SET=30, STEP0=31)
W_SHIFT, R_SHIFT, STK_SHIFT = 17, 19, 24
REG = {"RA": 1, "RB": 2, "R0": 3}

FETCH = ["IAR_E MAR BUS_OUT STEP0",       # step 0: IAR -> MAR
         "IAR_INC IR RAM BUS_IN"]         # step 1: memory -> IR, IAR + 1

# IMM = 0, ALU = 0: opcode -> (mnemonic, steps 2...). FLOAT (IR[13]) changes
# nothing here but the ALU operation's bit 4.
JUMP = ["IAR_E MAR TMP BUS_OUT",          # TMP = address of the offset word
        "IAR_INC RAM BUS_IN ACC_S ALU"]   # ACC = TMP + offset, IAR + 1
SYSTEM = {
    0x0: ("NOP", ["STEP_RST"]),
    0x1: ("LD", ["MAR BUS_OUT R=RA",
                 "RAM BUS_IN W=RB STEP_RST"]),
    0x2: ("ST", ["MAR BUS_OUT R=RA",
                 "RAM_S BUS_OUT R=RB STEP_RST"]),
    0x3: ("DATA", ["IAR_E MAR BUS_OUT",
                   "RAM BUS_IN W=RB",
                   "IAR_INC STEP_RST"]),
    0x4: ("RJMP", JUMP + ["ACC IAR BUS_IN STEP_RST"]),
    0x5: ("RJF", JUMP + [{"JF": "ACC IAR BUS_IN STEP_RST", "": "STEP_RST"}]),
    0x6: ("RJNF", JUMP + [{"JNF": "ACC IAR BUS_IN STEP_RST", "": "STEP_RST"}]),
    0x7: ("CLF", ["FLAG BUS_1 STEP_RST"]),
    # COMM: INDATA (RA[1:0] = 0) reads a device into RB; INADDR, OUTDATA and
    # OUTADDR send RB to the devices, which see IR[4] (DATA_ADDRESS) and
    # IR[5] (INPUT_OUTPUT).
    0x8: ("COMM", {0: ["", "IO_E BUS_IN W=RB STEP_RST"],
                   1: ["IO_S BUS_OUT R=RB STEP_RST"]}),
    0x9: ("ADDR", ["IAR_E W=RB STEP_RST"]),
    0xA: ("JMRB", ["IAR BUS_IN R=RB STEP_RST"]),
    # STK: RA[2:0] picks the operation (PUSH POP CALL RET SET GET, 6 and 7
    # unused); STK=n is the 4-bit STACK_OP to the RAM subcircuit
    0xB: ("STK", {0: ["STACK_E STACK_S BUS_OUT STK=2 R=R0",
                      "STACK_E STACK_S STK=4 STEP_RST"],
                  1: ["STACK_E STACK_S STK=5",
                      "STACK_E STACK_S BUS_IN STK=9 W=R0 STEP_RST"],
                  2: ["STACK_E STACK_S STK=3",
                      "STACK_E STACK_S STK=6",
                      "STACK_E STACK_S STK=4 STEP_RST"],
                  3: ["STACK_E STACK_S STK=7",
                      "STACK_E STACK_S STEP_RST"],
                  4: ["STACK_E STACK_S BUS_OUT STK=8 R=RB",
                      "RAM_S BUS_OUT R=R0 STEP_RST"],
                  5: ["STACK_E STACK_S BUS_OUT STK=8 R=RB",
                      "STACK_E STACK_S BUS_IN STK=1 W=R0 STEP_RST"],
                  6: ["STACK_E STACK_S",
                      "STACK_E STACK_S STEP_RST"],
                  7: ["STACK_E STACK_S",
                      "STACK_E STACK_S STEP_RST"]}),
    0xC: ("ALD", ["MAR BUS_OUT R=RA",
                  "ARR_E STACK_S BUS_OUT R=RB",
                  "RAM BUS_IN W=R0 STEP_RST"]),
    0xD: ("AST", ["MAR BUS_OUT R=RA",
                  "ARR_E STACK_S BUS_OUT R=RB",
                  "RAM_S BUS_OUT R=R0 STEP_RST"]),
    0xE: ("CPY", ["R=RA W=RB STEP_RST"]),
    0xF: ("HALT", ["HALT_SET STEP_RST"]),
}
# IMM = 0, ALU = 1: R0 = RA op RB
ALU_RR = ["TMP R=RB",
          "ACC_S FLAG OP R=RA",
          "ACC W=R0 STEP_RST"]
# opcode F (CMP / FCMP) stops after the flags: no R0 write and no STEP_RST,
# so the stepper runs to step 15 and wraps around to the next fetch.
ALU_CMP = ALU_RR[:2]
# IMM = 1 (IR[12] ignored): R0 = RA op immediate
ALU_IMM = ["IAR_E MAR BUS_OUT",
           "IAR_INC RAM TMP BUS_IN OP",
           "ACC_S FLAG OP R=RA",
           "ACC W=R0 STEP_RST"]

ALU_NAMES = "ADD SUB MULT DIV MOD AND OR XOR NOT SHL SHR ++ -- NEG TEST CMP".split()
SUB_NAMES = {0x8: ["INDATA", "INADDR / OUTDATA / OUTADDR"],
             0xB: "PUSH POP CALL RET SET GET (6) (7)".split()}


def program(op7, ra3):
    """(name, steps 2...) of the instruction IR[14:8] = op7."""
    imm, alu, opcode = op7 >> 6 & 1, op7 >> 4 & 1, op7 & 0xF
    if imm:
        return f"{ALU_NAMES[opcode]} imm", ALU_IMM
    if alu:
        return ALU_NAMES[opcode], ALU_CMP if opcode == 0xF else ALU_RR
    name, steps = SYSTEM[opcode]
    if isinstance(steps, dict):
        key = ra3 if opcode == 0xB else int(ra3 & 3 != 0)
        name, steps = f"{name} {SUB_NAMES[opcode][key]}", steps[key]
    return name, steps


def encode(text):
    word = 0
    for tok in text.split():
        if tok.startswith(("W=", "R=")):
            word |= REG[tok[2:]] << (W_SHIFT if tok[0] == "W" else R_SHIFT)
        elif tok.startswith("STK="):
            word |= int(tok[4:]) << STK_SHIFT
        else:
            word |= 1 << BIT[tok]
    return word


def word(op7, ra3, step, jf, jnf):
    _, steps = program(op7, ra3)
    seq = FETCH + steps
    text = seq[step] if step < len(seq) else ""
    if isinstance(text, dict):
        text = text["JF"] if jf and "JF" in text else text["JNF"] if jnf and "JNF" in text else text[""]
    return encode(text)


def address(op7, ra3, step, jf, jnf):
    return op7 << 9 | ra3 << 6 | step << 2 | jf << 1 | jnf


def table():
    words = [0] * 0x10000
    for op7 in range(128):
        for ra3 in range(8):
            for step in range(16):
                for jf in (0, 1):
                    for jnf in (0, 1):
                        words[address(op7, ra3, step, jf, jnf)] = word(op7, ra3, step, jf, jnf)
    return words


def outputs(w, ir, flags, stepbit=1, clk_s=1, clk_e=1):
    """What CONTROL_SECTION's pins show for ROM word w: the gates outside the ROM.
    flags = C<<3 | A<<2 | N<<1 | Z. Returns {pin label: value} (verify.py's model)."""
    if not stepbit:
        w = 0
    s = {n: (w >> BIT[n] & 1) & clk_s for n in SET}
    e = {n: (w >> BIT[n] & 1) & clk_e for n in ENABLE}
    out = {"MAR": s["MAR"], "IAR": s["IAR"], "IAR_136508e1": s["IAR_INC"], "IR": s["IR"],
           "TMP": s["TMP"], "ACC_S": s["ACC_S"], "FLAG": s["FLAG"], "RAM_S": s["RAM_S"],
           "STACK_S": s["STACK_S"], "I_O_CLK_S": s["IO_S"],
           "IAR_E": e["IAR_E"], "RAM": e["RAM"], "ACC": e["ACC"], "ARR_E": e["ARR_E"],
           "STACK_E": e["STACK_E"], "I_O_CLK_E": e["IO_E"], "bus_1_bfd35e32": e["BUS_1"]}
    regs = {1: ir >> 4 & 0xF, 2: ir & 0xF, 3: 0}
    wcode, rcode = w >> W_SHIFT & 3, w >> R_SHIFT & 3
    out["pin(1750,1220)"] = 1 << regs[wcode] if wcode and clk_s else 0
    out["pin(310,1490)"] = 1 << regs[rcode] if rcode and clk_e else 0
    out["P_STEPIN1"] = w >> BIT["STEP_RST"] & 1
    out["in"] = w >> BIT["BUS_IN"] & 1
    out["out"] = w >> BIT["BUS_OUT"] & 1
    out["P_HALTSET"] = w >> BIT["HALT_SET"] & 1
    out["P_STEP0"] = w >> BIT["STEP0"] & 1
    out["STACK_OP_a5e0941b"] = w >> STK_SHIFT & 0xF
    alu = w >> BIT["ALU"] & 1 | ir >> 14 & 1 | ir >> 12 & 1
    out["pin(530,2400)"] = (alu << 5 | (ir >> 13 & 1) << 4
                            | ((ir >> 8 & 0xF) if w >> BIT["OP"] & 1 else 0))
    out["DATA_ADDRESS_6059bfda"] = ir >> 4 & 1
    out["INPUT_OUTPUT_5ddf5234"] = ir >> 5 & 1
    return out


def rom_address(ir, step, flags):
    mask = ir & 0xF
    jf, jnf = int(mask & flags != 0), int(mask & ~flags & 0xF != 0)
    return address(ir >> 8 & 0x7F, ir >> 4 & 7, step, jf, jnf)


def decode(w):
    """ROM word -> the step's text, for --list."""
    names = [n for n, b in sorted(BIT.items(), key=lambda x: x[1]) if w >> b & 1]
    codes = {v: k for k, v in REG.items()}
    if w >> W_SHIFT & 3: names.append("W=" + codes[w >> W_SHIFT & 3])
    if w >> R_SHIFT & 3: names.append("R=" + codes[w >> R_SHIFT & 3])
    if w >> STK_SHIFT & 0xF: names.append(f"STK={w >> STK_SHIFT & 0xF}")
    return " ".join(names)


def listing(words):
    lines = []
    for op7 in range(128):
        for ra3 in range(8):
            name, _ = program(op7, ra3)
            if ra3 and not (op7 & 0x50 == 0 and op7 & 0xF in (0x8, 0xB)):
                continue                  # RA only matters for COMM and STK
            if op7 & 0x50 == 0 and op7 & 0xF == 0x8 and ra3 > 1:
                continue
            lines.append(f"IR[14:8]={op7:02x} RA[2:0]={ra3}  {name}")
            last = 0
            for step in range(16):
                ws = {words[address(op7, ra3, step, jf, jnf)] for jf in (0, 1) for jnf in (0, 1)}
                if len(ws) == 1:
                    lines.append(f"  {step:2}  {decode(ws.pop())}")
                else:
                    for jf, jnf in ((1, 0), (0, 1), (0, 0)):
                        lines.append(f"  {step:2}  JF={jf} JNF={jnf}: "
                                     f"{decode(words[address(op7, ra3, step, jf, jnf)])}")
                if words[address(op7, ra3, step, 0, 0)] >> BIT["STEP_RST"] & 1:
                    break
    return "\n".join(lines)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-o", default=os.path.join(here, "microcode.rom"), help="output ROM image")
    ap.add_argument("--list", action="store_true", help="print the table instead")
    args = ap.parse_args()
    words = table()
    if args.list:
        print(listing(words))
        return
    sys.path.insert(0, os.path.join(here, "..", "..", "compiler", "src", "asm"))
    from linker import format_raw
    with open(args.o, "w") as f:
        f.write(format_raw(words))
    print(f"wrote {args.o} (64K x 32)")


if __name__ == "__main__":
    main()
