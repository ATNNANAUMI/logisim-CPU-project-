"""Reading source text: comments, labels, operands, values and strings.

This file only cuts text into pieces. It doesn't know where labels are;
that's the assembler's job.
"""

import re
import struct

from errors import AsmError

MASK = 0xFFFFFFFF

NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LABEL_RE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:")
_MNEMONIC_RE = re.compile(r"\s*(\.?[A-Za-z_][A-Za-z0-9_]*|\+\+|--)")
_SUB_OP_RE = re.compile(r"\s*([A-Za-z]+)\s*,?(.*)$", re.DOTALL)
_REGISTER_RE = re.compile(r"[Rr]([0-9]{1,2})")

# A number must not run straight into letters, digits or a dot ("0x1G", "12ab").
_END = r"(?![A-Za-z0-9_.])"
_TOKEN_RE = re.compile(rf"""
    (?P<space>\s+)
  | (?P<char>'(?:\\.|[^'\\])*')
  | (?P<hex>0[xX][0-9A-Fa-f]+){_END}
  | (?P<bin>0[bB][01]+){_END}
  | (?P<float>(?:\d+\.\d*(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)[fF]?){_END}
  | (?P<dec>\d+){_END}
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>[+-])
""", re.VERBOSE)

ESCAPES = {"n": 0x0A, "t": 0x09, "r": 0x0D, "0": 0x00,
           "\\": 0x5C, "'": 0x27, '"': 0x22}


# ---------------------------------------------------------------- lines

def _unquoted(text):
    """Yield (index, char) for every character that isn't inside quotes."""
    quote = None
    escaped = False
    for i, ch in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        else:
            yield i, ch
    if quote:
        raise AsmError("missing closing quote")


def strip_comment(text):
    """Cut the line at the first ';' that isn't inside quotes."""
    for i, ch in _unquoted(text):
        if ch == ";":
            return text[:i]
    return text


def split_statement(text):
    """Split a comment-free line into (label, mnemonic, operand text).

    label and mnemonic are None when the line doesn't have them.
    """
    label = None
    m = _LABEL_RE.match(text)
    if m:
        label = m.group(1)
        text = text[m.end():]
    if not text.strip():
        return label, None, ""
    m = _MNEMONIC_RE.match(text)
    if not m:
        raise AsmError(f"can't read '{text.strip()}'")
    return label, m.group(1), text[m.end():].strip()


def split_operands(text):
    """Split operand text on the commas that aren't inside quotes."""
    if not text.strip():
        return []
    cuts = [i for i, ch in _unquoted(text) if ch == ","]
    parts, start = [], 0
    for cut in cuts:
        parts.append(text[start:cut].strip())
        start = cut + 1
    parts.append(text[start:].strip())
    if "" in parts:
        raise AsmError("empty operand (check the commas)")
    return parts


def split_sub_operation(text):
    """For COMM and STK: 'OUTADDR, R0' -> ('OUTADDR', ['R0']).

    The comma after the sub-operation is optional. Returns (None, []) when
    there is no sub-operation at all.
    """
    m = _SUB_OP_RE.match(text)
    if not m:
        return None, []
    return m.group(1).upper(), split_operands(m.group(2))


# ---------------------------------------------------------------- registers

def is_register(name):
    m = _REGISTER_RE.fullmatch(name)
    return bool(m) and int(m.group(1)) <= 15


def parse_register(text):
    text = text.strip()
    if not is_register(text):
        raise AsmError(f"'{text}' is not a register (R0-R15)")
    return int(text[1:])


# ---------------------------------------------------------------- strings

def _unescape(body, quote):
    """Turn the inside of a quoted literal into character codes."""
    codes = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if i + 1 >= len(body):
                raise AsmError("a quoted value can't end with a lone '\\'")
            esc = body[i + 1]
            if esc not in ESCAPES:
                raise AsmError(f"unknown escape '\\{esc}' "
                               "(use \\n \\t \\r \\0 \\\\ \\' or \\\")")
            codes.append(ESCAPES[esc])
            i += 2
        elif ch == quote:
            raise AsmError(f"unexpected {quote} inside the quotes "
                           f"(write \\{quote} to include it)")
        else:
            codes.append(ord(ch))
            i += 1
    return codes


def parse_string(text):
    """'"hi\\n"' -> [0x68, 0x69, 0x0A]. The 0 at the end is added elsewhere."""
    text = text.strip()
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        raise AsmError('expected a string in double quotes, like "hello"')
    return _unescape(text[1:-1], '"')


# ---------------------------------------------------------------- values

def float_bits(value):
    """The IEEE-754 float32 bit pattern of a number."""
    try:
        return struct.unpack(">I", struct.pack(">f", value))[0]
    except OverflowError:
        raise AsmError(f"{value} is too big for a float32") from None


class Expr:
    """A parsed value such as  'z' + 1,  buffer + 4  or  -0.25."""

    def __init__(self):
        self.number = 0          # sum of the plain numbers
        self.names = []          # (sign, name) for every name, in order
        self.float_bits = None   # set when the value is a float literal
        self.terms = 0           # how many numbers and names it has


def _tokenize(text):
    tokens, pos = [], 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise AsmError(f"can't read the value '{text.strip()}'")
        group = m.lastgroup
        assert group is not None          # every alternative in _TOKEN_RE is named
        if group != "space":
            tokens.append((group, m.group(group)))
        pos = m.end()
    return tokens


def _number(kind, token):
    if kind == "hex":
        return int(token, 16)
    if kind == "bin":
        return int(token, 2)
    if kind == "dec":
        return int(token)
    codes = _unescape(token[1:-1], "'")          # kind == "char"
    if len(codes) != 1:
        raise AsmError(f"{token} must hold exactly one character")
    return codes[0]


def parse_expression(text):
    """Parse a value: numbers and names joined by + and -."""
    tokens = _tokenize(text)
    if not tokens:
        raise AsmError("missing value")
    expr = Expr()
    sign = 1
    want_term = True
    float_value = None
    for kind, token in tokens:
        if kind == "op":
            if want_term:                       # a sign in front of a term
                if token == "-":
                    sign = -sign
            else:                               # an operator between terms
                sign = 1 if token == "+" else -1
                want_term = True
            continue
        if not want_term:
            raise AsmError(f"missing '+' or '-' before '{token}' in '{text.strip()}'")
        expr.terms += 1
        if kind == "name":
            expr.names.append((sign, token))
        elif kind == "float":
            float_value = sign * float(token.rstrip("fF"))
        else:
            expr.number += sign * _number(kind, token)
        sign = 1
        want_term = False
    if want_term:
        raise AsmError(f"'{text.strip()}' ends with an operator")
    if float_value is not None:
        if expr.terms > 1:
            raise AsmError("a float can't be added to or subtracted from other values")
        expr.float_bits = float_bits(float_value)
    return expr
