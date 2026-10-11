"""The C preprocessor: #include, #define, #if and friends, macro expansion.

Works on the tokens from lexer.tokenize(). Macro expansion follows the
standard "hide set" algorithm (Prosser's), the same one chibicc and most
modern preprocessors use: a token produced by expanding macro M carries M
in its hide set, so M can't expand inside its own expansion.

The result is a flat token list for the parser, already convert()ed:
keywords recognised, numbers and literals decoded, adjacent string literals
joined.
"""

import datetime
import os
from dataclasses import dataclass, field

import lexer
from cerror import CError, error_at
from lexer import Token, tokenize

MAX_INCLUDE_DEPTH = 200


@dataclass
class Macro:
    name: str
    objlike: bool
    params: list = field(default_factory=list)   # parameter names
    variadic: str | None = None    # name of the variadic parameter (__VA_ARGS__ or a GNU name)
    body: list = field(default_factory=list)     # replacement tokens
    handler: object = None         # builtin macros: function(token) -> list of tokens


@dataclass
class CondIncl:
    ctx: str          # "then", "elif" or "else"
    tok: Token        # the #if / #ifdef / #ifndef, for messages
    included: bool    # whether some branch has been taken already


class Stream:
    """Tokens waiting to be read; macro expansions are pushed on the front."""

    def __init__(self, tokens):
        self.stack = list(reversed(tokens))

    def peek(self):
        return self.stack[-1]

    def next(self):
        return self.stack.pop()

    def push(self, tokens):
        self.stack.extend(reversed(tokens))

    def empty(self):
        return not self.stack


def _eof_like(tok):
    return Token("eof", "", tok.file, tok.line, tok.col, bol=True)


class Preprocessor:
    def __init__(self, include_dirs=(), defines=(), warn=None):
        self.include_dirs = list(include_dirs)
        self.macros = {}
        self.cond = []
        self.pragma_once = set()
        self.files = []              # every file read, by number
        self.include_depth = 0
        self.counter = 0
        self.warn = warn or (lambda tok, msg: None)
        self._define_builtins()
        for d in defines:
            name, _, value = d.partition("=")
            self.define_text(f"#define {name} {value if _ else '1'}\n")

    # -------------------------------------------------------------- entry
    def run_file(self, path):
        """Preprocess a whole file; returns parser tokens."""
        tokens = self.read_file(path, None)
        return self.finish(tokens)

    def run_text(self, text, name="<input>"):
        self.files.append(name)
        tokens = tokenize(text, name, len(self.files) - 1)
        return self.finish(tokens)

    def finish(self, tokens):
        out = self.process(Stream(tokens))
        if self.cond:
            raise error_at(self.cond[-1].tok, "unterminated conditional directive")
        return join_strings(convert(out))

    def read_file(self, path, at):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            if at is None:
                raise CError(f"can't read the file ({e.strerror})", str(path)) from None
            raise error_at(at, f"can't read '{path}' ({e.strerror})") from None
        self.files.append(str(path))
        return tokenize(text, str(path), len(self.files) - 1)

    def define_text(self, text):
        """Run some #define lines (for predefined macros and -D)."""
        self.process(Stream(tokenize(text, "<built-in>")))

    # -------------------------------------------------------------- main loop
    def process(self, stream):
        out = []
        while True:
            tok = stream.next()
            if tok.kind == "eof":
                if isinstance(tok, _IncludeEnd):
                    tok.close()           # the end of an #included file
                    continue
                if stream.empty():
                    return out
                continue
            if self.expand_macro(tok, stream):
                continue
            if not (tok.is_("#") and tok.bol):
                out.append(tok)
                continue
            self.directive(tok, stream)

    def rest_of_line(self, stream):
        """The tokens up to the end of the current line."""
        toks = []
        while not stream.peek().bol:
            toks.append(stream.next())
        return toks

    def skip_line(self, stream, directive):
        extra = self.rest_of_line(stream)
        if extra:
            self.warn(extra[0], f"extra tokens at end of #{directive} directive")

    def directive(self, hash_tok, stream):
        tok = stream.next()
        if tok.bol:                       # a lone '#': the null directive
            stream.push([tok])
            return
        name = tok.text
        if tok.kind != "ident":
            if tok.kind == "num":         # GNU line marker: # 12 "file"
                self.rest_of_line(stream)
                return
            raise error_at(tok, "invalid preprocessing directive")

        if name == "include" or name == "include_next":
            self.include(tok, stream)
        elif name == "define":
            self.define(stream)
        elif name == "undef":
            t = stream.next()
            if t.kind != "ident" or t.bol:
                raise error_at(t, "macro name must be an identifier")
            self.macros.pop(t.text, None)
            self.skip_line(stream, "undef")
        elif name == "if":
            value = self.eval_condition(tok, stream)
            self.cond.append(CondIncl("then", tok, value))
            if not value:
                self.skip_cond(stream)
        elif name in ("ifdef", "ifndef"):
            t = stream.next()
            if t.kind != "ident" or t.bol:
                raise error_at(t, "macro name must be an identifier")
            defined = t.text in self.macros
            value = defined if name == "ifdef" else not defined
            self.skip_line(stream, name)
            self.cond.append(CondIncl("then", tok, value))
            if not value:
                self.skip_cond(stream)
        elif name == "elif":
            if not self.cond or self.cond[-1].ctx == "else":
                raise error_at(tok, "#elif without #if")
            top = self.cond[-1]
            top.ctx = "elif"
            if not top.included and self.eval_condition(tok, stream):
                top.included = True
            else:
                self.rest_of_line(stream)
                self.skip_cond(stream)
        elif name == "else":
            if not self.cond or self.cond[-1].ctx == "else":
                raise error_at(tok, "#else without #if")
            top = self.cond[-1]
            top.ctx = "else"
            self.skip_line(stream, "else")
            if top.included:
                self.skip_cond(stream)
            top.included = True
        elif name == "endif":
            if not self.cond:
                raise error_at(tok, "#endif without #if")
            self.cond.pop()
            self.skip_line(stream, "endif")
        elif name == "line":
            self.rest_of_line(stream)           # accepted, not used
        elif name == "pragma":
            rest = self.rest_of_line(stream)
            if rest and rest[0].text == "once":
                self.pragma_once.add(os.path.realpath(tok.file))
        elif name == "error":
            rest = self.rest_of_line(stream)
            raise error_at(tok, "#error " + " ".join(t.text for t in rest))
        elif name == "warning":
            rest = self.rest_of_line(stream)
            self.warn(tok, "#warning " + " ".join(t.text for t in rest))
        else:
            raise error_at(tok, f"invalid preprocessing directive #{name}")

    # -------------------------------------------------------------- #include
    def include(self, tok, stream):
        line = self.rest_of_line(stream)
        if not line:
            raise error_at(tok, "#include expects \"FILENAME\" or <FILENAME>")
        if line[0].kind == "str":
            name, quoted = line[0].text[1:-1], True
            rest = line[1:]
        elif line[0].is_("<"):
            name, rest, quoted = self._angle_name(line, tok)
        else:
            expanded = self.expand_all(line)          # #include MACRO
            if expanded and expanded[0].kind == "str":
                name, quoted, rest = expanded[0].text[1:-1], True, expanded[1:]
            elif expanded and expanded[0].is_("<"):
                name, rest, quoted = self._angle_name(expanded, tok)
            else:
                raise error_at(tok, "#include expects \"FILENAME\" or <FILENAME>")
        if rest:
            self.warn(rest[0], "extra tokens at end of #include directive")
        path = self.find_include(name, quoted, tok)
        if path is None:
            raise error_at(tok, f"{name}: no such file (searched "
                           + ", ".join(self.search_dirs(quoted, tok)) + ")")
        if os.path.realpath(path) in self.pragma_once:
            return
        self.include_depth += 1
        if self.include_depth > MAX_INCLUDE_DEPTH:
            raise error_at(tok, "#include nested too deeply")
        tokens = self.read_file(path, tok)
        # an include-depth marker: a dedicated eof token closes the file
        end = tokens[-1]
        end.text = "<end of include>"
        stream.push(tokens[:-1] + [_IncludeEnd(self, end)])

    def _angle_name(self, line, tok):
        parts = []
        for i in range(1, len(line)):
            if line[i].is_(">"):
                return "".join(parts), line[i + 1:], False
            if line[i].space and parts:
                parts.append(" ")
            parts.append(line[i].text)
        raise error_at(tok, "missing '>' in #include")

    def search_dirs(self, quoted, tok):
        dirs = [os.path.dirname(tok.file) or "."] if quoted else []
        return dirs + self.include_dirs

    def find_include(self, name, quoted, tok):
        if os.path.isabs(name):
            return name if os.path.exists(name) else None
        for d in self.search_dirs(quoted, tok):
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path
        return None

    # -------------------------------------------------------------- #define
    def define(self, stream):
        name_tok = stream.next()
        if name_tok.kind != "ident" or name_tok.bol:
            raise error_at(name_tok, "macro name must be an identifier")
        name = name_tok.text
        if name == "defined":
            raise error_at(name_tok, "'defined' can't be used as a macro name")
        nxt = stream.peek()
        if nxt.is_("(") and not nxt.space and not nxt.bol:
            stream.next()
            params, variadic = self.read_params(stream, name_tok)
            body = self.rest_of_line(stream)
            macro = Macro(name, False, params, variadic, body)
            self.check_hashes(macro)
        else:
            if not nxt.bol and not nxt.space:
                self.warn(nxt, "missing whitespace after the macro name")
            macro = Macro(name, True, body=self.rest_of_line(stream))
            for t in macro.body[:1] + macro.body[-1:]:
                if t.is_("##"):
                    raise error_at(t, "'##' cannot appear at either end of a macro expansion")
        old = self.macros.get(name)
        if old and old.handler is None and not _same_macro(old, macro):
            self.warn(name_tok, f"'{name}' redefined")
        self.macros[name] = macro

    def read_params(self, stream, name_tok):
        params, variadic = [], None
        tok = stream.next()
        if tok.is_(")"):
            return params, variadic
        while True:
            if tok.bol:
                raise error_at(name_tok, "missing ')' in macro parameter list")
            if tok.is_("..."):
                variadic = "__VA_ARGS__"
                tok = stream.next()
                if not tok.is_(")"):
                    raise error_at(tok, "expected ')' after '...'")
                return params, variadic
            if tok.kind != "ident":
                raise error_at(tok, "expected a parameter name")
            if tok.text in params:
                raise error_at(tok, f"duplicate macro parameter '{tok.text}'")
            name = tok.text
            tok = stream.next()
            if tok.is_("..."):                       # GNU: args...
                variadic = name
                tok = stream.next()
                if not tok.is_(")"):
                    raise error_at(tok, "expected ')' after '...'")
                return params, variadic
            params.append(name)
            if tok.is_(")"):
                return params, variadic
            if not tok.is_(","):
                raise error_at(tok, "expected ',' or ')' in the macro parameter list")
            tok = stream.next()

    def check_hashes(self, macro):
        names = set(macro.params) | ({macro.variadic} if macro.variadic else set())
        body = macro.body
        for i, t in enumerate(body):
            if t.is_("#") and (i + 1 >= len(body) or body[i + 1].text not in names):
                raise error_at(t, "'#' is not followed by a macro parameter")
        for t in body[:1] + body[-1:]:
            if t.is_("##"):
                raise error_at(t, "'##' cannot appear at either end of a macro expansion")

    # -------------------------------------------------------------- expansion
    def expand_macro(self, tok, stream):
        """If tok is a macro name to expand, push its expansion and return True."""
        if tok.kind != "ident" or tok.text in tok.hideset:
            return False
        macro = self.macros.get(tok.text)
        if macro is None:
            return False
        if macro.handler:
            stream.push(macro.handler(tok))
            return True
        if macro.objlike:
            hs = tok.hideset | {macro.name}
            body = [t.copy(hideset=t.hideset | hs, origin=tok.origin or tok)
                    for t in macro.body]
            body = self.paste_all(body, macro, {})
            self._place(body, tok)
            stream.push(body)
            return True
        # function-like: only when '(' follows
        if stream.empty() or not stream.peek().is_("("):
            return False
        stream.next()
        args, rparen = self.read_args(stream, macro, tok)
        hs = (tok.hideset & rparen.hideset) | {macro.name}
        body = self.substitute(macro, args, tok)
        body = [t.copy(hideset=t.hideset | hs, origin=tok.origin or tok) for t in body]
        self._place(body, tok)
        stream.push(body)
        return True

    @staticmethod
    def _place(body, tok):
        """The first token of an expansion takes the macro name's spacing. It
        never counts as the start of a line: an expansion can't make a
        directive."""
        if body:
            body[0] = body[0].copy(bol=False, space=tok.space or tok.bol)

    def read_args(self, stream, macro, name_tok):
        """Read the arguments of a function-like macro call (after '(')."""
        args = [[]]
        depth = 0
        while True:
            if stream.empty() or stream.peek().kind == "eof":
                raise error_at(name_tok, f"unterminated argument list invoking macro '{macro.name}'")
            tok = stream.next()
            if tok.is_("#") and tok.bol:
                raise error_at(tok, "directives inside macro arguments are not supported")
            if tok.is_("("):
                depth += 1
            elif tok.is_(")"):
                if depth == 0:
                    rparen = tok
                    break
                depth -= 1
            if tok.is_(",") and depth == 0:
                if macro.variadic and len(args) > len(macro.params):
                    args[-1].append(tok)     # commas inside the variadic part
                else:
                    args.append([])
                continue
            args[-1].append(tok.copy(bol=False))
        nparams = len(macro.params)
        if nparams == 0 and not macro.variadic and args == [[]]:
            args = []
        named = {}
        if macro.variadic:
            if len(args) < nparams:
                raise error_at(name_tok, f"macro '{macro.name}' requires at least {nparams} arguments")
            for p, a in zip(macro.params, args):
                named[p] = a
            named[macro.variadic] = args[nparams] if len(args) > nparams else []
        else:
            if len(args) != nparams:
                raise error_at(name_tok, f"macro '{macro.name}' takes {nparams} argument"
                               f"{'s' if nparams != 1 else ''}, but {len(args)} given")
            for p, a in zip(macro.params, args):
                named[p] = a
        return named, rparen

    def substitute(self, macro, args, name_tok):
        """The macro body with the arguments put in (#, ## and plain uses)."""
        body = macro.body
        out = []
        i = 0
        names = set(macro.params) | ({macro.variadic} if macro.variadic else set())
        while i < len(body):
            t = body[i]
            # '#' param: stringize
            if t.is_("#") and i + 1 < len(body) and body[i + 1].text in names:
                s = stringize(args[body[i + 1].text], t)
                out.append(s.copy(space=t.space))
                i += 2
                continue
            # GNU: , ## __VA_ARGS__ drops the comma when there are no variadic args
            if (t.is_(",") and i + 2 < len(body) and body[i + 1].is_("##")
                    and macro.variadic and body[i + 2].text == macro.variadic):
                va = args[macro.variadic]
                if va:
                    out.append(t)
                    out.extend(a.copy() for a in va)
                i += 3
                continue
            if t.kind == "ident" and t.text in names:
                arg = args[t.text]
                pasted_before = out and i > 0 and body[i - 1].is_("##")
                pasted_after = i + 1 < len(body) and body[i + 1].is_("##")
                if pasted_before or pasted_after:
                    toks = [a.copy() for a in arg]
                    if not toks:
                        toks = [_placemarker(t)]
                else:
                    toks = self.expand_all(arg)
                if toks:
                    toks[0] = toks[0].copy(space=t.space)
                out.extend(toks)
                i += 1
                continue
            out.append(t)
            i += 1
        return self.paste_all(out, macro, args)

    def paste_all(self, toks, macro, args):
        """Carry out every '##' in an expansion."""
        if not any(t.is_("##") for t in toks):
            return toks
        out = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.is_("##") and out and i + 1 < len(toks):
                left = out.pop()
                right = toks[i + 1]
                out.append(paste(left, right))
                i += 2
                continue
            out.append(t)
            i += 1
        return [t for t in out if t.kind != "placemarker"]

    def expand_all(self, toks):
        """Fully macro-expand a token list on its own (macro arguments, #include, #if)."""
        if not toks:
            return []
        stream = Stream(list(toks) + [_eof_like(toks[-1])])
        out = []
        while True:
            tok = stream.next()
            if tok.kind == "eof" and stream.empty():
                return out
            if self.expand_macro(tok, stream):
                continue
            out.append(tok)

    # -------------------------------------------------------------- #if
    def eval_condition(self, tok, stream):
        line = self.rest_of_line(stream)
        if not line:
            raise error_at(tok, f"#{tok.text} with no expression")
        # 'defined X' and __has_include are decided before macro expansion
        pre = []
        i = 0
        while i < len(line):
            t = line[i]
            if t.text == "defined" and t.kind == "ident":
                paren = i + 1 < len(line) and line[i + 1].is_("(")
                j = i + 2 if paren else i + 1
                if j >= len(line) or line[j].kind != "ident":
                    raise error_at(t, "macro name must be an identifier")
                if paren and (j + 1 >= len(line) or not line[j + 1].is_(")")):
                    raise error_at(t, "missing ')' after 'defined'")
                pre.append(_number_token("1" if line[j].text in self.macros else "0", t))
                i = j + 2 if paren else j + 1
                continue
            if t.text == "__has_include" and t.kind == "ident":
                j = i + 1
                if j >= len(line) or not line[j].is_("("):
                    raise error_at(t, "missing '(' after __has_include")
                k = j + 1
                while k < len(line) and not line[k].is_(")"):
                    k += 1
                inner = line[j + 1:k]
                if inner and inner[0].kind == "str":
                    name, quoted = inner[0].text[1:-1], True
                elif inner and inner[0].is_("<"):
                    name, _, quoted = self._angle_name(inner + [line[k]], t)
                else:
                    raise error_at(t, "expected \"FILENAME\" or <FILENAME>")
                found = self.find_include(name, quoted, t) is not None
                pre.append(_number_token("1" if found else "0", t))
                i = k + 1
                continue
            pre.append(t)
            i += 1
        toks = self.expand_all(pre)
        # whatever identifiers are left (keywords included) count as 0
        toks = [_number_token("0", t) if t.kind == "ident" else t for t in toks]
        return ConstExpr(convert(toks), tok).evaluate() != 0

    def skip_cond(self, stream):
        """Skip tokens up to the #elif / #else / #endif that ends this block."""
        depth = 0
        while True:
            if stream.empty():
                raise error_at(self.cond[-1].tok, "unterminated conditional directive")
            tok = stream.next()
            if tok.kind == "eof":
                if isinstance(tok, _IncludeEnd):
                    tok.close()
                raise error_at(self.cond[-1].tok, "unterminated conditional directive")
            if not (tok.is_("#") and tok.bol):
                continue
            d = stream.peek()
            if d.bol:
                continue
            if d.text in ("if", "ifdef", "ifndef"):
                depth += 1
                stream.next()
                self.rest_of_line(stream)
            elif d.text == "endif":
                if depth == 0:
                    stream.push([tok])
                    return
                depth -= 1
                stream.next()
                self.rest_of_line(stream)
            elif d.text in ("elif", "else") and depth == 0:
                stream.push([tok])
                return

    # -------------------------------------------------------------- built-ins
    def _define_builtins(self):
        self.define_text("""
#define __STDC__ 1
#define __STDC_VERSION__ 199901L
#define __STDC_HOSTED__ 1
#define __STDC_NO_ATOMICS__ 1
#define __STDC_NO_COMPLEX__ 1
#define __STDC_NO_THREADS__ 1
#define __STDC_NO_VLA__ 1
#define __STDC_IEC_559__ 1
#define __TINYC__ 1
#define __CHAR_BIT__ 32
#define __SIZEOF_INT__ 1
#define __SIZEOF_LONG__ 1
#define __SIZEOF_SHORT__ 1
#define __SIZEOF_POINTER__ 1
#define __SIZEOF_FLOAT__ 1
#define __SIZEOF_DOUBLE__ 1
#define __INT_MAX__ 0x7fffffff
#define __LONG_MAX__ 0x7fffffffL
#define __SIZE_TYPE__ unsigned int
#define __PTRDIFF_TYPE__ int
#define __WCHAR_TYPE__ int
#define __FLT_EVAL_METHOD__ 0
""")
        now = datetime.datetime.now()

        def string_tok(text, at):
            t = Token("str", '"' + text + '"', at.file, at.line, at.col)
            return t

        def file_macro(tok):
            src = tok.origin or tok
            return [string_tok(src.file.replace("\\", "\\\\"), tok)]

        def line_macro(tok):
            src = tok.origin or tok
            return [_number_token(str(src.line), tok)]

        def counter_macro(tok):
            self.counter += 1
            return [_number_token(str(self.counter - 1), tok)]

        def date_macro(tok):
            return [string_tok(now.strftime("%b %e %Y"), tok)]

        def time_macro(tok):
            return [string_tok(now.strftime("%H:%M:%S"), tok)]

        for name, handler in (("__FILE__", file_macro), ("__LINE__", line_macro),
                              ("__COUNTER__", counter_macro), ("__DATE__", date_macro),
                              ("__TIME__", time_macro)):
            self.macros[name] = Macro(name, True, handler=handler)


class _IncludeEnd(Token):
    """The eof at the end of an #included file: counts the include depth down."""

    def __init__(self, pp, end):
        super().__init__("eof", "", end.file, end.line, end.col, bol=True)
        self._pp = pp
        self._closed = False

    def close(self):
        if not self._closed:
            self._closed = True
            self._pp.include_depth -= 1


def _same_macro(a, b):
    if a.objlike != b.objlike or a.params != b.params or a.variadic != b.variadic:
        return False
    if len(a.body) != len(b.body):
        return False
    return all(x.text == y.text and (i == 0 or x.space == y.space)
               for i, (x, y) in enumerate(zip(a.body, b.body)))


def _number_token(text, at):
    return Token("num", text, at.file, at.line, at.col, space=True)


def _placemarker(at):
    return Token("placemarker", "", at.file, at.line, at.col)


def stringize(toks, at):
    """#param: the argument's spelling as a string literal."""
    parts = []
    for i, t in enumerate(toks):
        if i and t.space:
            parts.append(" ")
        if t.kind in ("str", "char"):
            parts.append(t.text.replace("\\", "\\\\").replace('"', '\\"'))
        else:
            parts.append(t.text)
    return Token("str", '"' + "".join(parts) + '"', at.file, at.line, at.col)


def paste(left, right):
    """left ## right: the two spellings joined must make one token."""
    if left.kind == "placemarker":
        return right
    if right.kind == "placemarker":
        return left
    text = left.text + right.text
    toks = tokenize(text, left.file)
    if len(toks) != 2:
        raise error_at(left, f"pasting \"{left.text}\" and \"{right.text}\" does not give "
                       "a valid preprocessing token")
    t = toks[0]
    return left.copy(kind=t.kind, text=t.text, str_kind=t.str_kind)


# ------------------------------------------------------------------ to parser tokens

def convert(tokens):
    """Preprocessing tokens -> parser tokens (in place)."""
    out = []
    for t in tokens:
        if t.kind == "eof":
            continue
        if t.kind == "ident" and t.text in lexer.KEYWORDS:
            t.kind = "keyword"
        elif t.kind == "num":
            kind, value, suffix, base = lexer.parse_number(t)
            t.value = value
            t.ty = (kind, suffix, base)
        elif t.kind == "char":
            codes = lexer.decode_literal(t)
            if len(codes) != 1:
                if not codes:
                    raise error_at(t, "empty character constant")
                raise error_at(t, "multi-character character constants are not supported")
            t.value = codes[0]
        elif t.kind == "str":
            t.value = lexer.decode_literal(t)
        elif t.kind == "other":
            raise error_at(t, f"stray '{t.text}' in program")
        out.append(t)
    return out


def join_strings(tokens):
    """Adjacent string literals become one ("ab" "cd" -> "abcd")."""
    out = []
    for t in tokens:
        if t.kind == "str" and out and out[-1].kind == "str":
            prev = out[-1]
            kind = prev.str_kind or t.str_kind
            if prev.str_kind and t.str_kind and prev.str_kind != t.str_kind:
                raise error_at(t, "concatenation of different kinds of string literals")
            out[-1] = prev.copy(value=prev.value + t.value, str_kind=kind,
                                text=prev.text + " " + t.text)
            continue
        out.append(t)
    return out


# ------------------------------------------------------------------ #if arithmetic

class ConstExpr:
    """Evaluates a #if expression. Values are (int, unsigned) pairs with
    64-bit wrap-around, like intmax_t / uintmax_t."""

    MASK = (1 << 64) - 1

    def __init__(self, tokens, at):
        self.toks = tokens
        self.pos = 0
        self.at = at

    def evaluate(self):
        if not self.toks:
            raise error_at(self.at, "#if with no expression")
        v, _ = self.cond()
        if self.pos < len(self.toks):
            raise error_at(self.toks[self.pos], f"missing binary operator before "
                           f"'{self.toks[self.pos].text}'")
        return v

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def accept(self, text):
        t = self.peek()
        if t is not None and t.text == text and t.kind in ("punct", "keyword", "ident"):
            self.pos += 1
            return True
        return False

    def fix(self, v, u):
        v &= self.MASK
        if not u and v >= 1 << 63:
            v -= 1 << 64
        return v, u

    def cond(self):
        c, cu = self.logor()
        if self.accept("?"):
            a = self.cond()
            if not self.accept(":"):
                raise error_at(self.at, "expected ':' in #if expression")
            b = self.cond()
            u = a[1] or b[1]
            return self.fix(a[0] if c else b[0], u)
        return c, cu

    def logor(self):
        v = self.logand()
        while self.accept("||"):
            r = self.logand()
            v = (int(bool(v[0]) or bool(r[0])), False)
        return v

    def logand(self):
        v = self.bitor()
        while self.accept("&&"):
            r = self.bitor()
            v = (int(bool(v[0]) and bool(r[0])), False)
        return v

    def binary(self, sub, ops):
        v = sub()
        while True:
            t = self.peek()
            if t is None or t.kind != "punct" or t.text not in ops:
                return v
            self.pos += 1
            r = sub()
            v = self.apply(t, v, r)

    def bitor(self):
        return self.binary(self.bitxor, ("|",))

    def bitxor(self):
        return self.binary(self.bitand, ("^",))

    def bitand(self):
        return self.binary(self.equality, ("&",))

    def equality(self):
        return self.binary(self.relational, ("==", "!="))

    def relational(self):
        return self.binary(self.shift, ("<", ">", "<=", ">="))

    def shift(self):
        return self.binary(self.additive, ("<<", ">>"))

    def additive(self):
        return self.binary(self.multiplicative, ("+", "-"))

    def multiplicative(self):
        return self.binary(self.unary, ("*", "/", "%"))

    def apply(self, t, a, b):
        op = t.text
        u = a[1] or b[1]
        x, y = a[0], b[0]
        if u:
            x &= self.MASK
            y &= self.MASK
        if op in ("<", ">", "<=", ">=", "==", "!="):
            r = {"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y,
                 "==": x == y, "!=": x != y}[op]
            return int(r), False
        if op in ("/", "%"):
            if y == 0:
                raise error_at(t, "division by zero in #if")
            q = abs(x) // abs(y)
            if (x < 0) != (y < 0):
                q = -q
            return self.fix(q if op == "/" else x - q * y, u)
        if op == "<<":
            return self.fix(x << (y & 63), a[1])
        if op == ">>":
            return self.fix(x >> (y & 63), a[1])
        r = {"+": x + y, "-": x - y, "*": x * y, "&": x & y, "|": x | y, "^": x ^ y}[op]
        return self.fix(r, u)

    def unary(self):
        t = self.peek()
        if t is None:
            raise error_at(self.at, "#if expression ends early")
        if t.kind == "punct" and t.text in ("+", "-", "~", "!"):
            self.pos += 1
            v, u = self.unary()
            if t.text == "+":
                return v, u
            if t.text == "-":
                return self.fix(-v, u)
            if t.text == "~":
                return self.fix(~v, u)
            return int(not v), False
        if self.accept("("):
            v = self.cond()
            if not self.accept(")"):
                raise error_at(t, "missing ')' in #if expression")
            return v
        self.pos += 1
        if t.kind == "num":
            kind, suffix, base = t.ty
            if kind != "int":
                raise error_at(t, "floating constant in preprocessor expression")
            return self.fix(t.value, "u" in suffix)
        if t.kind == "char":
            return t.value, False
        raise error_at(t, f"token '{t.text}' is not valid in preprocessor expressions")
