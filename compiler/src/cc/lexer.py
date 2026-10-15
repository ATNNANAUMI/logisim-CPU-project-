"""Turning C source text into tokens.

tokenize() gives preprocessing tokens: identifiers, pp-numbers, character
constants, string literals and punctuators, each with its file, line and
column, and two layout flags the preprocessor needs: bol (first token on its
line) and space (whitespace before it).

After preprocessing, convert() turns them into parser tokens: keywords are
recognised, numbers get their value and type, and character and string
literals are decoded.
"""

import re
from dataclasses import dataclass, field, replace

from cerror import CError, error_at

KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if",
    "inline", "int", "long", "register", "restrict", "return", "short",
    "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
    "unsigned", "void", "volatile", "while",
    "_Bool", "_Alignas", "_Alignof", "_Noreturn", "_Static_assert",
    "_Generic", "_Thread_local", "_Atomic", "_Complex", "_Imaginary",
    "__restrict", "__restrict__", "__inline", "__inline__", "__volatile__",
    "__const", "__signed__", "__attribute__", "__extension__",
    "asm", "__asm__", "__asm", "__typeof__", "typeof",
}

PUNCTUATORS = sorted("""
    <<= >>= ... -> ++ -- << >> <= >= == != && || += -= *= /= %= &= |= ^= ##
    [ ] ( ) { } . & * + - ~ ! / % < > ^ | ? : ; = , #
""".split(), key=len, reverse=True)

_PUNCT_RE = re.compile("|".join(re.escape(p) for p in PUNCTUATORS))
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PPNUM_RE = re.compile(r"\.?[0-9](?:[eEpP][+-]|[0-9A-Za-z_.])*")
_SPACE = " \t\v\f"


@dataclass(eq=False)
class Token:
    kind: str               # ident num char str punct other eof; after convert(): keyword too
    text: str               # the source spelling
    file: str               # file name for messages
    line: int
    col: int
    bol: bool = False       # first token on its line
    space: bool = False     # whitespace (or a comment) right before it
    hideset: frozenset = frozenset()    # macros that may not expand this token again
    origin: "Token | None" = None       # where a macro expansion started, for messages
    value: object = None    # after convert(): int/float for numbers, codes for char/str
    ty: object = None       # after convert(): the literal's type
    str_kind: str = ""      # string/char prefix: "", "u8", "u", "U" or "L"
    fileno: int = 0         # which source file (for __FILE__ and #line)

    def copy(self, **changes):
        return replace(self, **changes)

    def is_(self, text):
        return self.text == text and self.kind in ("punct", "ident", "keyword")

    def __repr__(self):
        return f"Token({self.kind}, {self.text!r}, {self.line}:{self.col})"


def _splice(text):
    """Remove backslash-newline pairs.

    Returns the joined text and, for every character in it, the line and
    column it came from in the original text.
    """
    out = []
    lines = []
    cols = []
    line, col = 1, 1
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] == "\n":
            i += 2
            line += 1
            col = 1
            continue
        out.append(ch)
        lines.append(line)
        cols.append(col)
        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1
        i += 1
    return "".join(out), lines, cols


def tokenize(text, filename, fileno=0):
    """Split one file's text into preprocessing tokens (ending with eof)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    text, lines, cols = _splice(text)
    tokens = []
    bol = True
    space = False
    i, n = 0, len(text)

    def make(kind, start, end):
        tok = Token(kind, text[start:end], filename, lines[start], cols[start],
                    bol=bol, space=space, fileno=fileno)
        tokens.append(tok)
        return tok

    def fail(message, at):
        raise CError(message, filename, lines[at], cols[at])

    while i < n:
        ch = text[i]
        if ch == "\n":
            bol, space = True, False
            i += 1
            continue
        if ch in _SPACE:
            space = True
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = j
            space = True
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                fail("unterminated comment", i)
            i = j + 2
            space = True
            continue

        start = i
        m = _PPNUM_RE.match(text, i)
        if m:
            i = m.end()
        elif ch in "\"'" or _string_prefix(text, i):
            prefix = _string_prefix(text, i)
            j = i + len(prefix)
            quote = text[j]
            j += 1
            while True:
                if j >= n or text[j] == "\n":
                    fail("missing terminating " + quote + " character", start)
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    break
                j += 1
            i = j + 1
            tok = make("str" if quote == '"' else "char", start, i)
            tok.str_kind = prefix
            bol = space = False
            continue
        else:
            m = _IDENT_RE.match(text, i)
            if m:
                i = m.end()
                make("ident", start, i)
                bol = space = False
                continue
            m = _PUNCT_RE.match(text, i)
            if m:
                i = m.end()
                make("punct", start, i)
                bol = space = False
                continue
            i += 1
            make("other", start, i)
            bol = space = False
            continue
        make("num", start, i)
        bol = space = False

    end = len(text) - 1
    tokens.append(Token("eof", "", filename, lines[end] if lines else 1, 1,
                        bol=True, fileno=fileno))
    return tokens


def _string_prefix(text, i):
    """The prefix of a string or character literal starting at i, or ''."""
    for prefix in ("u8", "u", "U", "L"):
        if text.startswith(prefix, i):
            after = i + len(prefix)
            if after < len(text) and text[after] in "\"'":
                if prefix == "u8" and text[after] == "'":
                    continue
                return prefix
    return ""


# ------------------------------------------------------------------ literals

_SIMPLE_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11,
                   "\\": 92, "'": 39, '"': 34, "?": 63, "e": 27, "E": 27}


def decode_literal(tok):
    """The character codes inside a char or string literal token.

    Narrow literals ("" and u8) are stored as UTF-8 bytes, like gcc does;
    wide ones (L, u, U) as code points. Each code becomes one 32-bit word.
    """
    body = tok.text[len(tok.str_kind) + 1:-1]
    wide = tok.str_kind in ("L", "u", "U")
    codes = []
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch != "\\":
            if wide or ord(ch) < 0x80:
                codes.append(ord(ch))
            else:
                codes.extend(ch.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= n:
            raise error_at(tok, "a literal can't end with a lone '\\'")
        esc = body[i]
        if esc in _SIMPLE_ESCAPES:
            codes.append(_SIMPLE_ESCAPES[esc])
            i += 1
        elif esc in "01234567":
            j = i
            while j < n and j < i + 3 and body[j] in "01234567":
                j += 1
            codes.append(int(body[i:j], 8))
            i = j
        elif esc == "x":
            j = i + 1
            while j < n and body[j] in "0123456789abcdefABCDEF":
                j += 1
            if j == i + 1:
                raise error_at(tok, "\\x used with no following hex digits")
            codes.append(int(body[i + 1:j], 16) & 0xFFFFFFFF)
            i = j
        elif esc in "uU":
            width = 4 if esc == "u" else 8
            digits = body[i + 1:i + 1 + width]
            if len(digits) != width or not all(c in "0123456789abcdefABCDEF" for c in digits):
                raise error_at(tok, f"incomplete universal character name \\{esc}{digits}")
            cp = int(digits, 16)
            if wide or cp < 0x80:
                codes.append(cp)
            else:
                codes.extend(chr(cp).encode("utf-8"))
            i += 1 + width
        else:
            raise error_at(tok, f"unknown escape sequence '\\{esc}'")
    return codes


_INT_RE = re.compile(r"(0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)([uUlL]*)$")
_INT_SUFFIXES = {"": "", "u": "u", "l": "l", "ul": "ul", "lu": "ul",
                 "ll": "ll", "ull": "ull", "llu": "ull"}


def parse_number(tok):
    """Value and type name of a pp-number: ('int', value, suffix) or
    ('float', value, suffix)."""
    text = tok.text
    m = _INT_RE.match(text)
    if m:
        digits, suffix = m.group(1), m.group(2).lower()
        if suffix not in _INT_SUFFIXES:
            raise error_at(tok, f"invalid suffix '{m.group(2)}' on integer constant")
        if digits[:2].lower() == "0x":
            value, base = int(digits, 16), 16
        elif digits[:2].lower() == "0b":
            value, base = int(digits[2:], 2), 2
        elif len(digits) > 1 and digits[0] == "0":
            if any(c in "89" for c in digits):
                raise error_at(tok, f"invalid digit in octal constant '{text}'")
            value, base = int(digits, 8), 8
        else:
            value, base = int(digits), 10
        return "int", value, _INT_SUFFIXES[suffix], base
    lower = text.lower()
    suffix = ""
    body = text
    if lower.endswith("f") and not lower.startswith("0x") or \
            lower.startswith("0x") and lower.endswith("f") and "p" in lower:
        suffix, body = "f", text[:-1]
    elif lower.endswith("l"):
        suffix, body = "l", text[:-1]
    try:
        if body.lower().startswith("0x"):
            value = float.fromhex(body)
        else:
            if not re.fullmatch(r"(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", body) or \
                    re.fullmatch(r"\d+", body):
                raise ValueError
            value = float(body)
    except (ValueError, OverflowError):
        raise error_at(tok, f"invalid number '{text}'") from None
    return "float", value, suffix, 10


def describe(tok):
    """How a token is quoted in error messages."""
    if tok.kind == "eof":
        return "end of file"
    return f"'{tok.text}'"


__all__ = ["Token", "tokenize", "decode_literal", "parse_number", "KEYWORDS",
           "describe", "field"]
