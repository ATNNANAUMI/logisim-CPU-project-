"""The instruction set as tables.

An instruction word is   prefix << 12 | opcode << 8 | RA << 4 | RB

The prefix picks the group: 0 system, 1 integer ALU, 3 float ALU. Adding 4
(bit 14) turns on immediate mode for the ALU groups: 5 is integer with an
immediate, 7 is float with an immediate.
"""

SYSTEM = 0
INT_ALU = 1
FLOAT_ALU = 3
IMMEDIATE = 4


def word(prefix, opcode, ra=0, rb=0):
    """Build one instruction word."""
    return (prefix << 12) | (opcode << 8) | (ra << 4) | rb


# Operand shapes:
#   none      no operands                    1 word
#   ra_rb     RA, RB                         1 word
#   rb        RB                             1 word
#   rb_value  RB, value                      2 words
#   jump      label                          2 words
#   flagjump  flags, label                   2 words
#   comm      sub-operation, RB              1 word
#   stk       sub-operation [, RB]           1 word
#   alu2      RA, RB   or   RA, #value       1 or 2 words
#   alu1      RB                             1 word

# System instructions: mnemonic -> (opcode, shape)
SYSTEM_OPS = {
    "NOP":  (0x0, "none"),
    "LD":   (0x1, "ra_rb"),
    "ST":   (0x2, "ra_rb"),
    "DATA": (0x3, "rb_value"),
    "RJMP": (0x4, "jump"),
    "RJF":  (0x5, "flagjump"),
    "RJNF": (0x6, "flagjump"),
    "CLF":  (0x7, "none"),
    "COMM": (0x8, "comm"),
    "ADDR": (0x9, "rb"),
    "JMRB": (0xA, "rb"),
    "STK":  (0xB, "stk"),
    "ALD":  (0xC, "ra_rb"),
    "AST":  (0xD, "ra_rb"),
    "CPY":  (0xE, "ra_rb"),
    "HALT": (0xF, "none"),
}

TWO_WORD_SHAPES = {"rb_value", "jump", "flagjump"}

# COMM sub-operations, stored in the RA field.
COMM_OPS = {"INDATA": 0, "INADDR": 1, "OUTDATA": 2, "OUTADDR": 3}

# STK sub-operations, stored in the RA field: name -> (code, takes a register)
STK_OPS = {
    "PUSH": (0, False),
    "POP":  (1, False),
    "CALL": (2, False),
    "RET":  (3, False),
    "SET":  (4, True),
    "GET":  (5, True),
}

# ALU instructions: mnemonic -> (prefix, opcode, shape)
ALU_OPS = {
    "ADD":   (INT_ALU, 0x0, "alu2"),
    "SUB":   (INT_ALU, 0x1, "alu2"),
    "MULT":  (INT_ALU, 0x2, "alu2"),
    "DIV":   (INT_ALU, 0x3, "alu2"),
    "SHL":   (INT_ALU, 0x4, "alu1"),
    "SHR":   (INT_ALU, 0x5, "alu1"),
    "NOT":   (INT_ALU, 0x6, "alu1"),
    "AND":   (INT_ALU, 0x7, "alu2"),
    "OR":    (INT_ALU, 0x8, "alu2"),
    "XOR":   (INT_ALU, 0x9, "alu2"),
    "MOD":   (INT_ALU, 0xA, "alu2"),
    "++":    (INT_ALU, 0xB, "alu1"),
    "INC":   (INT_ALU, 0xB, "alu1"),
    "--":    (INT_ALU, 0xC, "alu1"),
    "DEC":   (INT_ALU, 0xC, "alu1"),
    "NEG":   (INT_ALU, 0xD, "alu1"),
    "TEST":  (INT_ALU, 0xE, "alu1"),
    "CMP":   (INT_ALU, 0xF, "alu2"),

    "FADD":  (FLOAT_ALU, 0x0, "alu2"),
    "FSUB":  (FLOAT_ALU, 0x1, "alu2"),
    "FMULT": (FLOAT_ALU, 0x2, "alu2"),
    "FDIV":  (FLOAT_ALU, 0x3, "alu2"),
    "FLOAT": (FLOAT_ALU, 0x6, "alu1"),
    "INT":   (FLOAT_ALU, 0x7, "alu1"),
    "FNEG":  (FLOAT_ALU, 0xD, "alu1"),
    "FCMP":  (FLOAT_ALU, 0xF, "alu2"),
}

# Pseudo-instructions, expanded by the assembler: mnemonic -> size in words
PSEUDO_OPS = {"CALL": 7, "RET": 6}

# Flag letters for RJF / RJNF, as bits of the RB field (order C A N Z)
FLAGS = {"C": 0b1000, "A": 0b0100, "N": 0b0010, "Z": 0b0001}

MNEMONICS = set(SYSTEM_OPS) | set(ALU_OPS) | set(PSEUDO_OPS)

# How each shape is written, for error messages
USAGE = {
    "none":     "{op}",
    "ra_rb":    "{op} RA, RB",
    "rb":       "{op} RB",
    "rb_value": "{op} RB, value",
    "jump":     "{op} label",
    "flagjump": "{op} flags, label   (flags are letters from C A N Z, like Z or NZ)",
    "comm":     "{op} INDATA|INADDR|OUTDATA|OUTADDR, RB",
    "stk":      "{op} PUSH|POP|CALL|RET   or   {op} SET|GET, RB",
    "alu2":     "{op} RA, RB   or   {op} RA, #value",
    "alu1":     "{op} RB",
}


def sys_word(name, ra=0, rb=0):
    """A system instruction word, e.g. sys_word("CPY", 0, 15) is CPY R0, R15."""
    return word(SYSTEM, SYSTEM_OPS[name][0], ra, rb)


def stk_word(name, rb=0):
    """A stack instruction word, e.g. stk_word("PUSH")."""
    return word(SYSTEM, SYSTEM_OPS["STK"][0], STK_OPS[name][0], rb)
