from enum import Enum, auto
from dataclasses import dataclass

class TokenType(Enum):
    INTEGER    = auto()
    STRING     = auto()
    KEYWORD    = auto()
    IDENTIFIER = auto()
    SEPARATOR  = auto()
    OPERATOR   = auto()
    SPECIAL    = auto()

@dataclass
class Token:
    type: TokenType
    value: str

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r})"


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0          # replaces cur_char/next_char pointer logic
        self.tokens: list[Token] = []

    # ── helpers ──────────────────────────────────────────────────────────

    def _peek(self) -> str:
        """Look at the current character without consuming it."""
        if self.pos < len(self.source):
            return self.source[self.pos]
        return "\x00"          # sentinel — replaces (char)EOF == -1

    def _peek_next(self) -> str:
        """Look one character ahead without consuming."""
        if self.pos + 1 < len(self.source):
            return self.source[self.pos + 1]
        return "\x00"

    def _advance(self) -> str:
        """Consume and return the current character."""
        ch = self._peek()
        self.pos += 1
        return ch

    def _match(self, expected: str) -> bool:
        """Consume the next char only if it equals `expected`."""
        if self._peek() == expected:
            self.pos += 1
            return True
        return False

    # ── sub-lexers (mirror num_generator / keyword_generator) ────────────

    def _read_number(self) -> Token:
        start = self.pos
        while self._peek().isdigit():
            self._advance()
        return Token(TokenType.INTEGER, self.source[start:self.pos])

    def _read_word(self) -> Token:
        """Reads identifiers and keywords (classification happens later)."""
        start = self.pos
        while self._peek().isalpha() or self._peek() == "_":
            self._advance()
        word = self.source[start:self.pos]
        return Token(TokenType.IDENTIFIER, word)

    def _read_string(self) -> list[Token]:
        """Returns three tokens: open-quote, content, close-quote."""
        tokens = [Token(TokenType.SEPARATOR, '"')]
        content = []
        while self._peek() not in ('"', "\x00"):
            ch = self._advance()
            if ch == "\\" and self._peek() == '"':
                content.append(ch)
                content.append(self._advance())   # escaped quote
            else:
                content.append(ch)
        tokens.append(Token(TokenType.KEYWORD, "".join(content)))
        self._advance()   # consume closing "
        tokens.append(Token(TokenType.SEPARATOR, '"'))
        return tokens

    def _read_char_literal(self) -> list[Token]:
        tokens = [Token(TokenType.SEPARATOR, "'")]
        is_escape = self._peek() == "\\"
        if is_escape:
            self._advance()
            token_type = TokenType.SPECIAL
        else:
            token_type = TokenType.KEYWORD
        ch = self._advance()
        tokens.append(Token(token_type, ch))
        self._advance()   # consume closing '
        tokens.append(Token(TokenType.SEPARATOR, "'"))
        return tokens

    def _skip_block_comment(self):
        while not (self._peek() == "*" and self._peek_next() == "/"):
            if self._peek() == "\x00":
                break
            self._advance()
        self._advance()   # *
        self._advance()   # /

    def _skip_line_comment(self):
        while self._peek() not in ("\n", "\x00"):
            self._advance()

    def _skip_preprocessor(self):
        """Skips C #include / #define lines."""
        while self._peek() not in ("\n", "\x00"):
            self._advance()

    # ── main tokenize method ─────────────────────────────────────────────

    def tokenize(self) -> list[Token]:
        while self.pos < len(self.source):
            ch = self._advance()

            # --- whitespace ---
            if ch in (" ", "\t", "\n", "\r"):
                continue

            # --- preprocessor ---
            if ch == "#":
                self._skip_preprocessor()
                continue

            # --- comments ---
            if ch == "/" and self._peek() == "*":
                self._advance()
                self._skip_block_comment()
                continue
            if ch == "/" and self._peek() == "/":
                self._advance()
                self._skip_line_comment()
                continue

            # --- strings and chars ---
            if ch == '"':
                self.tokens.extend(self._read_string())
                continue
            if ch == "'":
                self.tokens.extend(self._read_char_literal())
                continue

            # --- numbers ---
            if ch.isdigit():
                self.pos -= 1            # put the digit back
                self.tokens.append(self._read_number())
                continue

            # --- identifiers / keywords ---
            if ch.isalpha() or (ch == "_" and self._peek() != "'"):
                self.pos -= 1
                self.tokens.append(self._read_word())
                continue

            # --- operators and separators ---
            tok = self._lex_symbol(ch)
            if tok:
                self.tokens.append(tok)

        self.tokens.append(Token(TokenType.SPECIAL, "EOF"))
        return self.tokens

    def _lex_symbol(self, ch: str) -> Token | None:
        SEP = TokenType.SEPARATOR
        OPR = TokenType.OPERATOR

        match ch:
            # separators
            case ";" | "(" | ")" | "[" | "]" | "{" | "}" | "," | ":":
                return Token(SEP, ch)
            case "|":
                return Token(SEP, "||" if self._match("|") else "|")

            # operators
            case ".": return Token(OPR, ".")
            case "?": return Token(OPR, "?")
            case "%": return Token(OPR, "%")
            case "^": return Token(OPR, "^")
            case "~": return Token(OPR, "~")
            case "&":
                return Token(OPR, "&&" if self._match("&") else "&")
            case "!":
                return Token(OPR, "!=" if self._match("=") else "!")
            case "=":
                return Token(SEP, "==" if self._match("=") else "=")
            case "+":
                if self._match("="): return Token(OPR, "+=")
                if self._match("+"): return Token(OPR, "++")
                return Token(OPR, "+")
            case "-":
                if self._match(">"): return Token(OPR, "->")
                if self._match("="): return Token(OPR, "-=")
                if self._match("-"): return Token(OPR, "--")
                return Token(OPR, "-")
            case "*":
                return Token(OPR, "*=" if self._match("=") else "*")
            case "/":
                return Token(OPR, "/=" if self._match("=") else "/")
            case "<":
                if self._match("="):  return Token(OPR, "<=")
                if self._match("<"):
                    return Token(OPR, "<<=" if self._match("=") else "<<")
                return Token(OPR, "<")
            case ">":
                if self._match("="):  return Token(OPR, ">=")
                if self._match(">"): 
                    return Token(OPR, ">>=" if self._match("=") else ">>")
                return Token(OPR, ">")
            case _:
                return None   # unknown character — skip silently

if __name__ == "__main__":

    code = open("data/input.in").read()
    output = open("data/output.out", "w")
    tokens = Lexer(code).tokenize()

    for tok in tokens:
        print(tok, file=output)