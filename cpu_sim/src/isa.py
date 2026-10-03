"""Instruction encoding, decoding and disassembly.

Layout (15 significant bits inside a 32-bit word, upper bits ignored):

    bit14  immediate  (operand is the next word in memory, RB unused)
    bit13  float group
    bit12  1 = ALU instruction, 0 = system instruction
    11..8  opcode
     7..4  RA field
     3..0  RB field

    000 ....  system      011 ....  float ALU
    001 ....  int ALU     101 ....  int ALU, immediate
                          111 ....  float ALU, immediate
"""

from dataclasses import dataclass

IMM_BIT = 1 << 14
FLOAT_BIT = 1 << 13
ALU_BIT = 1 << 12

SYS_OPS = {
    0x0: "NOP", 0x1: "LD", 0x2: "ST", 0x3: "DATA",
    0x4: "RJMP", 0x5: "RJF", 0x6: "RJNF", 0x7: "CLF",
    0x8: "COMM", 0x9: "ADDR", 0xA: "JMRB", 0xB: "STK",
    0xC: "ALD", 0xD: "AST", 0xE: "CPY", 0xF: "HALT",
}

INT_OPS = {
    0x0: "ADD", 0x1: "SUB", 0x2: "MULT", 0x3: "DIV",
    0x4: "SHL", 0x5: "SHR", 0x6: "NOT", 0x7: "AND",
    0x8: "OR", 0x9: "XOR", 0xA: "MOD", 0xB: "INC",
    0xC: "DEC", 0xD: "NEG", 0xE: "TEST", 0xF: "CMP",
}

FLOAT_OPS = {
    0x0: "ADD", 0x1: "SUB", 0x2: "MULT", 0x3: "DIV",
    0x4: "SHL", 0x5: "SHR", 0x6: "FLOAT", 0x7: "INT",
    0x8: "???", 0x9: "???", 0xA: "???", 0xB: "INC",
    0xC: "DEC", 0xD: "NEG", 0xE: "???", 0xF: "CMP",
}

# ALU instructions whose only operand is RB (RA is still read for the A flag)
ONE_OPERAND = {"SHL", "SHR", "NOT", "INC", "DEC", "NEG", "TEST", "FLOAT", "INT"}

STK_OPS = {0: "PUSH", 1: "POP", 2: "CALL", 3: "RET", 4: "SET", 5: "GET"}
COMM_OPS = {0: "INDATA", 1: "INADDR", 2: "OUTDATA", 3: "OUTADDR"}

FLAG_NAMES = ("C", "A", "N", "Z")          # bit3 .. bit0
FLAG_BITS = {"C": 0b1000, "A": 0b0100, "N": 0b0010, "Z": 0b0001}

# system instructions that consume the following word
TAKES_OPERAND = {"DATA", "RJMP", "RJF", "RJNF"}


@dataclass(frozen=True)
class Instr:
    word: int
    name: str
    is_alu: bool
    is_float: bool
    is_imm: bool
    op: int
    ra: int
    rb: int

    @property
    def takes_operand(self) -> bool:
        """True when the instruction is followed by a literal word."""
        if self.is_alu:
            return self.is_imm
        return self.name in TAKES_OPERAND


def decode(word: int) -> Instr:
    w = word & 0x7FFF
    op = (w >> 8) & 0xF
    ra = (w >> 4) & 0xF
    rb = w & 0xF
    is_alu = bool(w & ALU_BIT)
    is_float = bool(w & FLOAT_BIT)
    is_imm = bool(w & IMM_BIT)

    if is_alu:
        name = (FLOAT_OPS if is_float else INT_OPS)[op]
    else:
        name = SYS_OPS[op]
        is_float = is_imm = False
    return Instr(word, name, is_alu, is_float, is_imm, op, ra, rb)


def flag_list(nibble: int) -> str:
    return "".join(n for n in FLAG_NAMES if nibble & FLAG_BITS[n]) or "-"


def disassemble(word: int, operand: int | None = None) -> str:
    """Human-readable form of one instruction."""
    ins = decode(word)
    lit = "" if operand is None else f" 0x{operand:X}"

    if ins.is_alu:
        tag = "F" if ins.is_float else ""
        if ins.is_imm:
            b = f"#{operand if operand is not None else '?'}"
        else:
            b = f"R{ins.rb}"
        if ins.name in ONE_OPERAND:
            return f"{tag}{ins.name} {b}"
        return f"{tag}{ins.name} R{ins.ra},{b}"

    n = ins.name
    if n in ("NOP", "CLF", "HALT"):
        return n
    if n in ("LD", "ST", "ALD", "AST", "CPY"):
        return f"{n} R{ins.ra},R{ins.rb}"
    if n == "DATA":
        return f"DATA R{ins.rb},{lit.strip() or '?'}"
    if n == "RJMP":
        return f"RJMP{lit}"
    if n in ("RJF", "RJNF"):
        return f"{n} {flag_list(ins.rb)}{lit}"
    if n == "COMM":
        return f"COMM {COMM_OPS[ins.ra & 3]},R{ins.rb}"
    if n == "STK":
        return f"STK {STK_OPS.get(ins.ra & 7, '???')},R{ins.rb}"
    if n in ("ADDR", "JMRB"):
        return f"{n} R{ins.rb}"
    return n
