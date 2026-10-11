"""Parser and type checker: preprocessed tokens -> a typed syntax tree.

A recursive-descent parser for the C grammar, in the style of chibicc
(Rui Ueyama's small C compiler): it keeps the symbol tables while parsing
(needed to tell typedef names from other identifiers), gives every
expression its type as it builds it, and inserts the implicit conversions.

parse(tokens) returns a Program: the global objects (variables, functions,
string literals) in source order.
"""

import struct
from dataclasses import dataclass, field

import typesys as T
from cerror import CError, error_at
from lexer import Token, describe
from nodes import Node, Obj

MASK = 0xFFFFFFFF


def wrap(value, unsigned):
    """An integer as the 32-bit machine holds it: signed or unsigned."""
    value &= MASK
    if not unsigned and value & 0x80000000:
        value -= 1 << 32
    return value


def f32(value):
    """Round a Python float to float32, like every float op on the CPU."""
    try:
        return struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError:
        return float("inf") if value > 0 else float("-inf")


ASM_RESERVED = {
    "NOP", "LD", "ST", "DATA", "RJMP", "RJF", "RJNF", "CLF", "COMM", "ADDR", "JMRB",
    "STK", "ALD", "AST", "CPY", "HALT", "ADD", "SUB", "MULT", "DIV", "SHL", "SHR",
    "NOT", "AND", "OR", "XOR", "MOD", "INC", "DEC", "NEG", "TEST", "CMP", "FADD",
    "FSUB", "FMULT", "FDIV", "FLOAT", "INT", "FNEG", "FCMP", "CALL", "RET", "SAVE",
    "RESTORE",
}


def asm_label(name):
    """The assembly label for a C name. Names the assembler can't take
    (instruction names like 'add', register names like 'r1', anything
    starting with '__') get a '_X' prefix."""
    upper = name.upper()
    if (upper in ASM_RESERVED or name.startswith("__")
            or (upper[0] == "R" and upper[1:].isdigit() and int(upper[1:]) <= 15
                and len(upper) <= 3)):
        return "_X" + name
    return name


@dataclass
class VarScope:
    var: Obj | None = None
    type_def: T.Type | None = None
    enum_ty: T.Type | None = None
    enum_val: int = 0


@dataclass
class Scope:
    vars: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)


@dataclass
class VarAttr:
    is_typedef: bool = False
    is_static: bool = False
    is_extern: bool = False
    is_inline: bool = False


@dataclass
class Initializer:
    ty: T.Type
    tok: Token = None
    children: list | None = None      # for arrays and structs
    expr: Node | None = None          # for scalars
    is_flexible: bool = False         # an array whose length comes from the initializer
    mem: T.Member | None = None       # the union member being initialised


@dataclass
class Program:
    globals: list                     # Obj: functions, variables, strings, in order
    warnings: list


class Parser:
    def __init__(self, tokens, warn=None):
        self.toks = tokens
        self.pos = 0
        self.scopes = [Scope()]
        self.globals = []
        self.global_names = {}          # name -> Obj (file-level declarations)
        self.fn = None                  # function being parsed
        self.locals = None
        self.labels = None              # label name -> unique label
        self.gotos = None               # (name, token) used by goto
        self.brk = None
        self.cont = None
        self.switch = None
        self.counter = 0
        self.warnings = []
        self.warn_fn = warn

    # ================================================================ tokens
    @property
    def tok(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else self._eof()

    def _eof(self):
        last = self.toks[-1] if self.toks else None
        return Token("eof", "", last.file if last else "<input>",
                     last.line if last else 1, last.col if last else 1)

    def peek(self, k=1):
        i = self.pos + k
        return self.toks[i] if i < len(self.toks) else self._eof()

    def next(self):
        t = self.tok
        self.pos += 1
        return t

    def equal(self, text, tok=None):
        t = tok or self.tok
        return t.text == text and t.kind in ("punct", "keyword")

    def consume(self, text):
        if self.equal(text):
            self.pos += 1
            return True
        return False

    def expect(self, text):
        if not self.equal(text):
            raise error_at(self.tok, f"expected '{text}' before {describe(self.tok)}")
        return self.next()

    def expect_ident(self):
        t = self.tok
        if t.kind != "ident":
            raise error_at(t, f"expected an identifier, found {describe(t)}")
        self.pos += 1
        return t

    def error(self, message, tok=None):
        return error_at(tok or self.tok, message)

    def warn(self, tok, message):
        err = error_at(tok, message)
        self.warnings.append(err)
        if self.warn_fn:
            self.warn_fn(err)

    def unique(self, prefix):
        self.counter += 1
        return f"{prefix}{self.counter}"

    # ================================================================ scopes
    def enter_scope(self):
        self.scopes.append(Scope())

    def leave_scope(self):
        self.scopes.pop()

    def find_var(self, name):
        for sc in reversed(self.scopes):
            if name in sc.vars:
                return sc.vars[name]
        return None

    def find_tag(self, name):
        for sc in reversed(self.scopes):
            if name in sc.tags:
                return sc.tags[name]
        return None

    def push_scope(self, name):
        vs = VarScope()
        self.scopes[-1].vars[name] = vs
        return vs

    def find_typedef(self, tok):
        if tok.kind == "ident":
            vs = self.find_var(tok.text)
            if vs and vs.type_def:
                return vs.type_def
        return None

    def new_lvar(self, name, ty, tok=None):
        var = Obj(name, ty, tok, is_local=True)
        self.push_scope(name).var = var
        self.locals.append(var)
        return var

    def new_gvar(self, name, ty, tok=None, label=None):
        var = Obj(name, ty, tok)
        var.asm_name = label or asm_label(name)
        self.globals.append(var)
        return var

    def new_anon_gvar(self, ty, prefix="_G"):
        name = self.unique(prefix)
        var = Obj(name, ty)
        var.asm_name = name
        var.is_static = True
        var.is_definition = True
        self.globals.append(var)
        return var

    def new_string(self, tok):
        codes = list(tok.value) + [0]
        ty = T.array_of(T.qualified(T.int_type() if tok.str_kind in ("L", "U")
                                    else T.char_type(), const=False), len(codes))
        var = self.new_anon_gvar(ty, "_S")
        var.init_data = [c & MASK for c in codes]
        var.in_rom = True
        var.is_string = True
        return var

    # ================================================================ program
    def program(self):
        while self.tok.kind != "eof":
            if self.consume(";"):
                continue
            if self.equal("_Static_assert"):
                self.static_assert()
                continue
            if self.equal("asm") or self.equal("__asm__") or self.equal("__asm"):
                node = self.asm_stmt()
                var = self.new_anon_gvar(T.int_type(), "_A")
                var.asm_text = node.text
                continue
            attr = VarAttr()
            basety = self.declspec(attr)
            if attr.is_typedef:
                self.parse_typedef(basety)
                continue
            if self.is_function():
                self.function(basety, attr)
                continue
            self.global_variable(basety, attr)
        for g in self.globals:
            if g.is_function and g.is_referenced and not g.is_definition and g.is_static:
                raise error_at(g.tok, f"static function '{g.name}' used but never defined")
        return Program(self.globals, self.warnings)

    def is_function(self):
        if self.equal(";"):
            return False
        saved = self.speculation()
        try:
            ty, _, _ = self.declarator(T.int_type())
            return ty.is_func
        finally:
            self.undo(saved)

    # ================================================================ declarations
    TYPE_WORDS = {"void", "_Bool", "char", "short", "int", "long", "float", "double",
                  "signed", "unsigned", "__signed__"}
    STORAGE = {"typedef", "static", "extern", "inline", "__inline", "__inline__",
               "auto", "register", "_Noreturn", "_Thread_local"}
    QUALIFIERS = {"const", "volatile", "restrict", "__restrict", "__restrict__",
                  "__const", "__volatile__", "_Atomic"}

    def is_typename(self, tok=None):
        tok = tok or self.tok
        if tok.kind == "keyword":
            return (tok.text in self.TYPE_WORDS or tok.text in self.STORAGE
                    or tok.text in self.QUALIFIERS
                    or tok.text in ("struct", "union", "enum", "_Alignas", "typeof",
                                    "__typeof__", "__attribute__", "__extension__"))
        return self.find_typedef(tok) is not None

    def skip_attributes(self):
        while self.equal("__attribute__"):
            self.next()
            self.expect("(")
            depth = 1
            while depth:
                t = self.next()
                if t.kind == "eof":
                    raise self.error("unterminated __attribute__")
                if self.equal("(", t):
                    depth += 1
                elif self.equal(")", t):
                    depth -= 1

    def declspec(self, attr=None):
        counts = {}
        ty = None
        is_const = is_volatile = False
        start = self.tok
        while self.is_typename():
            t = self.tok
            text = t.text
            if text == "__attribute__":
                self.skip_attributes()
                continue
            if text == "__extension__":
                self.next()
                continue
            if text in self.STORAGE:
                if attr is None:
                    raise self.error("storage class specifier is not allowed in this context")
                self.next()
                if text == "typedef":
                    attr.is_typedef = True
                elif text == "static":
                    attr.is_static = True
                elif text == "extern":
                    attr.is_extern = True
                elif text in ("inline", "__inline", "__inline__"):
                    attr.is_inline = True
                elif text == "_Thread_local":
                    raise error_at(t, "_Thread_local is not supported (there are no threads)")
                if attr.is_typedef + attr.is_static + attr.is_extern > 1:
                    raise error_at(t, "typedef, static and extern may not be used together")
                continue
            if text in self.QUALIFIERS:
                self.next()
                if text in ("const", "__const"):
                    is_const = True
                elif text in ("volatile", "__volatile__"):
                    is_volatile = True
                elif text == "_Atomic":
                    raise error_at(t, "_Atomic is not supported")
                continue
            if text == "_Alignas":
                self.next()
                self.expect("(")
                if self.is_typename():
                    self.typename()
                else:
                    self.const_expr()
                self.expect(")")
                continue
            # a user type: struct/union/enum/typedef name/typeof
            if text in ("struct", "union", "enum", "typeof", "__typeof__") or \
                    (t.kind == "ident" and self.find_typedef(t)):
                if counts:
                    break                 # 'int x' then a typedef name 'x': it is the declarator
                if ty is not None:
                    break
                self.next()
                if text == "struct" or text == "union":
                    ty = self.struct_union_decl(text)
                elif text == "enum":
                    ty = self.enum_specifier()
                elif text in ("typeof", "__typeof__"):
                    ty = self.typeof_specifier()
                else:
                    ty = self.find_typedef(t)
                continue
            if ty is not None:
                raise error_at(t, f"two or more data types in declaration specifiers")
            # basic type words
            self.next()
            counts[text] = counts.get(text, 0) + 1
            if text == "__signed__":
                counts["signed"] = counts.pop("__signed__")
        if ty is None:
            ty = self.basic_type(counts, start)
        elif counts:
            raise error_at(start, "two or more data types in declaration specifiers")
        return T.qualified(ty, is_const, is_volatile)

    def basic_type(self, counts, tok):
        c = dict(counts)
        signed = c.pop("signed", 0)
        unsigned = c.pop("unsigned", 0)
        if signed and unsigned or signed > 1 or unsigned > 1:
            raise error_at(tok, "both signed and unsigned, or repeated")
        key = tuple(sorted(c.items()))
        u = bool(unsigned)
        if key == ():
            if signed or unsigned:
                return T.int_type(u)
            if tok.kind == "ident":
                raise error_at(tok, f"unknown type name '{tok.text}'")
            raise error_at(tok, f"expected a type, found {describe(tok)}")
        table = {
            (("void", 1),): "void", (("_Bool", 1),): "bool", (("char", 1),): "char",
            (("short", 1),): "short", (("int", 1), ("short", 1)): "short",
            (("int", 1),): "int", (("long", 1),): "long", (("int", 1), ("long", 1)): "long",
            (("long", 2),): "llong", (("int", 1), ("long", 2)): "llong",
            (("float", 1),): "float", (("double", 1),): "double",
            (("double", 1), ("long", 1)): "ldouble",
        }
        kind = table.get(key)
        if kind is None:
            raise error_at(tok, "invalid combination of type specifiers")
        if kind in ("void", "bool", "float", "double", "ldouble") and (signed or unsigned):
            raise error_at(tok, f"'{'signed' if signed else 'unsigned'}' can't be used with {kind}")
        if kind == "llong":
            raise error_at(tok, "long long (64-bit integers) is not supported: "
                           "every integer type is 32 bits")
        return {"void": T.void_type, "bool": T.bool_type, "float": T.float_type,
                "double": T.double_type, "ldouble": T.ldouble_type}.get(kind, None)() \
            if kind in ("void", "bool", "float", "double", "ldouble") else \
            {"char": T.char_type, "short": T.short_type, "int": T.int_type,
             "long": T.long_type}[kind](u)

    def typeof_specifier(self):
        self.expect("(")
        if self.is_typename():
            ty = self.typename()
        else:
            ty = self.expr().ty
        self.expect(")")
        return ty

    def pointers(self, ty):
        while self.consume("*"):
            ty = T.pointer_to(ty)
            const = volatile = False
            while True:
                t = self.tok.text
                if t in ("const", "__const"):
                    const = True
                elif t in ("volatile", "__volatile__"):
                    volatile = True
                elif t in ("restrict", "__restrict", "__restrict__"):
                    pass
                elif t == "__attribute__":
                    self.skip_attributes()
                    continue
                else:
                    break
                self.next()
            ty = T.qualified(ty, const, volatile)
        return ty

    def declarator(self, ty):
        """declarator = pointers ("(" declarator ")" | ident)? type-suffix

        Returns (type, name token or None, the token where the name is)."""
        ty = self.pointers(ty)
        self.skip_attributes()
        if self.equal("(") and not self.is_param_list_start():
            start = self.pos
            self.next()
            self.declarator(T.int_type())         # find where the nested part ends
            self.expect(")")
            ty = self.type_suffix(ty)
            end = self.pos
            self.pos = start + 1
            ty, name, pos = self.declarator(ty)
            self.expect(")")
            self.pos = end
            return ty, name, pos
        pos = self.tok
        name = None
        if self.tok.kind == "ident":
            name = self.next()
        ty = self.type_suffix(ty)
        self.skip_attributes()
        return ty, name, pos

    def is_param_list_start(self):
        """After '(' in a declarator: a parameter list (abstract function
        declarator) rather than a nested declarator?"""
        nxt = self.peek()
        return self.equal(")", nxt) or self.is_typename(nxt) or self.equal("...", nxt)

    def typename(self):
        ty, name, _ = self.declarator(self.declspec())
        if name is not None:
            raise error_at(name, f"unexpected name '{name.text}' in a type name")
        return ty

    def type_suffix(self, ty):
        if self.equal("("):
            return self.func_params(ty)
        if self.equal("["):
            return self.array_dimensions(ty)
        return ty

    def func_params(self, ty):
        open_tok = self.expect("(")
        if ty.is_func:
            raise error_at(open_tok, "a function can't return a function")
        if ty.kind == "array":
            raise error_at(open_tok, "a function can't return an array")
        fty = T.func_type(ty)
        if self.equal("void") and self.equal(")", self.peek()):
            self.pos += 2
            return fty
        if self.consume(")"):
            fty.has_proto = False
            return fty
        while True:
            if self.consume("..."):
                fty.variadic = True
                self.expect(")")
                break
            pty = self.declspec(VarAttr())
            pty, name, _ = self.declarator(pty)
            if pty.kind == "array":
                pty = T.qualified(T.pointer_to(pty.base), pty.is_const, pty.is_volatile)
            elif pty.is_func:
                pty = T.pointer_to(pty)
            elif pty.is_void:
                raise error_at(name or self.tok, "a parameter can't have type void")
            fty.params.append(pty)
            fty.param_names.append(name)
            if self.consume(")"):
                break
            self.expect(",")
        return fty

    def array_dimensions(self, ty):
        self.expect("[")
        while self.tok.text in ("static", "const", "volatile", "restrict"):
            self.next()
        if self.consume("]"):
            ty = self.type_suffix(ty)
            if ty.is_func:
                raise self.error("arrays of functions are not allowed")
            return T.array_of(ty, -1)
        size_tok = self.tok
        node = self.conditional()
        if not self.is_const_expr(node):
            raise error_at(size_tok, "variable-length arrays are not supported: "
                           "the size must be a constant")
        length = self.eval(node)
        if length < 0:
            raise error_at(size_tok, "the size of an array can't be negative")
        self.expect("]")
        ty = self.type_suffix(ty)
        if ty.is_func:
            raise error_at(size_tok, "arrays of functions are not allowed")
        if ty.size < 0:
            raise error_at(size_tok, "array of an incomplete type")
        return T.array_of(ty, length)

    # ---------------------------------------------------------------- struct/union/enum
    def struct_union_decl(self, kind):
        self.skip_attributes()
        tag = None
        tag_tok = self.tok
        if self.tok.kind == "ident":
            tag = self.next()
        if tag and not self.equal("{"):
            ty = self.find_tag(tag.text)
            if ty is not None:
                if ty.kind != kind:
                    raise error_at(tag, f"'{tag.text}' defined as the wrong kind of tag")
                return ty
            ty = T.struct_type(kind)
            ty.tag = tag.text
            self.scopes[-1].tags[tag.text] = ty
            return ty
        self.expect("{")
        ty = None
        if tag:
            old = self.scopes[-1].tags.get(tag.text)
            if old is not None:
                if old.kind != kind:
                    raise error_at(tag, f"'{tag.text}' defined as the wrong kind of tag")
                if old.size >= 0:
                    raise error_at(tag, f"redefinition of '{kind} {tag.text}'")
                ty = old
        if ty is None:
            ty = T.struct_type(kind)
            ty.tag = tag.text if tag else None
            if tag:
                self.scopes[-1].tags[tag.text] = ty
        members = self.struct_members(ty, tag_tok)
        self.skip_attributes()
        self.layout(ty, members, kind, tag_tok)
        return ty

    def struct_members(self, ty, tag_tok):
        members = []
        while not self.consume("}"):
            if self.equal("_Static_assert"):
                self.static_assert()
                continue
            attr = VarAttr()
            basety = self.declspec(attr)
            if attr.is_typedef or attr.is_static or attr.is_extern:
                raise self.error("storage class in a struct member")
            # anonymous struct/union member (C11)
            if basety.is_struct and self.consume(";"):
                members.append(T.Member(None, basety, tok=self.tok))
                continue
            first = True
            while not self.consume(";"):
                if not first:
                    self.expect(",")
                first = False
                mtok = self.tok
                if self.equal(":"):
                    mty = basety
                    name = None
                else:
                    mty, name, _ = self.declarator(basety)
                m = T.Member(name.text if name else None, mty, tok=name or mtok)
                if self.consume(":"):
                    if not mty.is_integer:
                        raise error_at(mtok, "a bit-field must have an integer type")
                    width_tok = self.tok
                    width = self.const_expr()
                    if width < 0 or width > 32:
                        raise error_at(width_tok, "bit-field width must be 0 to 32")
                    if width == 0 and name is not None:
                        raise error_at(width_tok, "a zero-width bit-field can't have a name")
                    m.bit_width = width
                members.append(m)
        if not members:
            raise error_at(tag_tok, "a struct or union needs at least one member")
        return members

    def layout(self, ty, members, kind, tag_tok):
        """Give each member its word offset (and bit offset for bit-fields)."""
        offset = 0          # next free word
        bit = 0             # next free bit in the current bit-field word (0 = none open)
        size = 0
        for i, m in enumerate(members):
            m.index = i
            if m.ty.kind == "array" and m.ty.array_len < 0:
                if i != len(members) - 1 or kind != "struct":
                    raise error_at(m.tok, "flexible array member not at the end of the struct")
                m.ty = T.array_of(m.ty.base, 0)
                ty.is_flexible = True
            elif m.ty.size < 0:
                raise error_at(m.tok, f"member '{m.name}' has an incomplete type")
            if kind == "union":
                m.offset = 0
                m.bit_offset = 0
                size = max(size, m.ty.size if not m.is_bitfield else 1)
                continue
            if m.is_bitfield:
                if m.bit_width == 0:
                    if bit:
                        offset += 1
                    bit = 0
                    continue
                if bit == 0 or bit + m.bit_width > 32:
                    if bit:
                        offset += 1
                    bit = 0
                m.offset = offset
                m.bit_offset = bit
                bit += m.bit_width
                if bit == 32:
                    offset += 1
                    bit = 0
                continue
            if bit:
                offset += 1
                bit = 0
            m.offset = offset
            offset += m.ty.size
        if kind == "struct":
            size = offset + (1 if bit else 0)
        ty.members = [m for m in members if not (m.is_bitfield and m.bit_width == 0)]
        ty.size = size

    def enum_specifier(self):
        self.skip_attributes()
        tag = None
        if self.tok.kind == "ident":
            tag = self.next()
        if tag and not self.equal("{"):
            ty = self.find_tag(tag.text)
            if ty is None:
                ty = T.enum_type()
                ty.tag = tag.text
                self.scopes[-1].tags[tag.text] = ty
            elif ty.kind != "enum":
                raise error_at(tag, f"'{tag.text}' is not an enum tag")
            return ty
        self.expect("{")
        ty = T.enum_type()
        ty.tag = tag.text if tag else None
        value = 0
        first = True
        while not self.consume("}"):
            if not first:
                self.expect(",")
                if self.consume("}"):
                    break
            first = False
            name = self.expect_ident()
            if self.consume("="):
                value = self.const_expr()
            if not -(1 << 31) <= value <= MASK:
                raise error_at(name, "enumerator value doesn't fit in 32 bits")
            vs = self.push_scope(name.text)
            vs.enum_ty = ty
            vs.enum_val = wrap(value, False)
            ty.enum_values[name.text] = value
            value += 1
        if tag:
            self.scopes[-1].tags[tag.text] = ty
        return ty

    def static_assert(self):
        t = self.expect("_Static_assert")
        self.expect("(")
        value = self.const_expr()
        msg = ""
        if self.consume(","):
            if self.tok.kind != "str":
                raise self.error("expected a string literal")
            msg = "".join(chr(c) for c in self.next().value)
        self.expect(")")
        self.expect(";")
        if not value:
            raise error_at(t, "static assertion failed" + (f": \"{msg}\"" if msg else ""))

    def parse_typedef(self, basety):
        first = True
        while not self.consume(";"):
            if not first:
                self.expect(",")
            first = False
            ty, name, pos = self.declarator(basety)
            if name is None:
                raise error_at(pos, "typedef name omitted")
            vs = self.scopes[-1].vars.get(name.text)
            if vs and vs.type_def and not T.is_compatible(vs.type_def, ty):
                raise error_at(name, f"conflicting types for typedef '{name.text}'")
            self.push_scope(name.text).type_def = ty

    # ================================================================ functions
    def function(self, basety, attr):
        ty, name_tok, pos = self.declarator(basety)
        if name_tok is None:
            raise error_at(pos, "function name omitted")
        name = name_tok.text
        fn = self.declare_global(name, ty, name_tok, attr, is_function=True)
        if self.consume(";"):
            return
        if fn.is_definition:
            raise error_at(name_tok, f"redefinition of '{name}'")
        if not ty.has_proto and not self.equal("{"):
            raise error_at(self.tok, "old-style (K&R) parameter declarations are not supported")
        fn.is_definition = True
        fn.ty = ty
        self.fn = fn
        self.locals = []
        self.labels = {}
        self.gotos = []
        self.enter_scope()
        if ty.return_ty.is_struct:
            fn.ret_ptr = Obj("__ret", T.pointer_to(ty.return_ty), name_tok, is_local=True,
                             is_param=True)
            self.locals.append(fn.ret_ptr)
        params = []
        for pty, pname in zip(ty.params, ty.param_names):
            if pname is None:
                var = Obj("", pty, None, is_local=True, is_param=True)
                self.locals.append(var)
            else:
                if pname.text in self.scopes[-1].vars:
                    raise error_at(pname, f"redefinition of parameter '{pname.text}'")
                var = self.new_lvar(pname.text, pty, pname)
                var.is_param = True
            if pty.size < 0:
                raise error_at(pname or name_tok, "parameter has an incomplete type")
            params.append(var)
        fn.params = params
        body_tok = self.expect("{")
        # __func__: a static string with the function's name
        self.enter_scope()
        fvar = self.new_anon_gvar(T.array_of(T.qualified(T.char_type(), const=True),
                                             len(name) + 1), "_F")
        fvar.init_data = [ord(c) for c in name] + [0]
        fvar.in_rom = True
        self.push_scope("__func__").var = fvar
        self.push_scope("__FUNCTION__").var = fvar
        fn.body = self.compound_stmt(body_tok, new_scope=False)
        self.leave_scope()
        self.leave_scope()
        for gname, gtok in self.gotos:
            if not self.labels[gname][1]:
                raise error_at(gtok, f"label '{gname}' used but not defined")
        fn.locals = self.locals
        fn.labels = self.labels
        self.fn = None

    def declare_global(self, name, ty, tok, attr, is_function):
        """Find or make the global object for a file-level declaration,
        checking that repeated declarations agree."""
        old = self.global_names.get(name)
        if old is not None:
            if old.is_function != is_function:
                raise error_at(tok, f"'{name}' redeclared as a different kind of symbol")
            if not T.is_compatible(old.ty, ty):
                raise error_at(tok, f"conflicting types for '{name}'")
            # keep the more complete type (prototype, array length)
            if is_function:
                if ty.has_proto and not old.ty.has_proto:
                    old.ty = ty
            elif ty.kind == "array" and old.ty.kind == "array" and old.ty.array_len < 0:
                old.ty = ty
            if attr.is_static and not old.is_static and not is_function:
                raise error_at(tok, f"static declaration of '{name}' follows a non-static one")
            if attr.is_static:
                old.is_static = True
            vs = self.scopes[0].vars.get(name)
            if vs is None or vs.var is not old:
                self.scopes[0].vars.setdefault(name, VarScope()).var = old
            return old
        vs = self.scopes[0].vars.get(name)
        if vs is not None and (vs.type_def or vs.enum_ty):
            raise error_at(tok, f"'{name}' redeclared as a different kind of symbol")
        var = self.new_gvar(name, ty, tok)
        var.is_function = is_function
        var.is_static = attr.is_static
        var.is_inline = attr.is_inline
        self.global_names[name] = var
        self.scopes[0].vars[name] = VarScope(var=var)
        return var

    # ================================================================ global variables
    def global_variable(self, basety, attr):
        first = True
        while not self.consume(";"):
            if not first:
                self.expect(",")
            first = False
            ty, name_tok, pos = self.declarator(basety)
            if name_tok is None:
                if basety.is_struct or basety.kind == "enum":
                    continue                      # 'struct s { ... };'
                raise error_at(pos, "variable name omitted")
            name = name_tok.text
            if ty.is_func:
                self.declare_global(name, ty, name_tok, attr, is_function=True)
                continue
            if ty.is_void:
                raise error_at(name_tok, f"variable '{name}' declared void")
            var = self.declare_global(name, ty, name_tok, attr, is_function=False)
            if attr.is_extern and not self.equal("="):
                continue
            if self.consume("="):
                if var.init_data is not None:
                    raise error_at(name_tok, f"redefinition of '{name}'")
                self.gvar_initializer(var)
                var.is_definition = True
                var.is_tentative = False
            elif not var.is_definition:
                var.is_tentative = True
                var.is_definition = True
            if var.ty.size < 0 and not (var.ty.kind == "array" and var.is_tentative):
                raise error_at(name_tok, f"storage size of '{name}' isn't known")

    # ================================================================ statements
    def compound_stmt(self, open_tok, new_scope=True):
        node = Node("block", open_tok, body=[])
        if new_scope:
            self.enter_scope()
        while not self.consume("}"):
            if self.tok.kind == "eof":
                raise error_at(open_tok, "missing '}' at end of the block")
            if self.is_typename() and not self.equal(":", self.peek()):
                node.body.extend(self.declaration())
                continue
            if self.equal("_Static_assert"):
                self.static_assert()
                continue
            node.body.append(self.stmt())
        if new_scope:
            self.leave_scope()
        return node

    def declaration(self):
        """A local declaration; returns the statements its initializers make."""
        attr = VarAttr()
        start = self.tok
        basety = self.declspec(attr)
        if attr.is_typedef:
            self.parse_typedef(basety)
            return []
        out = []
        first = True
        while not self.consume(";"):
            if not first:
                self.expect(",")
            first = False
            ty, name_tok, pos = self.declarator(basety)
            if name_tok is None:
                if basety.is_struct or basety.kind == "enum":
                    continue
                raise error_at(pos, "variable name omitted")
            name = name_tok.text
            if ty.is_void:
                raise error_at(name_tok, f"variable '{name}' declared void")
            if ty.is_func or attr.is_extern:
                # a block-scope declaration of something defined elsewhere
                var = self.declare_global(name, ty, name_tok, VarAttr(), is_function=ty.is_func)
                self.push_scope(name).var = var
                if self.equal("="):
                    raise self.error("an extern declaration can't have an initializer")
                continue
            if attr.is_static:
                var = self.new_anon_gvar(ty, "_V")
                var.asm_name = f"_V{self.counter}_{name}"
                var.name = name
                var.tok = name_tok
                self.push_scope(name).var = var
                if self.consume("="):
                    self.gvar_initializer(var)
                elif ty.size < 0:
                    raise error_at(name_tok, f"storage size of '{name}' isn't known")
                continue
            if name in self.scopes[-1].vars and self.scopes[-1].vars[name].var is not None \
                    and self.scopes[-1].vars[name].var.is_local:
                raise error_at(name_tok, f"redefinition of '{name}'")
            var = self.new_lvar(name, ty, name_tok)
            if self.equal("="):
                eq = self.next()
                expr = self.lvar_initializer(var, eq)
                out.append(Node("expr_stmt", eq, lhs=expr))
            if var.ty.size < 0:
                raise error_at(name_tok, f"storage size of '{name}' isn't known")
        return out

    def stmt(self):
        t = self.tok
        if self.equal("return"):
            self.next()
            if self.consume(";"):
                if not self.fn.ty.return_ty.is_void:
                    self.warn(t, "'return' with no value in a function returning non-void")
                return Node("return", t, lhs=None)
            e = self.expr()
            self.expect(";")
            rty = self.fn.ty.return_ty
            if rty.is_void:
                if not e.ty.is_void:
                    raise error_at(t, "'return' with a value in a function returning void")
                return Node("return", t, lhs=e)
            if rty.is_struct:
                if not (e.ty.is_struct and T.is_compatible(T.unqualified(e.ty), T.unqualified(rty))):
                    raise error_at(t, "incompatible type in return")
                return Node("return", t, lhs=e)
            return Node("return", t, lhs=self.assign_convert(e, rty, t, "return"))

        if self.equal("if"):
            self.next()
            self.expect("(")
            cond = self.condition(self.expr())
            self.expect(")")
            then = self.stmt()
            els = None
            if self.consume("else"):
                els = self.stmt()
            return Node("if", t, cond=cond, then=then, els=els)

        if self.equal("switch"):
            self.next()
            self.expect("(")
            cond = self.expr()
            self.expect(")")
            if not cond.ty.is_integer:
                raise error_at(t, "switch quantity is not an integer")
            cond = self.new_cast(cond, T.promote(cond.ty))
            node = Node("switch", t, cond=cond, cases=[], default=None,
                        brk=self.unique("_L"))
            saved = (self.switch, self.brk)
            self.switch = node
            self.brk = node.brk
            node.then = self.stmt()
            self.switch, self.brk = saved
            return node

        if self.equal("case"):
            self.next()
            if self.switch is None:
                raise error_at(t, "'case' label not within a switch statement")
            lo = self.const_expr()
            hi = lo
            if self.consume("..."):
                hi = self.const_expr()
            self.expect(":")
            cty = self.switch.cond.ty
            lo, hi = wrap(lo, cty.unsigned), wrap(hi, cty.unsigned)
            for c in self.switch.cases:
                if not (hi < c.lo or lo > c.hi):
                    raise error_at(t, "duplicate case value")
            node = Node("case", t, lo=lo, hi=hi, label=self.unique("_L"))
            self.switch.cases.append(node)
            node.lhs = self.stmt_after_label()
            return node

        if self.equal("default"):
            self.next()
            if self.switch is None:
                raise error_at(t, "'default' label not within a switch statement")
            self.expect(":")
            if self.switch.default is not None:
                raise error_at(t, "multiple default labels in one switch")
            node = Node("case", t, lo=None, hi=None, label=self.unique("_L"))
            self.switch.default = node
            node.lhs = self.stmt_after_label()
            return node

        if self.equal("for"):
            self.next()
            self.expect("(")
            self.enter_scope()
            brk, cont = self.brk, self.cont
            node = Node("for", t, init=None, cond=None, inc=None,
                        brk=self.unique("_L"), cont=self.unique("_L"))
            self.brk, self.cont = node.brk, node.cont
            if self.is_typename():
                stmts = self.declaration()
                node.init = Node("block", t, body=stmts)
            else:
                if not self.equal(";"):
                    node.init = Node("expr_stmt", t, lhs=self.expr())
                self.expect(";")
            if not self.equal(";"):
                node.cond = self.condition(self.expr())
            self.expect(";")
            if not self.equal(")"):
                node.inc = self.expr()
            self.expect(")")
            node.then = self.stmt()
            self.leave_scope()
            self.brk, self.cont = brk, cont
            return node

        if self.equal("while"):
            self.next()
            self.expect("(")
            cond = self.condition(self.expr())
            self.expect(")")
            brk, cont = self.brk, self.cont
            node = Node("for", t, init=None, cond=cond, inc=None,
                        brk=self.unique("_L"), cont=self.unique("_L"))
            self.brk, self.cont = node.brk, node.cont
            node.then = self.stmt()
            self.brk, self.cont = brk, cont
            return node

        if self.equal("do"):
            self.next()
            brk, cont = self.brk, self.cont
            node = Node("do", t, brk=self.unique("_L"), cont=self.unique("_L"))
            self.brk, self.cont = node.brk, node.cont
            node.then = self.stmt()
            self.brk, self.cont = brk, cont
            self.expect("while")
            self.expect("(")
            node.cond = self.condition(self.expr())
            self.expect(")")
            self.expect(";")
            return node

        if self.equal("goto"):
            self.next()
            name = self.expect_ident()
            self.expect(";")
            self.gotos.append((name.text, name))
            return Node("goto", t, label=self.label_for(name.text))

        if self.equal("break"):
            self.next()
            if self.brk is None:
                raise error_at(t, "'break' outside of a loop or switch")
            self.expect(";")
            return Node("goto", t, label=self.brk)

        if self.equal("continue"):
            self.next()
            if self.cont is None:
                raise error_at(t, "'continue' outside of a loop")
            self.expect(";")
            return Node("goto", t, label=self.cont)

        if t.kind == "ident" and self.equal(":", self.peek()):
            self.pos += 2
            if t.text in self.labels and self.labels[t.text][1]:
                raise error_at(t, f"duplicate label '{t.text}'")
            label = self.label_for(t.text)
            self.labels[t.text] = (label, True)
            return Node("label", t, label=label, lhs=self.stmt_after_label())

        if self.equal("{"):
            return self.compound_stmt(self.next())

        if self.equal("asm") or self.equal("__asm__") or self.equal("__asm"):
            return self.asm_stmt()

        if self.consume(";"):
            return Node("block", t, body=[])

        e = self.expr()
        self.expect(";")
        return Node("expr_stmt", t, lhs=e)

    def stmt_after_label(self):
        """The statement after a label. C23 allows a declaration or the end
        of a block there; earlier C needs a statement, so allow '}' as empty."""
        if self.equal("}"):
            return Node("block", self.tok, body=[])
        if self.is_typename() and not self.equal(":", self.peek()):
            return Node("block", self.tok, body=self.declaration())
        return self.stmt()

    def label_for(self, name):
        if name not in self.labels:
            self.labels[name] = (self.unique("_L") + "_" + name, False)
        return self.labels[name][0]

    def asm_stmt(self):
        t = self.next()
        while self.tok.text in ("volatile", "__volatile__", "goto", "inline"):
            self.next()
        self.expect("(")
        if self.tok.kind != "str":
            raise self.error("expected a string literal in asm()")
        text = "".join(chr(c) for c in self.next().value)
        if not self.equal(")"):
            raise self.error("only the basic form asm(\"text\") is supported")
        self.expect(")")
        self.expect(";")
        return Node("asm", t, text=text)

    def condition(self, node):
        """A controlling expression: must be scalar."""
        if not node.ty.is_scalar and node.ty.kind not in ("array", "func"):
            raise error_at(node.tok, "used a value of type "
                           f"'{T.type_name(node.ty)}' where a scalar is required")
        return node

    # ================================================================ expressions
    def expr(self):
        node = self.assign()
        if self.equal(","):
            t = self.next()
            rhs = self.expr()
            return self.typed(Node("comma", t, lhs=node, rhs=rhs))
        return node

    ASSIGN_OPS = {"+=": "add", "-=": "sub", "*=": "mul", "/=": "div", "%=": "mod",
                  "&=": "bitand", "|=": "bitor", "^=": "bitxor", "<<=": "shl",
                  ">>=": "shr"}

    def assign(self):
        node = self.conditional()
        t = self.tok
        if self.equal("="):
            self.next()
            rhs = self.assign()
            return self.new_assign(node, rhs, t)
        if t.kind == "punct" and t.text in self.ASSIGN_OPS:
            self.next()
            rhs = self.assign()
            return self.new_assign_op(self.ASSIGN_OPS[t.text], node, rhs, t)
        return node

    def check_lvalue(self, node, t, what="assignment"):
        if not self.is_lvalue(node):
            raise error_at(t, f"lvalue required as left operand of {what}")
        if node.ty.kind == "array":
            raise error_at(t, f"{what} to an expression with array type")
        if node.ty.is_const:
            raise error_at(t, f"{what} of read-only location")
        if node.ty.is_struct and self.has_const_member(node.ty):
            raise error_at(t, f"{what} of a struct with a const member")

    def has_const_member(self, ty):
        for m in ty.members:
            if m.ty.is_const or (m.ty.is_struct and self.has_const_member(m.ty)):
                return True
        return False

    def is_lvalue(self, node):
        if node.kind in ("var", "deref"):
            return True
        if node.kind == "member":
            return True
        return False

    def new_assign(self, lhs, rhs, t):
        self.check_lvalue(lhs, t)
        if lhs.ty.is_struct:
            if not (rhs.ty.is_struct and T.is_compatible(T.unqualified(lhs.ty),
                                                          T.unqualified(rhs.ty))):
                raise error_at(t, "incompatible types in assignment")
            return self.typed(Node("assign", t, lhs=lhs, rhs=rhs))
        rhs = self.assign_convert(rhs, lhs.ty, t, "assignment")
        return self.typed(Node("assign", t, lhs=lhs, rhs=rhs))

    def new_assign_op(self, op, lhs, rhs, t):
        self.check_lvalue(lhs, t)
        lty = lhs.ty
        if op in ("add", "sub") and lty.kind == "ptr":
            if not rhs.ty.is_integer:
                raise error_at(t, "invalid operands to pointer arithmetic")
            self.require_complete(lty.base, t)
            rhs = self.new_cast(rhs, T.int_type())
            if lty.base.size != 1:
                rhs = self.fold(self.typed(Node("mul", t, lhs=rhs,
                                                rhs=self.new_num(lty.base.size, t))))
            return self.typed(Node("assign_op", t, op=op, lhs=lhs, rhs=rhs))
        if not lty.is_arith or not rhs.ty.is_arith:
            raise error_at(t, "invalid operands to a compound assignment")
        if op in ("mod", "bitand", "bitor", "bitxor", "shl", "shr") and \
                (not lty.is_integer or not rhs.ty.is_integer):
            raise error_at(t, "invalid operands: this operator needs integers")
        if op in ("shl", "shr"):
            rhs = self.new_cast(rhs, T.promote(rhs.ty))
            return self.typed(Node("assign_op", t, op=op, lhs=lhs, rhs=rhs,
                                   calc_ty=T.promote(lty)))
        cty = T.common_type(lty, rhs.ty)
        rhs = self.new_cast(rhs, cty)
        return self.typed(Node("assign_op", t, op=op, lhs=lhs, rhs=rhs, calc_ty=cty))

    def assign_convert(self, rhs, ty, t, what):
        """Convert rhs to ty as assignment does, checking that it is allowed."""
        rty = rhs.ty
        if ty.is_arith and rty.is_arith:
            return self.new_cast(rhs, ty)
        if ty.kind == "ptr":
            if rty.is_ptr_like or rty.is_func:
                base = rty.base if rty.is_ptr_like else rty
                if not (ty.base.is_void or base.is_void or
                        T.is_compatible(T.unqualified(ty.base), T.unqualified(base))):
                    self.warn(t, f"incompatible pointer types in {what} "
                              f"('{T.type_name(ty)}' from '{T.type_name(rty)}')")
                return self.new_cast(rhs, ty)
            if rty.is_integer:
                if not self.is_null_constant(rhs):
                    self.warn(t, f"{what} makes a pointer from an integer without a cast")
                return self.new_cast(rhs, ty)
        if ty.kind == "bool" and rty.is_ptr_like:
            return self.new_cast(rhs, ty)
        if ty.is_integer and rty.is_ptr_like:
            self.warn(t, f"{what} makes an integer from a pointer without a cast")
            return self.new_cast(rhs, ty)
        if ty.is_struct and rty.is_struct and T.is_compatible(T.unqualified(ty),
                                                              T.unqualified(rty)):
            return rhs
        raise error_at(t, f"incompatible types in {what}: can't convert "
                       f"'{T.type_name(rty)}' to '{T.type_name(ty)}'")

    def is_null_constant(self, node):
        return node.ty.is_integer and self.is_const_expr(node) and self.eval(node) == 0

    def conditional(self):
        cond = self.logor()
        if not self.equal("?"):
            return cond
        t = self.next()
        self.condition(cond)
        if self.equal(":"):                  # GNU a ?: b
            raise error_at(t, "the 'a ?: b' form is a GNU extension and is not supported")
        then = self.expr()
        self.expect(":")
        els = self.conditional()
        node = Node("cond", t, cond=cond, then=then, els=els)
        tt, et = then.ty, els.ty
        if tt.is_arith and et.is_arith:
            ty = T.common_type(tt, et)
            node.then = self.new_cast(then, ty)
            node.els = self.new_cast(els, ty)
            node.ty = ty
        elif tt.is_void or et.is_void:
            node.ty = T.void_type()
        elif tt.is_struct or et.is_struct:
            if not (tt.is_struct and et.is_struct and
                    T.is_compatible(T.unqualified(tt), T.unqualified(et))):
                raise error_at(t, "type mismatch in conditional expression")
            node.ty = tt
        elif (tt.is_ptr_like or tt.is_func) and self.is_null_constant(els):
            node.ty = self.decay(tt)
            node.els = self.new_cast(els, node.ty)
        elif (et.is_ptr_like or et.is_func) and self.is_null_constant(then):
            node.ty = self.decay(et)
            node.then = self.new_cast(then, node.ty)
        elif (tt.is_ptr_like or tt.is_func) and (et.is_ptr_like or et.is_func):
            dt, de = self.decay(tt), self.decay(et)
            node.ty = de if dt.base.is_void is False and de.base.is_void else dt
        else:
            raise error_at(t, "type mismatch in conditional expression")
        return self.fold(node)

    @staticmethod
    def decay(ty):
        if ty.kind == "array":
            return T.pointer_to(ty.base)
        if ty.is_func:
            return T.pointer_to(ty)
        return ty

    def logor(self):
        node = self.logand()
        while self.equal("||"):
            t = self.next()
            node = self.fold(self.typed(Node("logor", t, lhs=self.condition(node),
                                             rhs=self.condition(self.logand()))))
        return node

    def logand(self):
        node = self.bitor()
        while self.equal("&&"):
            t = self.next()
            node = self.fold(self.typed(Node("logand", t, lhs=self.condition(node),
                                             rhs=self.condition(self.bitor()))))
        return node

    def bitor(self):
        node = self.bitxor()
        while self.equal("|"):
            t = self.next()
            node = self.new_binary("bitor", node, self.bitxor(), t)
        return node

    def bitxor(self):
        node = self.bitand()
        while self.equal("^"):
            t = self.next()
            node = self.new_binary("bitxor", node, self.bitand(), t)
        return node

    def bitand(self):
        node = self.equality()
        while self.equal("&"):
            t = self.next()
            node = self.new_binary("bitand", node, self.equality(), t)
        return node

    def equality(self):
        node = self.relational()
        while True:
            t = self.tok
            if self.consume("=="):
                node = self.new_compare("eq", node, self.relational(), t)
            elif self.consume("!="):
                node = self.new_compare("ne", node, self.relational(), t)
            else:
                return node

    def relational(self):
        node = self.shift()
        while True:
            t = self.tok
            if self.consume("<"):
                node = self.new_compare("lt", node, self.shift(), t)
            elif self.consume("<="):
                node = self.new_compare("le", node, self.shift(), t)
            elif self.consume(">"):
                node = self.new_compare("lt", self.shift(), node, t, swapped=True)
            elif self.consume(">="):
                node = self.new_compare("le", self.shift(), node, t, swapped=True)
            else:
                return node

    def shift(self):
        node = self.add()
        while True:
            t = self.tok
            if self.consume("<<"):
                node = self.new_binary("shl", node, self.add(), t)
            elif self.consume(">>"):
                node = self.new_binary("shr", node, self.add(), t)
            else:
                return node

    def add(self):
        node = self.mul()
        while True:
            t = self.tok
            if self.consume("+"):
                node = self.new_add(node, self.mul(), t)
            elif self.consume("-"):
                node = self.new_sub(node, self.mul(), t)
            else:
                return node

    def mul(self):
        node = self.cast()
        while True:
            t = self.tok
            if self.consume("*"):
                node = self.new_binary("mul", node, self.cast(), t)
            elif self.consume("/"):
                node = self.new_binary("div", node, self.cast(), t)
            elif self.consume("%"):
                node = self.new_binary("mod", node, self.cast(), t)
            else:
                return node

    def cast(self):
        if self.equal("(") and self.is_typename(self.peek()):
            start = self.pos
            t = self.next()
            ty = self.typename()
            self.expect(")")
            if self.equal("{"):                  # compound literal
                self.pos = start
                return self.unary()
            operand = self.cast()
            if ty.is_void:
                return self.typed(Node("cast", t, lhs=operand, ty=T.void_type()))
            if not ty.is_scalar:
                raise error_at(t, f"cast to non-scalar type '{T.type_name(ty)}'")
            if not (operand.ty.is_scalar or operand.ty.kind in ("array", "func")):
                raise error_at(t, f"cast of a non-scalar value of type "
                               f"'{T.type_name(operand.ty)}'")
            if ty.is_float and operand.ty.is_ptr_like or \
                    ty.kind == "ptr" and operand.ty.is_float:
                raise error_at(t, "can't convert between a pointer and a floating type")
            node = self.new_cast(operand, T.unqualified(ty), t)
            return node
        return self.unary()

    def unary(self):
        t = self.tok
        if self.consume("+"):
            operand = self.cast()
            if not operand.ty.is_arith:
                raise error_at(t, "wrong type argument to unary plus")
            return self.new_cast(operand, T.promote(operand.ty))
        if self.consume("-"):
            operand = self.cast()
            if not operand.ty.is_arith:
                raise error_at(t, "wrong type argument to unary minus")
            operand = self.new_cast(operand, T.promote(operand.ty))
            return self.fold(self.typed(Node("neg", t, lhs=operand)))
        if self.consume("&"):
            operand = self.cast()
            return self.new_addr(operand, t)
        if self.consume("*"):
            operand = self.cast()
            return self.new_deref(operand, t)
        if self.consume("!"):
            operand = self.condition(self.cast())
            return self.fold(self.typed(Node("not", t, lhs=operand)))
        if self.consume("~"):
            operand = self.cast()
            if not operand.ty.is_integer:
                raise error_at(t, "wrong type argument to bit-complement")
            operand = self.new_cast(operand, T.promote(operand.ty))
            return self.fold(self.typed(Node("bitnot", t, lhs=operand)))
        if self.consume("++"):
            return self.new_incdec("preinc", self.unary(), t)
        if self.consume("--"):
            return self.new_incdec("predec", self.unary(), t)
        if self.equal("sizeof"):
            self.next()
            if self.equal("(") and self.is_typename(self.peek()):
                start = self.pos
                self.next()
                ty = self.typename()
                self.expect(")")
                if self.equal("{"):             # sizeof (type){...}
                    self.pos = start
                    node = self.unary()
                    ty = node.ty
            else:
                node = self.unary()
                ty = node.ty
                if node.kind == "member" and node.member.is_bitfield:
                    raise error_at(t, "sizeof applied to a bit-field")
            if ty.is_func:
                raise error_at(t, "sizeof applied to a function type")
            if ty.size < 0:
                raise error_at(t, f"sizeof applied to an incomplete type '{T.type_name(ty)}'")
            return self.new_num(ty.size, t, T.int_type(True))
        if self.equal("_Alignof") or self.equal("__alignof__"):
            self.next()
            self.expect("(")
            if self.is_typename():
                self.typename()
            else:
                self.expr()
            self.expect(")")
            return self.new_num(1, t, T.int_type(True))
        return self.postfix()

    def postfix(self):
        t = self.tok
        if self.equal("(") and self.is_typename(self.peek()):
            # compound literal: (type){ initializer }
            self.next()
            ty = self.typename()
            self.expect(")")
            if not self.equal("{"):
                raise self.error("expected '{' for a compound literal")
            if self.fn is None:
                var = self.new_anon_gvar(ty, "_C")
                self.gvar_initializer(var)
                node = self.var_node(var, t)
            else:
                var = Obj(self.unique("_c"), ty, t, is_local=True)
                self.locals.append(var)
                init = self.lvar_initializer(var, t)
                node = self.typed(Node("comma", t, lhs=init, rhs=self.var_node(var, t)))
            return self.postfix_ops(node)
        return self.postfix_ops(self.primary())

    def postfix_ops(self, node):
        while True:
            t = self.tok
            if self.consume("("):
                node = self.funcall(node, t)
                continue
            if self.consume("["):
                idx = self.expr()
                self.expect("]")
                node = self.new_deref(self.new_add(node, idx, t), t)
                continue
            if self.consume("."):
                node = self.struct_ref(node, self.expect_ident(), t)
                continue
            if self.consume("->"):
                node = self.struct_ref(self.new_deref(node, t), self.expect_ident(), t)
                continue
            if self.consume("++"):
                node = self.new_incdec("postinc", node, t)
                continue
            if self.consume("--"):
                node = self.new_incdec("postdec", node, t)
                continue
            return node

    def struct_ref(self, node, name, t):
        if not node.ty.is_struct:
            raise error_at(t, f"request for member '{name.text}' in something that is "
                           "not a struct or union")
        if node.ty.size < 0:
            raise error_at(t, f"'{T.type_name(node.ty)}' is incomplete")
        path = self.find_member(node.ty, name.text)
        if path is None:
            raise error_at(name, f"'{T.type_name(node.ty)}' has no member named '{name.text}'")
        for m in path:
            mty = m.ty
            if node.ty.is_const or node.ty.is_volatile:
                mty = T.qualified(mty, node.ty.is_const, node.ty.is_volatile)
            node = Node("member", t, lhs=node, member=m)
            node.ty = mty
        return node

    def find_member(self, ty, name):
        """The member path to a name, looking inside anonymous members too."""
        for m in ty.members:
            if m.name is None and m.ty.is_struct:
                inner = self.find_member(m.ty, name)
                if inner is not None:
                    return [m] + inner
            elif m.name == name:
                return [m]
        return None

    def new_incdec(self, kind, operand, t):
        what = "increment" if "inc" in kind else "decrement"
        self.check_lvalue(operand, t, what)
        ty = operand.ty
        if ty.kind == "ptr":
            self.require_complete(ty.base, t)
            step = ty.base.size
        elif ty.is_float:
            step = 1.0
        elif ty.is_integer:
            step = 1
        else:
            raise error_at(t, f"wrong type argument to {what}")
        node = Node(kind, t, lhs=operand, step=step)
        node.ty = ty
        return node

    def require_complete(self, ty, t):
        if ty.is_void:
            raise error_at(t, "pointer arithmetic on 'void *'")
        if ty.size < 0 or ty.is_func:
            raise error_at(t, f"arithmetic on a pointer to an incomplete type "
                           f"'{T.type_name(ty)}'")

    def funcall(self, fn_node, t):
        fty = fn_node.ty
        if fty.kind == "ptr" and fty.base.is_func:
            fty = fty.base
        if not fty.is_func:
            raise error_at(t, "called object is not a function or function pointer")
        args = []
        i = 0
        while not self.consume(")"):
            if args:
                self.expect(",")
            arg = self.assign()
            if i < len(fty.params):
                arg = self.assign_convert(arg, T.unqualified(fty.params[i]), arg.tok,
                                          f"argument {i + 1}")
            else:
                if fty.has_proto and not fty.variadic:
                    raise error_at(arg.tok, "too many arguments to function")
                # default argument promotions
                if arg.ty.is_integer:
                    arg = self.new_cast(arg, T.promote(arg.ty))
                elif arg.ty.is_float:
                    arg = self.new_cast(arg, T.double_type())
                elif arg.ty.kind in ("array", "func"):
                    arg = self.new_cast(arg, self.decay(arg.ty))
            if arg.ty.is_void:
                raise error_at(arg.tok, "invalid use of a void expression")
            args.append(arg)
            i += 1
        if fty.has_proto and len(args) < len(fty.params):
            raise error_at(t, "too few arguments to function")
        node = Node("funcall", t, func=fn_node, args=args, func_ty=fty, ret_buf=None)
        node.ty = fty.return_ty
        if fty.return_ty.is_struct:
            if fty.return_ty.size < 0:
                raise error_at(t, "calling a function that returns an incomplete type")
            if self.fn is not None:
                buf = Obj(self.unique("_r"), fty.return_ty, t, is_local=True)
                self.locals.append(buf)
                node.ret_buf = buf
            else:
                raise error_at(t, "function call at file scope")
        if fn_node.kind == "var" and fn_node.var.is_function:
            fn_node.var.is_referenced = True
        return node

    def primary(self):
        t = self.tok
        if self.consume("("):
            if self.equal("{"):
                raise error_at(t, "statement expressions ({ ... }) are a GNU extension "
                               "and are not supported")
            node = self.expr()
            self.expect(")")
            return node
        if t.kind == "num":
            self.next()
            return self.number(t)
        if t.kind == "char":
            self.next()
            ty = T.int_type()
            return self.new_num(wrap(t.value, False), t, ty)
        if t.kind == "str":
            self.next()
            var = self.new_string(t)
            return self.var_node(var, t)
        if self.equal("_Generic"):
            return self.generic_selection()
        if t.kind == "ident":
            self.next()
            if t.text.startswith("__builtin_"):
                return self.builtin(t)
            vs = self.find_var(t.text)
            if vs is not None:
                if vs.var is not None:
                    if vs.var.is_function:
                        vs.var.is_referenced = True
                    return self.var_node(vs.var, t)
                if vs.enum_ty is not None:
                    return self.new_num(vs.enum_val, t, T.int_type())
            if self.equal("("):
                raise error_at(t, f"implicit declaration of function '{t.text}' "
                               "(include its header, or declare it first)")
            raise error_at(t, f"'{t.text}' undeclared")
        raise error_at(t, f"expected an expression before {describe(t)}")

    def number(self, t):
        kind, suffix, base = t.ty
        if kind == "float":
            ty = T.float_type() if suffix == "f" else \
                T.ldouble_type() if suffix == "l" else T.double_type()
            return self.new_num(f32(t.value), t, ty)
        v = t.value
        u = "u" in suffix
        if v > MASK:
            raise error_at(t, "integer constant is too large (integers are 32 bits)")
        if v > 0x7FFFFFFF and not u:
            if base == 10 and "u" not in suffix:
                # C99 would make this 'long long', which this compiler doesn't have
                self.warn(t, "integer constant is so large that it is unsigned")
            u = True
        kind = "long" if "l" in suffix else "int"
        return self.new_num(wrap(v, u), t, T.long_type(u) if kind == "long" else T.int_type(u))

    def generic_selection(self):
        t = self.next()
        self.expect("(")
        ctrl = self.assign()
        cty = T.unqualified(self.decay(ctrl.ty))
        self.expect(",")
        chosen = default = None
        while True:
            if self.consume("default"):
                self.expect(":")
                node = self.assign()
                default = node
            else:
                ty = self.typename()
                self.expect(":")
                node = self.assign()
                if T.is_compatible(cty, T.unqualified(ty)):
                    chosen = node
            if self.consume(")"):
                break
            self.expect(",")
        result = chosen or default
        if result is None:
            raise error_at(t, f"_Generic: no association matches type '{T.type_name(cty)}'")
        return result

    def builtin(self, t):
        name = t.text
        if name == "__builtin_va_start":
            self.expect("(")
            self.expect(")")
            if self.fn is None or not self.fn.ty.variadic:
                raise error_at(t, "va_start used in a function with fixed arguments")
            node = Node("builtin", t, name="va_start", args=[])
            node.ty = T.pointer_to(T.char_type())
            return node
        if name == "__builtin_offsetof":
            self.expect("(")
            ty = self.typename()
            self.expect(",")
            offset = 0
            cur = ty
            while True:
                mt = self.expect_ident()
                if not cur.is_struct:
                    raise error_at(mt, "offsetof on a non-struct type")
                path = self.find_member(cur, mt.text)
                if path is None:
                    raise error_at(mt, f"'{T.type_name(cur)}' has no member named '{mt.text}'")
                for m in path:
                    if m.is_bitfield:
                        raise error_at(mt, "offsetof applied to a bit-field")
                    offset += m.offset
                    cur = m.ty
                if self.consume("."):
                    continue
                if self.consume("["):
                    idx = self.const_expr()
                    self.expect("]")
                    if cur.kind != "array":
                        raise error_at(mt, "subscript of a non-array member in offsetof")
                    offset += idx * cur.base.size
                    cur = cur.base
                    if self.consume("."):
                        continue
                break
            self.expect(")")
            return self.new_num(offset, t, T.int_type(True))
        if name == "__builtin_expect":
            self.expect("(")
            e = self.assign()
            self.expect(",")
            self.assign()
            self.expect(")")
            return e
        if name in ("__builtin_out", "__builtin_in"):
            # device I/O through COMM: __builtin_out(device, value), __builtin_in(device)
            self.expect("(")
            args = [self.assign_convert(self.assign(), T.int_type(), t, "argument")]
            if name == "__builtin_out":
                self.expect(",")
                args.append(self.assign_convert(self.assign(), T.int_type(), t, "argument"))
            self.expect(")")
            node = Node("builtin", t, name=name[len("__builtin_"):], args=args)
            node.ty = T.void_type() if name == "__builtin_out" else T.int_type()
            return node
        if name == "__builtin_unreachable" or name == "__builtin_trap":
            self.expect("(")
            self.expect(")")
            node = Node("builtin", t, name="halt", args=[])
            node.ty = T.void_type()
            return node
        raise error_at(t, f"unknown builtin '{name}'")

    # ================================================================ node helpers
    def var_node(self, var, t):
        node = Node("var", t, var=var)
        node.ty = var.ty
        return node

    def new_num(self, val, t, ty=None):
        node = Node("num", t, val=val)
        node.ty = ty or T.int_type()
        return node

    def typed(self, node):
        """Give a freshly built node its type (operands already typed)."""
        k = node.kind
        if k == "comma":
            node.ty = node.rhs.ty
        elif k in ("logand", "logor", "not", "eq", "ne", "lt", "le"):
            node.ty = T.int_type()
        elif k in ("neg", "bitnot"):
            node.ty = node.lhs.ty
        elif k == "assign":
            node.ty = T.unqualified(node.lhs.ty)
        elif k == "assign_op":
            node.ty = T.unqualified(node.lhs.ty)
        elif k in ("add", "sub", "mul", "div", "mod", "bitand", "bitor", "bitxor"):
            node.ty = node.lhs.ty
        elif k in ("shl", "shr"):
            node.ty = node.lhs.ty
        elif k == "cast":
            pass
        return node

    def new_cast(self, expr, ty, t=None):
        """Convert expr to ty (no-op casts are still recorded; folding
        removes the trivial ones)."""
        ty = T.unqualified(ty)
        if expr.ty is ty or self.same_type(expr.ty, ty):
            return expr
        node = Node("cast", t or expr.tok, lhs=expr)
        node.ty = ty
        return self.fold(node)

    @staticmethod
    def same_type(a, b):
        """Arithmetic types that are the same apart from qualifiers: a cast
        between them changes nothing."""
        return (a.is_arith and a.kind == b.kind and a.unsigned == b.unsigned
                and not a.is_const and not a.is_volatile)

    def arith_operands(self, lhs, rhs, t, what):
        if not lhs.ty.is_arith or not rhs.ty.is_arith:
            raise error_at(t, f"invalid operands to binary {what} "
                           f"('{T.type_name(lhs.ty)}' and '{T.type_name(rhs.ty)}')")
        ty = T.common_type(lhs.ty, rhs.ty)
        return self.new_cast(lhs, ty), self.new_cast(rhs, ty)

    SYMBOLS = {"add": "+", "sub": "-", "mul": "*", "div": "/", "mod": "%",
               "bitand": "&", "bitor": "|", "bitxor": "^", "shl": "<<", "shr": ">>",
               "eq": "==", "ne": "!=", "lt": "<", "le": "<="}

    def new_binary(self, kind, lhs, rhs, t):
        sym = self.SYMBOLS[kind]
        if kind in ("shl", "shr"):
            if not lhs.ty.is_integer or not rhs.ty.is_integer:
                raise error_at(t, f"invalid operands to binary {sym}")
            lhs = self.new_cast(lhs, T.promote(lhs.ty))
            rhs = self.new_cast(rhs, T.promote(rhs.ty))
        else:
            lhs, rhs = self.arith_operands(lhs, rhs, t, sym)
            if kind in ("mod", "bitand", "bitor", "bitxor") and not lhs.ty.is_integer:
                raise error_at(t, f"invalid operands to binary {sym} (needs integers)")
        return self.fold(self.typed(Node(kind, t, lhs=lhs, rhs=rhs)))

    def new_compare(self, kind, lhs, rhs, t, swapped=False):
        lt, rt = lhs.ty, rhs.ty
        if lt.is_arith and rt.is_arith:
            lhs, rhs = self.arith_operands(lhs, rhs, t, "comparison")
        elif (lt.is_ptr_like or lt.is_func) and (rt.is_ptr_like or rt.is_func):
            lhs = self.new_cast(lhs, self.decay(lt))
            rhs = self.new_cast(rhs, self.decay(rt))
        elif (lt.is_ptr_like or lt.is_func) and rt.is_integer:
            if not self.is_null_constant(rhs):
                self.warn(t, "comparison between a pointer and an integer")
            lhs = self.new_cast(lhs, self.decay(lt))
            rhs = self.new_cast(rhs, lhs.ty)
        elif lt.is_integer and (rt.is_ptr_like or rt.is_func):
            if not self.is_null_constant(lhs):
                self.warn(t, "comparison between a pointer and an integer")
            rhs = self.new_cast(rhs, self.decay(rt))
            lhs = self.new_cast(lhs, rhs.ty)
        else:
            raise error_at(t, f"invalid operands to a comparison "
                           f"('{T.type_name(lt)}' and '{T.type_name(rt)}')")
        node = Node(kind, t, lhs=lhs, rhs=rhs)
        node.swapped = swapped
        return self.fold(self.typed(node))

    def new_add(self, lhs, rhs, t):
        lt, rt = lhs.ty, rhs.ty
        if lt.is_arith and rt.is_arith:
            return self.new_binary("add", lhs, rhs, t)
        if lt.is_ptr_like and rt.is_ptr_like:
            raise error_at(t, "invalid operands to binary + (two pointers)")
        if rt.is_ptr_like and lt.is_integer:
            lhs, rhs = rhs, lhs
            lt, rt = rt, lt
        if not (lt.is_ptr_like and rt.is_integer):
            raise error_at(t, f"invalid operands to binary + ('{T.type_name(lt)}' "
                           f"and '{T.type_name(rt)}')")
        self.require_complete(lt.base, t)
        rhs = self.new_cast(rhs, T.int_type())
        if lt.base.size != 1:
            rhs = self.fold(self.typed(Node("mul", t, lhs=rhs,
                                            rhs=self.new_num(lt.base.size, t))))
        lhs = self.new_cast(lhs, self.decay(lt))
        node = Node("add", t, lhs=lhs, rhs=rhs)
        node.ty = lhs.ty
        return self.fold(node)

    def new_sub(self, lhs, rhs, t):
        lt, rt = lhs.ty, rhs.ty
        if lt.is_arith and rt.is_arith:
            return self.new_binary("sub", lhs, rhs, t)
        if lt.is_ptr_like and rt.is_integer:
            self.require_complete(lt.base, t)
            rhs = self.new_cast(rhs, T.int_type())
            if lt.base.size != 1:
                rhs = self.fold(self.typed(Node("mul", t, lhs=rhs,
                                                rhs=self.new_num(lt.base.size, t))))
            lhs = self.new_cast(lhs, self.decay(lt))
            node = Node("sub", t, lhs=lhs, rhs=rhs)
            node.ty = lhs.ty
            return self.fold(node)
        if lt.is_ptr_like and rt.is_ptr_like:
            if not T.is_compatible(T.unqualified(lt.base), T.unqualified(rt.base)):
                raise error_at(t, "invalid operands to binary - (pointers to different types)")
            self.require_complete(lt.base, t)
            lhs = self.new_cast(lhs, self.decay(lt))
            rhs = self.new_cast(rhs, self.decay(rt))
            node = Node("sub", t, lhs=lhs, rhs=rhs)
            node.ty = T.int_type()
            diff = self.fold(node)
            if lt.base.size != 1:
                diff = self.fold(self.typed(Node("div", t, lhs=diff,
                                                 rhs=self.new_num(lt.base.size, t))))
            return diff
        raise error_at(t, f"invalid operands to binary - ('{T.type_name(lt)}' "
                       f"and '{T.type_name(rt)}')")

    def new_addr(self, operand, t):
        if operand.kind == "member" and operand.member.is_bitfield:
            raise error_at(t, "cannot take the address of a bit-field")
        if operand.kind == "var":
            if operand.var.is_local:
                operand.var.addr_taken = True
        elif operand.ty.is_func and operand.kind == "deref":
            return operand.lhs                    # &*f
        elif operand.kind not in ("deref", "member"):
            if operand.kind == "comma" and operand.rhs.kind == "var":
                operand.rhs.var.addr_taken = True    # &(compound literal)
                node = Node("addr", t, lhs=operand)
                node.ty = T.pointer_to(operand.ty)
                return node
            raise error_at(t, "lvalue required as unary '&' operand")
        self.mark_addr_taken(operand)
        node = Node("addr", t, lhs=operand)
        node.ty = T.pointer_to(operand.ty)
        return node

    def mark_addr_taken(self, node):
        """A local whose address escapes has to live in memory."""
        while node.kind == "member":
            node = node.lhs
        if node.kind == "var" and node.var.is_local:
            node.var.addr_taken = True

    def new_deref(self, operand, t):
        ty = operand.ty
        if ty.is_func:
            return operand                        # *f is f
        if not ty.is_ptr_like:
            raise error_at(t, "invalid type argument of unary '*' "
                           f"(have '{T.type_name(ty)}')")
        if ty.kind == "array":
            self.mark_addr_taken(operand)
        base = ty.base
        if base.is_void:
            raise error_at(t, "dereferencing a 'void *' pointer")
        node = Node("deref", t, lhs=operand)
        node.ty = base
        return node

    # ================================================================ folding
    def fold(self, node):
        """Replace a constant integer/float expression by its value."""
        if node.kind in ("num",):
            return node
        if not (node.ty is not None and (node.ty.is_arith or node.ty.kind == "ptr")):
            return node
        if node.kind == "cast" and node.ty.kind == "ptr":
            return node
        if not self.is_const_expr(node, allow_addr=False):
            return node
        try:
            if node.ty.is_float:
                val = self.eval_float(node)
            else:
                val = self.eval(node)
        except CError:
            return node
        num = self.new_num(val, node.tok, node.ty)
        return num

    # ================================================================ constant expressions
    def const_expr(self):
        node = self.conditional()
        if not self.is_const_expr(node):
            raise error_at(node.tok, "expression is not a constant")
        return self.eval(node)

    def is_const_expr(self, node, allow_addr=False):
        k = node.kind
        if k == "num":
            return True
        if k in ("add", "sub", "mul", "div", "mod", "bitand", "bitor", "bitxor", "shl",
                 "shr", "eq", "ne", "lt", "le", "logand", "logor"):
            return self.is_const_expr(node.lhs, allow_addr) and \
                self.is_const_expr(node.rhs, allow_addr)
        if k == "cond":
            return all(self.is_const_expr(n, allow_addr) for n in (node.cond, node.then, node.els))
        if k == "comma":
            return False
        if k in ("neg", "not", "bitnot"):
            return self.is_const_expr(node.lhs, allow_addr)
        if k == "cast":
            if node.ty.is_void:
                return False
            return self.is_const_expr(node.lhs, allow_addr)
        return False

    def eval(self, node):
        """Value of an integer constant expression (32-bit, wrapped)."""
        v = self._eval(node)
        if isinstance(v, float):
            v = int(v)
        return wrap(v, node.ty.unsigned if node.ty and node.ty.is_integer else False)

    def _eval(self, node):
        k = node.kind
        ty = node.ty
        u = ty.unsigned if ty is not None else False
        if k == "num":
            return node.val
        if ty is not None and ty.is_float and k != "cast":
            return self.eval_float(node)
        if k in ("add", "sub", "mul", "div", "mod", "bitand", "bitor", "bitxor"):
            a, b = self._eval(node.lhs), self._eval(node.rhs)
            if isinstance(a, float) or isinstance(b, float):
                return self.eval_float(node)
            if u:
                a, b = a & MASK, b & MASK
            if k == "add":
                return wrap(a + b, u)
            if k == "sub":
                return wrap(a - b, u)
            if k == "mul":
                return wrap(a * b, u)
            if k in ("div", "mod"):
                if b == 0:
                    raise error_at(node.tok, "division by zero in a constant expression")
                q = abs(a) // abs(b)
                if (a < 0) != (b < 0):
                    q = -q
                return wrap(q if k == "div" else a - q * b, u)
            if k == "bitand":
                return wrap(a & b, u)
            if k == "bitor":
                return wrap(a | b, u)
            return wrap(a ^ b, u)
        if k in ("shl", "shr"):
            a, b = self._eval(node.lhs), self._eval(node.rhs)
            b &= MASK
            if b >= 32:
                raise error_at(node.tok, "shift count is 32 or more")
            if k == "shl":
                return wrap(a << b, u)
            if u:
                return wrap((a & MASK) >> b, u)
            return wrap(a >> b, u)
        if k in ("eq", "ne", "lt", "le"):
            lt = node.lhs.ty
            if lt.is_float:
                a, b = self.eval_float(node.lhs), self.eval_float(node.rhs)
            else:
                a, b = self._eval(node.lhs), self._eval(node.rhs)
                if lt.unsigned:
                    a, b = a & MASK, b & MASK
            return int({"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b}[k])
        if k == "logand":
            return int(bool(self._truth(node.lhs)) and bool(self._truth(node.rhs)))
        if k == "logor":
            return int(bool(self._truth(node.lhs)) or bool(self._truth(node.rhs)))
        if k == "cond":
            return self._eval(node.then) if self._truth(node.cond) else self._eval(node.els)
        if k == "neg":
            return wrap(-self._eval(node.lhs), u)
        if k == "not":
            return int(not self._truth(node.lhs))
        if k == "bitnot":
            return wrap(~self._eval(node.lhs), u)
        if k == "cast":
            src = node.lhs.ty
            v = self.eval_float(node.lhs) if src.is_float else self._eval(node.lhs)
            if ty.is_float:
                return f32(float(v))
            if ty.kind == "bool":
                return int(v != 0)
            if isinstance(v, float):
                if v != v or v in (float("inf"), float("-inf")):
                    return 0
                v = int(v)
            return wrap(v, u)
        raise error_at(node.tok, "expression is not a constant")

    def _truth(self, node):
        if node.ty.is_float:
            return self.eval_float(node) != 0.0
        return self._eval(node) != 0

    def eval_float(self, node):
        k = node.kind
        if k == "num":
            return float(node.val) if not node.ty.is_float else node.val
        if k == "cast":
            if node.lhs.ty.is_float:
                return f32(self.eval_float(node.lhs))
            v = self._eval(node.lhs)
            if node.lhs.ty.unsigned:
                v &= MASK
            return f32(float(v))
        if k in ("add", "sub", "mul", "div"):
            a, b = self.eval_float(node.lhs), self.eval_float(node.rhs)
            if k == "add":
                return f32(a + b)
            if k == "sub":
                return f32(a - b)
            if k == "mul":
                return f32(a * b)
            if b == 0:
                if a == 0 or a != a:
                    return float("nan")
                return float("inf") if (a > 0) == (str(b)[0] != "-") else float("-inf")
            return f32(a / b)
        if k == "neg":
            return -self.eval_float(node.lhs)
        if k == "cond":
            return self.eval_float(node.then) if self._truth(node.cond) \
                else self.eval_float(node.els)
        if not node.ty.is_float:
            return float(self._eval(node))
        raise error_at(node.tok, "expression is not a constant")

    def eval_address(self, node):
        """An address constant for a static initializer: (label or None, addend)."""
        k = node.kind
        if k == "var":
            if node.var.is_local:
                raise error_at(node.tok, "initializer element is not constant")
            if node.ty.kind in ("array", "func"):
                return node.var.asm_name, 0, node.var
            raise error_at(node.tok, "initializer element is not constant")
        if k == "addr":
            return self.eval_lvalue_address(node.lhs)
        if k == "cast":
            if node.lhs.ty.is_ptr_like or node.lhs.ty.is_func:
                return self.eval_address(node.lhs)
            if node.ty.kind == "ptr" or node.ty.is_integer:
                return None, self.eval(node.lhs), None
        if k in ("add", "sub"):
            base = self.eval_address(node.lhs)
            off = self.eval(node.rhs)
            return base[0], base[1] + (off if k == "add" else -off), base[2]
        if k == "comma" and node.rhs.kind == "var":     # file-scope compound literal
            return self.eval_address(node.rhs)
        if self.is_const_expr(node):
            return None, self.eval(node), None
        raise error_at(node.tok, "initializer element is not constant")

    def eval_lvalue_address(self, node):
        k = node.kind
        if k == "var":
            if node.var.is_local:
                raise error_at(node.tok, "initializer element is not constant")
            return node.var.asm_name, 0, node.var
        if k == "deref":
            return self.eval_address(node.lhs)
        if k == "member":
            base = self.eval_lvalue_address(node.lhs)
            return base[0], base[1] + node.member.offset, base[2]
        if k == "comma" and node.rhs.kind == "var":
            return self.eval_lvalue_address(node.rhs)
        raise error_at(node.tok, "initializer element is not constant")

    # ================================================================ initializers
    def new_initializer(self, ty, is_flexible):
        init = Initializer(ty)
        if ty.kind == "array":
            if is_flexible and ty.size < 0:
                init.is_flexible = True
                return init
            init.children = [self.new_initializer(ty.base, False)
                             for _ in range(max(ty.array_len, 0))]
            return init
        if ty.is_struct:
            init.children = []
            for i, m in enumerate(ty.members):
                flex = is_flexible and ty.is_flexible and i == len(ty.members) - 1
                child = self.new_initializer(m.ty, flex)
                init.children.append(child)
            return init
        return init

    def initializer(self, ty):
        init = self.new_initializer(ty, True)
        self.initializer2(init)
        if ty.is_struct and ty.is_flexible:
            # a flexible array member initialised with values: a new, longer type
            last = init.children[-1]
            if last.ty.array_len > 0:
                ty = T.copy_type(ty)
                ty.origin = None
                mems = list(ty.members)
                lm = mems[-1]
                mems[-1] = T.Member(lm.name, last.ty, lm.offset, lm.tok, lm.bit_width,
                                    lm.bit_offset, lm.index)
                ty.members = mems
                ty.size += last.ty.size
                init.ty = ty
        return init, init.ty

    def initializer2(self, init):
        ty = init.ty
        if ty.kind == "array" and self.tok.kind == "str" and self.is_char_array(ty):
            self.string_initializer(init)
            return
        if ty.kind == "array" and self.equal("{") and \
                self.peek().kind == "str" and self.is_char_array(ty) and \
                self.equal("}", self.peek(2)):
            self.next()
            self.string_initializer(init)
            self.expect("}")
            return
        if ty.kind == "array":
            if self.equal("{"):
                self.array_initializer1(init)
            else:
                self.array_initializer2(init, 0)
            return
        if ty.is_struct:
            if self.equal("{"):
                self.struct_initializer1(init)
                return
            # a struct value (e.g. from a function or another variable)
            saved = self.speculation()
            expr = self.assign()
            if expr.ty.is_struct:
                if not T.is_compatible(T.unqualified(expr.ty), T.unqualified(ty)):
                    raise error_at(expr.tok, "incompatible type in initializer")
                init.expr = expr
                return
            self.undo(saved)
            self.struct_initializer2(init, 0)
            return
        if self.equal("{"):
            # scalar in braces: { 3 }
            self.next()
            if self.equal("}"):
                raise self.error("empty scalar initializer")
            self.initializer2(init)
            self.consume(",")
            self.expect("}")
            return
        expr = self.assign()
        init.tok = expr.tok
        init.expr = self.assign_convert(expr, T.unqualified(ty), expr.tok, "initialization")

    @staticmethod
    def is_char_array(ty):
        return ty.kind == "array" and ty.base.kind in ("char", "int", "short", "long") \
            and ty.base.size == 1

    def string_initializer(self, init):
        t = self.next()
        codes = list(t.value) + [0]
        if init.is_flexible:
            ty = T.array_of(init.ty.base, len(codes))
            new = self.new_initializer(ty, False)
            init.ty = new.ty
            init.children = new.children
            init.is_flexible = False
        n = min(init.ty.array_len, len(codes))
        if len(codes) - 1 > init.ty.array_len:
            self.warn(t, "initializer-string for array is too long")
        for i in range(n):
            init.children[i].expr = self.new_num(wrap(codes[i], False), t, init.ty.base)

    def speculation(self):
        """What a look-ahead parse must put back: the position, and any
        strings, compound literals or names it created."""
        return (self.pos, len(self.globals), len(self.locals or []), self.counter)

    def undo(self, saved):
        pos, nglobals, nlocals, counter = saved
        self.pos = pos
        del self.globals[nglobals:]
        if self.locals is not None:
            del self.locals[nlocals:]
        self.counter = counter

    def count_array_init_elements(self, ty):
        """How many elements a braced initializer for an array of unknown size has."""
        saved = self.speculation()
        dummy = self.new_initializer(ty.base, True)
        i = max_ = 0
        first = True
        while not self.consume_end():
            if not first:
                self.expect(",")
            first = False
            if self.equal("["):
                self.next()
                i = self.const_expr()
                if self.consume("..."):
                    i = self.const_expr()
                self.expect("]")
                self.designation_rest(dummy)
            else:
                self.initializer2(dummy)
            i += 1
            max_ = max(max_, i)
        self.undo(saved)
        return max_

    def designation_rest(self, init):
        """After an array designator inside count_array_init_elements: skip the value."""
        if self.equal("[") or self.equal("."):
            # nested designators: parse into a throwaway
            while self.equal("[") or self.equal("."):
                if self.consume("."):
                    self.expect_ident()
                else:
                    self.next()
                    self.const_expr()
                    self.expect("]")
            self.consume("=")
            self.skip_init_value()
            return
        self.consume("=")
        self.skip_init_value()

    def skip_init_value(self):
        if self.equal("{"):
            depth = 0
            while True:
                t = self.next()
                if self.equal("{", t):
                    depth += 1
                elif self.equal("}", t):
                    depth -= 1
                    if depth == 0:
                        return
                elif t.kind == "eof":
                    raise self.error("unterminated initializer")
        self.assign()

    def consume_end(self):
        """'}' or ',}' at the end of a braced initializer."""
        if self.equal("}"):
            self.next()
            return True
        if self.equal(",") and self.equal("}", self.peek()):
            self.pos += 2
            return True
        return False

    def is_end(self):
        return self.equal("}") or (self.equal(",") and self.equal("}", self.peek()))

    def array_initializer1(self, init):
        open_tok = self.expect("{")
        if init.is_flexible:
            n = self.count_array_init_elements(init.ty)
            new = self.new_initializer(T.array_of(init.ty.base, n), False)
            init.ty, init.children, init.is_flexible = new.ty, new.children, False
        first = True
        i = 0
        while not self.consume_end():
            if not first:
                self.expect(",")
            first = False
            if self.equal("["):
                lo, hi = self.array_designator(init.ty)
                for j in range(lo, hi + 1):
                    self.designation(init.children[j], keep_pos=j != hi)
                i = hi + 1
                continue
            if i < len(init.children):
                self.initializer2(init.children[i])
            else:
                self.warn(self.tok, "excess elements in array initializer")
                self.skip_init_value()
            i += 1

    def array_initializer2(self, init, i):
        """Elements without their own braces (they continue the outer list)."""
        if init.is_flexible:
            n = self.count_array_init_elements(init.ty)
            new = self.new_initializer(T.array_of(init.ty.base, n), False)
            init.ty, init.children, init.is_flexible = new.ty, new.children, False
        while i < len(init.children) and not self.is_end():
            start = self.pos
            if i > 0:
                self.expect(",")
            if self.equal("[") or self.equal("."):
                self.pos = start
                return
            self.initializer2(init.children[i])
            i += 1

    def array_designator(self, ty):
        t = self.expect("[")
        lo = self.const_expr()
        hi = lo
        if self.consume("..."):
            hi = self.const_expr()
        self.expect("]")
        if lo < 0 or hi >= ty.array_len or hi < lo:
            raise error_at(t, "array index in initializer exceeds array bounds")
        return lo, hi

    def designation(self, init, keep_pos=False):
        """designation = ("[" const-expr "]" | "." ident)* "="? initializer"""
        start = self.pos
        if self.equal("["):
            if init.ty.kind != "array":
                raise self.error("array index in a non-array initializer")
            lo, hi = self.array_designator(init.ty)
            for j in range(lo, hi + 1):
                self.designation(init.children[j], keep_pos=j != hi)
            if keep_pos:
                self.pos = start
            return
        if self.equal(".") and init.ty.is_struct:
            self.next()
            name = self.expect_ident()
            path = self.find_member(init.ty, name.text)
            if path is None:
                raise error_at(name, f"'{T.type_name(init.ty)}' has no member named "
                               f"'{name.text}'")
            child = init
            for m in path:
                if child.ty.kind == "union":
                    child.mem = m
                    child = child.children[m.index]
                else:
                    child = child.children[m.index]
            self.designation(child)
            if keep_pos:
                self.pos = start
            return
        if self.equal("."):
            raise self.error("field name not in a struct or union initializer")
        self.consume("=")
        self.initializer2(init)
        if keep_pos:
            self.pos = start

    def struct_initializer1(self, init):
        self.expect("{")
        ty = init.ty
        if ty.kind == "union":
            self.union_initializer(init)
            return
        i = 0
        first = True
        while not self.consume_end():
            if not first:
                self.expect(",")
            first = False
            if self.equal("."):
                name_tok = self.peek()
                path = self.find_member(ty, name_tok.text) if name_tok.kind == "ident" else None
                self.designation(init)
                if path is not None:
                    i = path[0].index + 1
                continue
            if self.equal("["):
                raise self.error("array index in a struct initializer")
            if i < len(init.children):
                self.initializer2(init.children[i])
            else:
                self.warn(self.tok, "excess elements in struct initializer")
                self.skip_init_value()
            i += 1

    def struct_initializer2(self, init, i):
        first = True
        while i < len(init.children) and not self.is_end():
            start = self.pos
            if not first:
                self.expect(",")
            first = False
            if self.equal("[") or self.equal("."):
                self.pos = start
                return
            self.initializer2(init.children[i])
            i += 1

    def union_initializer(self, init):
        """'{' already read."""
        ty = init.ty
        if self.equal("."):
            self.designation(init)
            self.consume(",")
            self.expect("}")
            return
        init.mem = ty.members[0]
        if self.equal("}"):
            self.next()
            return
        self.initializer2(init.children[0])
        self.consume(",")
        self.expect("}")

    # ---------------------------------------------------------------- local initializers
    def lvar_initializer(self, var, t):
        init, ty = self.initializer(var.ty)
        var.ty = ty
        zero = Node("memzero", t, var=var)
        zero.ty = T.void_type()
        if var.ty.is_scalar and init.expr is not None:
            # a plain scalar: just the assignment
            node = self.var_node(var, t)
            assign = Node("assign", t, lhs=node, rhs=init.expr)
            assign.ty = T.unqualified(var.ty)
            assign.is_init = True
            return assign
        rhs = self.create_lvar_init(init, var.ty, self.var_node(var, t), t)
        node = Node("comma", t, lhs=zero, rhs=rhs)
        node.ty = T.void_type()
        return node

    def create_lvar_init(self, init, ty, target, t):
        """Assignments that store the initializer into target (a node)."""
        if ty.kind == "array":
            node = self.null_expr(t)
            for i, child in enumerate(init.children):
                idx = self.new_num(i, t)
                elem = Node("deref", t, lhs=self.ptr_plus(target, i, ty, t))
                elem.ty = ty.base
                node = self.comma(node, self.create_lvar_init(child, ty.base, elem, t), t)
            return node
        if ty.is_struct and init.expr is None:
            node = self.null_expr(t)
            if ty.kind == "union":
                if init.mem is None:
                    return node
                m = init.mem
                child = init.children[m.index]
                ref = Node("member", t, lhs=target, member=m)
                ref.ty = m.ty
                return self.create_lvar_init(child, m.ty, ref, t)
            for m, child in zip(ty.members, init.children):
                ref = Node("member", t, lhs=target, member=m)
                ref.ty = m.ty
                node = self.comma(node, self.create_lvar_init(child, m.ty, ref, t), t)
            return node
        if init.expr is None:
            return self.null_expr(t)
        node = Node("assign", t, lhs=target, rhs=init.expr)
        node.ty = T.unqualified(ty)
        node.is_init = True
        return node

    def ptr_plus(self, target, i, ty, t):
        """Address of element i of the array 'target'."""
        base = Node("addr", t, lhs=target)
        base.ty = T.pointer_to(ty.base)
        self.mark_addr_taken_for_init(target)
        if i == 0:
            return base
        node = Node("add", t, lhs=base, rhs=self.new_num(i * ty.base.size, t))
        node.ty = base.ty
        return node

    def mark_addr_taken_for_init(self, node):
        """Arrays and structs live in memory anyway; nothing to mark."""
        return

    def null_expr(self, t):
        node = Node("block_expr", t)
        node.ty = T.void_type()
        return node

    def comma(self, a, b, t):
        if a.kind == "block_expr":
            return b
        if b.kind == "block_expr":
            return a
        node = Node("comma", t, lhs=a, rhs=b)
        node.ty = T.void_type()
        return node

    # ---------------------------------------------------------------- global initializers
    def gvar_initializer(self, var):
        init, ty = self.initializer(var.ty)
        var.ty = ty
        words = [0] * ty.size
        self.write_gvar_data(init, ty, words, 0, 0)
        var.init_data = words

    def write_gvar_data(self, init, ty, words, offset, bit=None):
        if ty.kind == "array":
            for i, child in enumerate(init.children or []):
                self.write_gvar_data(child, ty.base, words, offset + i * ty.base.size)
            return
        if ty.is_struct and init.expr is None:
            if ty.kind == "union":
                if init.mem is not None:
                    m = init.mem
                    self.write_member(init.children[m.index], m, words, offset)
                return
            for m, child in zip(ty.members, init.children):
                self.write_member(child, m, words, offset)
            return
        if init.expr is None:
            return
        if ty.is_struct:
            raise error_at(init.expr.tok, "initializer element is not constant")
        words[offset] = self.static_value(init.expr, ty)

    def write_member(self, child, m, words, offset):
        if m.is_bitfield:
            if child.expr is None:
                return
            v = self.static_value(child.expr, m.ty)
            if isinstance(v, tuple):
                raise error_at(child.expr.tok, "initializer element is not constant")
            mask = (1 << m.bit_width) - 1 if m.bit_width < 32 else MASK
            cur = words[offset + m.offset]
            if isinstance(cur, tuple):
                cur = 0
            cur = (cur & ~(mask << m.bit_offset)) | ((v & mask) << m.bit_offset)
            words[offset + m.offset] = cur & MASK
            return
        self.write_gvar_data(child, m.ty, words, offset + m.offset)

    def static_value(self, expr, ty):
        """One word of static data: an int (bits) or (label, addend)."""
        if ty.is_float:
            if not self.is_const_expr(expr):
                raise error_at(expr.tok, "initializer element is not constant")
            return struct.unpack("<I", struct.pack("<f", self.eval_float(expr)))[0]
        if ty.is_integer and self.is_const_expr(expr):
            return self.eval(expr) & MASK
        label, addend, var = self.eval_address(expr)
        if label is None:
            return addend & MASK
        if var is not None and var.is_function:
            var.is_referenced = True
        if var is not None:
            var.addr_used = True
        return (label, addend)


def parse(tokens, warn=None):
    return Parser(tokens, warn).program()
