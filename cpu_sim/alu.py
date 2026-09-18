"""The ALU: integer ops, float ops, and the C A N Z flags.

Every ALU instruction writes its result to R0 and rewrites all four flags.

    C  unsigned carry out of the adder
    A  RA > RB (the two ALU inputs)
    N  result < 0
    Z  result == 0
"""

import math
import struct

import config as config

MASK = config.WORD_MASK
SIGN = config.SIGN_BIT

INF_BITS = 0x7F800000
NEG_INF_BITS = 0xFF800000


# ------------------------------------------------------------- conversions
def to_signed(value: int) -> int:
    value &= MASK
    return value - (1 << 32) if value & SIGN else value


def bits_to_float(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & MASK))[0]


def float_to_bits(value: float) -> int:
    if math.isnan(value):
        return 0x7FC00000
    try:
        return struct.unpack("<I", struct.pack("<f", value))[0]
    except OverflowError:                       # bigger than float32 range
        return INF_BITS if value > 0 else NEG_INF_BITS


# -------------------------------------------------------------------- flags
def pack_flags(c: int, a: int, n: int, z: int) -> int:
    return (bool(c) << 3) | (bool(a) << 2) | (bool(n) << 1) | bool(z)


def _a_flag(a: int, b: int) -> bool:
    if config.A_FLAG_SIGNED:
        return to_signed(a) > to_signed(b)
    return (a & MASK) > (b & MASK)


def _int_flags(a: int, b: int, flag_value: int, carry: bool) -> int:
    v = flag_value & MASK
    return pack_flags(carry, _a_flag(a, b), v & SIGN, v == 0)


def _float_flags(fa: float, fb: float, result: float) -> int:
    return pack_flags(False, fa > fb, result < 0, result == 0)


# --------------------------------------------------------------- integer op
def int_op(name: str, a: int, b: int) -> tuple[int, int]:
    """Return (value written to R0, flag nibble).  a = RA, b = RB/immediate."""
    a &= MASK
    b &= MASK
    sa, sb = to_signed(a), to_signed(b)
    carry = False
    flag_value = None                            # defaults to the result

    if name == "ADD":
        total = a + b
        carry, result = total > MASK, total & MASK
    elif name == "SUB":
        total = a + (~b & MASK) + 1              # carry out = no borrow
        carry, result = total > MASK, total & MASK
    elif name == "MULT":
        product = sa * sb
        carry = not (-(1 << 31) <= product <= (1 << 31) - 1)
        result = product & MASK
    elif name == "DIV":
        result = a if sb == 0 else _divide(sa, sb)[0] & MASK
    elif name == "MOD":
        result = a if sb == 0 else _divide(sa, sb)[1] & MASK
    elif name == "SHL":
        carry, result = bool(b & SIGN), (b << 1) & MASK
    elif name == "SHR":
        carry = bool(b & 1)
        result = ((b >> 1) | (b & SIGN)) if config.SHR_ARITHMETIC else b >> 1
    elif name == "NOT":
        result = ~b & MASK
    elif name == "AND":
        result = a & b
    elif name == "OR":
        result = a | b
    elif name == "XOR":
        result = a ^ b
    elif name == "INC":
        total = b + 1
        carry, result = total > MASK, total & MASK
    elif name == "DEC":
        total = b + MASK                         # b + (-1)
        carry, result = total > MASK, total & MASK
    elif name == "NEG":
        total = (~b & MASK) + 1
        carry, result = total > MASK, total & MASK
    elif name == "TEST":
        result = b
    elif name == "CMP":
        total = a + (~b & MASK) + 1              # flags from RA - RB ...
        carry, flag_value = total > MASK, total & MASK
        result = 0                               # ... but R0 gets 0
    else:
        result = 0

    if flag_value is None:
        flag_value = result
    return result & MASK, _int_flags(a, b, flag_value, carry)


def _divide(sa: int, sb: int) -> tuple[int, int]:
    if config.DIV_TRUNCATE:
        q = abs(sa) // abs(sb)
        if (sa < 0) != (sb < 0):
            q = -q
        return q, sa - q * sb
    return sa // sb, sa % sb


# ----------------------------------------------------------------- float op
def float_op(name: str, a: int, b: int) -> tuple[int, int]:
    """Float group.  a = RA bits, b = RB/immediate bits."""
    a &= MASK
    b &= MASK
    fa, fb = bits_to_float(a), bits_to_float(b)

    if name in ("ADD", "SUB", "MULT", "DIV"):
        if name == "ADD":
            value = fa + fb
        elif name == "SUB":
            value = fa - fb
        elif name == "MULT":
            value = fa * fb
        else:
            value = math.copysign(math.inf, fa) if fb == 0 else fa / fb
        bits = float_to_bits(value)
        return bits, _float_flags(fa, fb, bits_to_float(bits))

    if name == "FLOAT":                          # int -> float
        bits = float_to_bits(float(to_signed(b)))
        return bits, _float_flags(fa, fb, bits_to_float(bits))

    if name == "INT":                            # float -> int
        if math.isnan(fb) or math.isinf(fb):
            value = 0
        else:
            value = int(fb)
        bits = value & MASK
        return bits, pack_flags(False, fa > fb, bits & SIGN, bits == 0)

    if name == "NEG":
        bits = float_to_bits(-fb)
        return bits, _float_flags(fa, fb, bits_to_float(bits))

    if name == "CMP":
        return 0, _float_flags(fa, fb, 0.0)

    # SHL, SHR, ++, -- and the undefined opcodes: do nothing
    value = config.FLOAT_NOP_RESULT & MASK
    return value, pack_flags(False, fa > fb, value & SIGN, value == 0)
