"""Code generator: the typed syntax tree -> assembly for the logic-gate CPU.

The output is ordinary assembly for compiler/src/asm, one .asm per C file.

Machine model
    R0        the ALU result register (every ALU op writes it)
    R1-R12    expression temporaries
    R13       scratch for frame indexes and addresses
    R14, R15  used by the CALL/RET/RESTORE pseudo-instructions and by the
              runtime helpers; never live across a statement

Calling convention (the one stdlib.asm uses, so C and assembly mix freely)
    The caller pushes the arguments first to last, then CALL f, N pops them
    after the return. The result comes back in R0. Every register may be
    changed by a call; live temporaries are kept with SAVE/RESTORE.
    Inside the callee, with N argument words, word i is at EBP-(N+1)+i.
    A struct argument is pushed word by word; a struct result is written
    through a hidden pointer passed as the first argument.
    Variadic calls push the variadic arguments first, then the fixed ones,
    then the number of variadic words V: the fixed parameters keep fixed
    places (EBP-(F+2)+i for F fixed words) and va_start finds the rest.

Locals live in the stack frame above EBP (EBP+1, EBP+2, ...) and are read
and written with STK GET/SET. A function that takes the address of a local
computes FP = 0x10000 + EBP once (stack slot i is RAM word 0x10000 + i).
"""

import os
import struct

import peephole
import regalloc
import typesys as T
from cerror import CError, error_at
from cparser import MASK, wrap
from nodes import Node, Obj

TEMPS = list(range(1, 13))
SCRATCH = 13
MIN_TEMPS = 5           # registers kept for expressions; the rest can hold variables
INT_MIN = -(1 << 31)
UINT_MAX = MASK
PUSH_LIMIT = 15         # frames up to this size are reserved with STK PUSHes


def float_bits(value):
    try:
        return struct.unpack("<I", struct.pack("<f", value))[0]
    except OverflowError:
        return 0x7F800000 if value > 0 else 0xFF800000


def signed(v):
    v &= MASK
    return v - (1 << 32) if v & 0x80000000 else v


class Val:
    """Where an expression's value is.

    imm   a constant: .imm is an int (32-bit pattern) or a str (label expr)
    reg   in temporary register .reg (owned: free it when done)
    vreg  in register .reg that belongs to a variable (read it, don't change it)
    r0    in R0 (move it out before anything else uses the ALU)
    addr  an aggregate (array/struct/function): .addr is its Addr
    void  no value
    """
    __slots__ = ("kind", "reg", "imm", "addr", "flt")

    def __init__(self, kind, reg=None, imm=None, addr=None, flt=False):
        self.kind = kind
        self.reg = reg
        self.imm = imm
        self.addr = addr
        self.flt = flt          # imm holds float bits: written as a float literal

    def __repr__(self):
        return f"Val({self.kind}, reg={self.reg}, imm={self.imm})"


class Addr:
    """Where an lvalue is, without computing a full address.

    frame   stack slot EBP + off (+ register .reg if set): STK GET/SET
    abs     memory address label + off (+ register .reg if set)
    var     a variable that lives in register .var_reg
    """
    __slots__ = ("kind", "reg", "off", "label", "var_reg", "owned")

    def __init__(self, kind, reg=None, off=0, label=None, var_reg=None, owned=True):
        self.kind = kind
        self.reg = reg
        self.off = off
        self.label = label
        self.var_reg = var_reg
        self.owned = owned      # False: .reg is a variable's register (read only)

    def plus(self, n):
        if self.kind == "var":
            raise CError("internal error: offset from a register variable")
        return Addr(self.kind, self.reg, self.off + n, self.label, owned=self.owned)

    def sym(self):
        """The constant part as assembly text."""
        if self.label is None:
            return str(signed(self.off))
        if self.off == 0:
            return self.label
        if self.off > 0:
            return f"{self.label} + {self.off}"
        return f"{self.label} - {-self.off}"

    def __repr__(self):
        return f"Addr({self.kind}, reg={self.reg}, off={self.off}, label={self.label})"


def has_call(node):
    """Does evaluating this expression call a function?"""
    cached = getattr(node, "_has_call", None)
    if cached is not None:
        return cached
    result = False
    if node.kind == "funcall":
        result = True
    else:
        for child in _children(node):
            if has_call(child):
                result = True
                break
    node._has_call = result
    return result


def depth(node):
    """Roughly how many registers evaluating node needs (casts between
    integer and pointer types cost nothing)."""
    cached = getattr(node, "_depth", None)
    if cached is not None:
        return cached
    if node.kind == "cast" and _free_cast(node):
        d = depth(node.lhs)
    else:
        kids = list(_children(node))
        d = 1 + max((depth(k) for k in kids), default=0)
    node._depth = d
    return d


def _free_cast(node):
    a, b = node.lhs.ty, node.ty
    return (a.is_integer or a.kind == "ptr") and (b.is_integer or b.kind == "ptr") \
        and b.kind != "bool"


def _children(node):
    for name in ("lhs", "rhs", "cond", "then", "els", "func"):
        child = getattr(node, name, None)
        if isinstance(child, Node):
            yield child
    for a in getattr(node, "args", None) or ():
        if isinstance(a, Node):
            yield a


class OutOfRegisters(Exception):
    """An expression needed more temporaries than there were; the function
    is generated again with fewer register variables."""

    def __init__(self, error):
        super().__init__(str(error))
        self.error = error


class CodeGen:
    def __init__(self, program, unit, source=None):
        self.program = program
        self.unit = unit                # a name for this file's init routine
        self.lines = []                 # the finished output
        self.code = None                # the current function body: list of tuples
        self.temps = list(TEMPS)        # registers for expression temporaries
        self.var_regs = {}              # variable -> the register it lives in
        self.free = []
        self.used_labels = set()        # labels this file refers to
        self.defined = set()            # labels this file defines
        self.counter = 0
        self.source = source or {}      # file name -> list of source lines
        self.last_line = None

    # ================================================================ output
    def ins(self, op, *args):
        self.code.append(("ins", op, args))

    def label(self, name):
        self.code.append(("label", name))

    def comment(self, text):
        self.code.append(("comment", text))

    def raw(self, text):
        self.code.append(("raw", text))

    def new_label(self):
        self.counter += 1
        return f"_K{self.counter}"

    def use(self, label):
        """Note a reference to a label (for .extern)."""
        if label is not None:
            base = label.split()[0]
            self.used_labels.add(base)

    def error(self, node, message):
        return error_at(node.tok if node is not None else None, message)

    # ================================================================ registers
    def alloc(self, node=None):
        if not self.free:
            raise OutOfRegisters(self.error(node, "expression too complex: out of registers"))
        return self.free.pop(0)

    def release(self, reg):
        if reg is not None and reg not in self.free and reg in self.temps:
            self.free.append(reg)
            self.free.sort()

    def live(self):
        return [r for r in self.temps if r not in self.free]

    def free_val(self, v):
        if v is None:
            return
        if v.kind == "reg":
            self.release(v.reg)
        elif v.kind == "addr":
            self.free_addr(v.addr)

    def free_addr(self, a):
        if a is not None and a.reg is not None and a.owned:
            self.release(a.reg)

    def imm_text(self, imm, flt=False):
        if isinstance(imm, str):
            return imm
        if flt:
            value = struct.unpack("<f", struct.pack("<I", imm & MASK))[0]
            if value == value and value not in (float("inf"), float("-inf")):
                text = repr(value)
                if "e" not in text and "." not in text:
                    text += ".0"
                return text
        return str(signed(imm))

    def operand(self, v):
        """An ALU right operand: Rn or #value."""
        if v.kind == "imm":
            return "#" + self.imm_text(v.imm, v.flt)
        if v.kind in ("reg", "vreg"):
            return f"R{v.reg}"
        if v.kind == "r0":
            return "R0"
        raise CError(f"internal error: bad operand {v}")

    def hold(self, v, node=None):
        """Make sure v does not sit in R0 (before the ALU is used again)."""
        if v.kind == "r0":
            self.to_reg(v, node)
        return v

    def to_reg(self, v, node=None):
        """Move v into a temporary register and return its number. v itself
        is updated to say so: free it with free_val(v) or release(reg), once.
        (A variable's register is copied: the caller may change the copy.)"""
        if v.kind == "reg":
            return v.reg
        if v.kind == "vreg":
            r = self.alloc(node)
            self.ins("CPY", f"R{v.reg}", f"R{r}")
            v.kind, v.reg = "reg", r
            return r
        if v.kind == "addr":
            m = self.materialize(v.addr, node)
            v.kind, v.reg, v.imm, v.addr = m.kind, m.reg, m.imm, None
            return self.to_reg(v, node)
        r = self.alloc(node)
        if v.kind == "r0":
            self.ins("CPY", "R0", f"R{r}")
        elif v.kind == "imm":
            self.ins("DATA", f"R{r}", self.imm_text(v.imm, v.flt))
        else:
            raise CError(f"internal error: no value to put in a register ({v})")
        v.kind, v.reg, v.imm = "reg", r, None
        return r

    def to_r0(self, v):
        """Move v into R0 (v is updated; a register it held is freed)."""
        if v.kind == "r0":
            return
        if v.kind == "imm":
            self.ins("DATA", "R0", self.imm_text(v.imm, v.flt))
        elif v.kind in ("reg", "vreg"):
            self.ins("CPY", f"R{v.reg}", "R0")
            self.release(v.reg)
        elif v.kind == "addr":
            m = self.materialize(v.addr)
            self.to_r0(m)
        else:
            raise CError(f"internal error: no value to put in R0 ({v})")
        v.kind, v.reg, v.imm, v.addr = "r0", None, None, None

    def reg_name(self, v):
        """The name of a register holding v, for reading (R0 allowed; a
        variable's own register; constants get a temporary, recorded in v)."""
        if v.kind == "r0":
            return "R0"
        if v.kind == "vreg":
            return f"R{v.reg}"
        return f"R{self.to_reg(v)}"

    # ================================================================ program
    def run(self):
        prog = self.program
        out = self.lines
        out.append(f"; generated by the tiny C compiler from {self.unit_source()}")
        funcs = [g for g in prog.globals if g.is_function and g.is_definition]
        data = [g for g in prog.globals if not g.is_function and g.asm_text is None
                and (g.is_definition or g.init_data is not None)]
        for g in funcs + data:
            self.defined.add(g.asm_name)
        exported = [g.asm_name for g in funcs + data if not g.is_static]

        body = []
        for fn in funcs:
            body.extend(self.gen_function(fn))
        rom_data, ram_init, ram_zero, templates = self.layout_data(data)
        init_lines = self.gen_init(ram_init, ram_zero)
        for g in prog.globals:
            if g.asm_text is not None:
                body.extend(["; asm block", *g.asm_text.splitlines()])

        if init_lines:
            exported.append(self.init_label())
            self.defined.add(self.init_label())
        if exported:
            out.append("        .global " + ", ".join(exported))
        externs = sorted(l for l in self.used_labels if l not in self.defined)
        if externs:
            out.append("        .extern " + ", ".join(externs))
        out.append("")
        out.append("        .rom")
        out.extend(body)
        out.extend(init_lines)
        out.extend(rom_data)
        out.extend(templates)
        if ram_init or ram_zero:
            out.append("")
            out.append("        .ram")
            for g in ram_init + ram_zero:
                out.append(f"{g.asm_name}:  .space {max(g.ty.size, 0)}")
            out.append("        .rom")
        return "\n".join(out) + "\n"

    def unit_source(self):
        return self.unit_file if hasattr(self, "unit_file") else self.unit

    def init_label(self):
        return f"_init_{self.unit}"

    # ================================================================ data
    def layout_data(self, data):
        rom, ram_init, ram_zero, templates = [], [], [], []
        for g in data:
            if g.ty.size < 0:
                if g.ty.kind == "array" and g.is_tentative:
                    g.ty = T.array_of(g.ty.base, 1)     # int x[]; at file scope: one element
                else:
                    raise error_at(g.tok, f"storage size of '{g.name}' isn't known")
            const = self.is_const_object(g.ty)
            if g.in_rom or (const and g.init_data is not None) or (const and g.is_tentative):
                rom.append("")
                rom.append("        .part")              # the linker may leave it out
                rom.extend(self.data_words(g.asm_name, g.init_data or [0] * g.ty.size,
                                           g.is_string))
            elif g.init_data is not None and any(w != 0 for w in g.init_data):
                ram_init.append(g)
            else:
                ram_zero.append(g)
        if ram_init:
            templates.append("")
            templates.append("        .part")
            templates.append(f"; starting values of {self.unit}'s initialised variables")
            templates.append(f"{self.template_label()}:")
            for g in ram_init:
                templates.extend(self.data_words(None, g.init_data, False, comment=g.name))
        return rom, ram_init, ram_zero, templates

    def template_label(self):
        return f"_T_{self.unit}"

    def is_const_object(self, ty):
        if ty.is_const:
            return True
        if ty.kind == "array":
            return self.is_const_object(ty.base)
        return False

    def data_words(self, label, words, is_string, comment=None):
        out = []
        if is_string and words and words[-1] == 0 and all(
                0 < w < 127 and (32 <= w or w in (9, 10, 13)) for w in words[:-1]):
            esc = "".join({9: "\\t", 10: "\\n", 13: "\\r", 34: '\\"', 92: "\\\\",
                           39: "\\'"}.get(w, chr(w)) for w in words[:-1])
            out.append(f"{label}:  .string \"{esc}\"" if label else f"        .string \"{esc}\"")
            return out
        items = []
        for w in words:
            if isinstance(w, tuple):
                lab, add = w
                self.use(lab)
                items.append(lab if add == 0 else
                             f"{lab} + {add}" if add > 0 else f"{lab} - {-add}")
            else:
                items.append(str(signed(w)))
        first = True
        for i in range(0, max(len(items), 1), 8):
            chunk = ", ".join(items[i:i + 8]) if items else "0"
            prefix = f"{label}:" if label and first else ""
            note = f"      ; {comment}" if comment and first else ""
            out.append(f"{prefix:<8}.word {chunk}{note}")
            first = False
        return out

    def gen_init(self, ram_init, ram_zero):
        """The routine crt0 calls before main: copy starting values into RAM
        and clear the rest (RAM is not cleared by a reset)."""
        if not ram_init and not ram_zero:
            return []
        lines = ["", "        .part", f"; puts {self.unit}'s global variables in their starting state",
                 f"{self.init_label()}:"]
        n = 0
        if ram_init:
            first = ram_init[0].asm_name
            n = sum(g.ty.size for g in ram_init)
            lines += [
                f"        DATA R1, {self.template_label()}",
                f"        DATA R2, {first}",
                f"        DATA R3, {n - 1}",
                f"_I_{self.unit}_copy:",
                "        ALD R1, R3",
                "        AST R2, R3",
                "        -- R3",
                "        CPY R0, R3",
                f"        RJNF N, _I_{self.unit}_copy",
            ]
        if ram_zero:
            first = ram_zero[0].asm_name
            m = sum(g.ty.size for g in ram_zero)
            lines += [
                f"        DATA R2, {first}",
                f"        DATA R3, {m - 1}",
                f"_I_{self.unit}_zero:",
                "        DATA R0, 0",
                "        AST R2, R3",
                "        -- R3",
                "        CPY R0, R3",
                f"        RJNF N, _I_{self.unit}_zero",
            ]
        lines.append("        RET")
        return lines

    # ================================================================ functions
    def gen_function(self, fn):
        analysis = regalloc.Analysis(fn)
        wanted = regalloc.candidates(fn, analysis)
        n = min(len(wanted), len(TEMPS) - MIN_TEMPS)
        while True:
            try:
                return self.gen_function_with(fn, analysis, wanted[:n])
            except OutOfRegisters as e:
                if n == 0:
                    raise e.error from None
                n = max(0, n - 2)

    def gen_function_with(self, fn, analysis, regvars):
        self.fn = fn
        self.analysis = analysis
        self.call_pos = {id(node): pos for node, pos in analysis.calls}
        self.var_regs = {v: 12 - i for i, v in enumerate(regvars)}
        self.temps = list(range(1, 13 - len(regvars)))
        self.code = []
        self.free = list(self.temps)
        self.frame = 0                  # words of frame used above EBP
        self.fp_slot = None
        self.va_count = None
        self.ret_label = self.new_label()
        self.last_line = None
        fty = fn.ty

        # parameters: word offsets relative to EBP
        params = ([fn.ret_ptr] if fn.ret_ptr is not None else []) + list(fn.params)
        total = sum(p.ty.size for p in params)
        start = -(total + 2) if fty.variadic else -(total + 1)
        b = start
        for p in params:
            p.offset = b
            b += p.ty.size
        self.fixed_words = total
        for var in fn.locals:
            if var.is_param or var in params:
                continue
            if var in self.var_regs:
                var.offset = None        # a stack slot only if a call needs one
                continue
            var.offset = self.frame + 1
            self.frame += max(var.ty.size, 0)

        self.gen_stmt(fn.body)
        if fn.name == "main" and self.falls_through():
            self.ins("DATA", "R0", "0")          # reaching the end of main returns 0
        if self.live():
            raise CError(f"internal error: registers {self.live()} still live at the "
                         f"end of {fn.name}")

        body = self.code
        self.code = []
        self.comment_header(fn)
        self.label(fn.asm_name)
        self.prologue()
        for var, r in sorted(self.var_regs.items(), key=lambda item: -item[1]):
            if var.is_param:
                self.ins("DATA", f"R{SCRATCH}", str(var.offset))
                self.ins("STK", "GET", f"R{SCRATCH}")
                self.ins("CPY", "R0", f"R{r}")
        if self.var_regs:
            self.comment("in registers: " + ", ".join(
                f"{v.name or 'param'}=R{r}" for v, r in sorted(self.var_regs.items(),
                                                              key=lambda item: -item[1])))
        prologue = self.code
        self.code = []
        self.label(self.ret_label)
        if fn.ty.return_ty.is_void:
            # no result to keep: drop the frame, pop the return address, jump
            self.ins("STK", "RET")
            self.ins("STK", "POP")
            self.ins("JMRB", "R0")
        else:
            self.ins("RET")
        epilogue = self.code
        return self.format(peephole.optimize(prologue + body + epilogue))

    def comment_header(self, fn):
        self.raw("")
        self.raw("        .part")                # each function: a part the linker may drop
        self.raw(f"; {T.type_name(fn.ty, fn.name)}")

    def falls_through(self):
        for item in reversed(self.code):
            if item[0] in ("comment", "loc"):
                continue
            if item[0] == "ins" and item[1] in ("RJMP", "RET", "JMRB", "HALT"):
                return False
            return True
        return True

    def prologue(self):
        size = self.frame
        if size <= PUSH_LIMIT:
            for _ in range(size):
                self.ins("STK", "PUSH")
            if self.fp_slot is not None:
                self.read_ebp()
                self.ins("ADD", "R0", "#0x10000")
                self.ins("DATA", f"R{SCRATCH}", str(self.fp_slot))
                self.ins("STK", "SET", f"R{SCRATCH}")
            return
        # A big frame: set ESP directly. With EBP = E and stack[E] = old EBP:
        #   stack[E] = Y; STK RET -> ESP = E, EBP = Y
        #   stack[Y] = E; STK RET -> ESP = Y, EBP = E
        # then put the old EBP back in stack[E].
        self.comment(f"reserve {size} words of frame")
        self.read_ebp()                          # R0 = E
        self.ins("CPY", "R0", "R1")
        self.ins("DATA", f"R{SCRATCH}", "0")
        self.ins("STK", "GET", f"R{SCRATCH}")
        self.ins("CPY", "R0", "R2")              # R2 = old EBP
        self.ins("ADD", "R1", f"#{size + 1}")    # R0 = Y = E + size + 1
        self.ins("STK", "SET", f"R{SCRATCH}")
        self.ins("STK", "RET")
        self.ins("CPY", "R1", "R0")
        self.ins("STK", "SET", f"R{SCRATCH}")
        self.ins("STK", "RET")
        self.ins("CPY", "R2", "R0")
        self.ins("STK", "SET", f"R{SCRATCH}")
        if self.fp_slot is not None:
            self.ins("ADD", "R1", "#0x10000")
            self.ins("DATA", f"R{SCRATCH}", str(self.fp_slot))
            self.ins("STK", "SET", f"R{SCRATCH}")

    def read_ebp(self):
        """R0 = EBP. STK CALL saves EBP in the next free slot and makes it the
        frame; GET 0 reads it back; STK RET undoes the frame."""
        self.ins("STK", "CALL")
        self.ins("DATA", f"R{SCRATCH}", "0")
        self.ins("STK", "GET", f"R{SCRATCH}")
        self.ins("STK", "RET")

    def alloc_slot(self, size=1):
        slot = self.frame + 1
        self.frame += size
        return slot

    def load_fp(self):
        """R0 = the frame's RAM address (0x10000 + EBP)."""
        if self.fp_slot is None:
            self.fp_slot = self.alloc_slot()
        self.ins("DATA", f"R{SCRATCH}", str(self.fp_slot))
        self.ins("STK", "GET", f"R{SCRATCH}")

    def format(self, items):
        out = []
        for item in items:
            kind = item[0]
            if kind == "ins":
                op, args = item[1], item[2]
                text = f"        {op}"
                if args:
                    if op in ("STK", "COMM") and len(args) == 2:
                        text += f" {args[0]}, {args[1]}"
                    else:
                        text += " " + ", ".join(args)
                out.append(text)
            elif kind == "label":
                out.append(f"{item[1]}:")
            elif kind == "comment":
                out.append(f"        ; {item[1]}")
            elif kind == "loc":
                path = item[1].replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'        .loc "{path}", {item[2]}')
            else:
                out.append(item[1])
        return out

    # ================================================================ statements
    def note_line(self, node):
        tok = node.tok
        if tok is None:
            return
        src = getattr(tok, "origin", None) or tok
        key = (src.file, src.line)
        if key == self.last_line:
            return
        self.last_line = key
        if src.file and not src.file.startswith("<"):
            self.code.append(("loc", os.path.abspath(src.file), src.line))
        lines = self.source.get(src.file)
        if lines and 0 < src.line <= len(lines):
            text = lines[src.line - 1].strip()
            if text:
                self.comment(f"{src.line}: {text}")

    def gen_stmt(self, node):
        k = node.kind
        if k not in ("block",):
            self.note_line(node)
        if k == "block":
            for s in node.body:
                self.gen_stmt(s)
        elif k == "expr_stmt":
            self.discard(node.lhs)
        elif k == "return":
            self.gen_return(node)
        elif k == "if":
            else_label = self.new_label()
            self.branch(node.cond, else_label, False)
            self.gen_stmt(node.then)
            if node.els is not None:
                end = self.new_label()
                if self.reachable():
                    self.ins("RJMP", end)
                self.label(else_label)
                self.gen_stmt(node.els)
                self.label(end)
            else:
                self.label(else_label)
        elif k == "for":
            if node.init is not None:
                self.gen_stmt(node.init)
            body = self.new_label()
            test = self.new_label()
            if node.cond is not None and not self.always_true(node.cond):
                self.ins("RJMP", test)
            self.label(body)
            self.gen_stmt(node.then)
            self.label(node.cont)
            if node.inc is not None:
                self.note_line(node.inc)
                self.discard(node.inc)
            self.label(test)
            if node.cond is None or self.always_true(node.cond):
                self.ins("RJMP", body)
            else:
                self.branch(node.cond, body, True)
            self.label(node.brk)
        elif k == "do":
            body = self.new_label()
            self.label(body)
            self.gen_stmt(node.then)
            self.label(node.cont)
            self.branch(node.cond, body, True)
            self.label(node.brk)
        elif k == "switch":
            self.gen_switch(node)
        elif k == "case":
            self.label(node.label)
            self.gen_stmt(node.lhs)
        elif k == "goto":
            self.ins("RJMP", node.label)
        elif k == "label":
            self.label(node.label)
            self.gen_stmt(node.lhs)
        elif k == "asm":
            keep, _ = self.vars_across(node)
            saved = self.save_live([self.var_regs[v] for v in keep])
            for line in node.text.splitlines():
                self.raw(line if line.startswith((" ", "\t")) or line.endswith(":")
                         else "        " + line.strip())
            self.restore_live(saved)
        else:
            raise self.error(node, f"internal error: unknown statement '{k}'")

    def reachable(self):
        for item in reversed(self.code):
            if item[0] in ("comment", "loc"):
                continue
            return not (item[0] == "ins" and item[1] in ("RJMP", "JMRB", "RET"))
        return True

    def always_true(self, node):
        return node.kind == "num" and (node.val != 0)

    def discard(self, node):
        """Evaluate an expression for its effects only."""
        k = node.kind
        if k in ("preinc", "predec", "postinc", "postdec"):
            v = self.gen_incdec(node, want=False)
        elif k == "assign":
            v = self.gen_assign(node, want=False)
        elif k == "assign_op":
            v = self.gen_assign_op(node, want=False)
        elif k == "comma":
            self.discard(node.lhs)
            self.discard(node.rhs)
            return
        elif k == "cast" and node.ty.is_void:
            self.discard(node.lhs)
            return
        elif k == "funcall":
            v = self.gen_call(node, want=False)
        else:
            v = self.gen(node)
        self.free_val(v)

    def gen_return(self, node):
        e = node.lhs
        if e is not None:
            rty = self.fn.ty.return_ty
            if rty.is_struct:
                src = self.gen(e)
                dst = self.load(Addr("frame", off=self.fn.ret_ptr.offset), T.pointer_to(rty))
                dst = self.hold(dst)
                daddr = Addr("abs", reg=self.to_reg(dst))
                self.copy_words(daddr, src.addr, rty.size)
                self.free_addr(src.addr)
                self.ins("CPY", f"R{daddr.reg}", "R0")
                self.release(daddr.reg)
            elif rty.is_void:
                self.discard(e)
            else:
                v = self.gen(e)
                self.to_r0(v)
        if self.live():
            raise CError(f"internal error: registers live at return: {self.live()}")
        self.ins("RJMP", self.ret_label)

    def gen_switch(self, node):
        v = self.gen(node.cond)
        if v.kind == "imm":
            r = self.to_reg(v)
        else:
            r = self.to_reg(self.hold(v))
        cases = node.cases
        values = [c for c in cases if c.lo == c.hi]
        if self.use_table(cases):
            self.jump_table(node, r)
        else:
            for c in cases:
                if c.lo == c.hi:
                    self.ins("CMP", f"R{r}", f"#{signed(c.lo)}")
                    self.ins("RJF", "Z", c.label)
                else:
                    self.ins("SUB", f"R{r}", f"#{signed(c.lo)}")
                    span = (c.hi - c.lo) & MASK
                    if span == UINT_MAX:
                        self.ins("RJMP", c.label)
                    else:
                        self.ins("SUB", "R0", f"#{signed(span + 1)}")
                        self.ins("RJF", "C", c.label)       # (v - lo) < span + 1, unsigned
            self.release(r)
            self.ins("RJMP", node.default.label if node.default else node.brk)
        self.gen_stmt(node.then)
        self.label(node.brk)

    def use_table(self, cases):
        singles = [c for c in cases if c.lo == c.hi]
        if len(cases) < 5 or len(singles) != len(cases):
            return False
        lo = min(c.lo for c in cases)
        hi = max(c.hi for c in cases)
        span = hi - lo + 1
        return span <= 3 * len(cases) and span <= 1024

    def jump_table(self, node, r):
        cases = node.cases
        lo = min(c.lo for c in cases)
        hi = max(c.hi for c in cases)
        default = node.default.label if node.default else node.brk
        table = self.new_label()
        self.comment(f"switch: jump table for {signed(lo)}..{signed(hi)}")
        self.ins("SUB", f"R{r}", f"#{signed(lo)}")             # R0 = v - lo
        self.ins("CPY", "R0", f"R{r}")
        self.ins("SUB", f"R{r}", f"#{signed(hi - lo + 1)}")
        self.ins("RJNF", "C", default)                      # v - lo >= count (unsigned)
        self.ins("DATA", f"R{SCRATCH}", table)
        self.ins("ALD", f"R{SCRATCH}", f"R{r}")
        self.release(r)
        self.ins("JMRB", "R0")
        targets = {}
        for c in cases:
            targets[c.lo - lo] = c.label
        words = [targets.get(i, default) for i in range(hi - lo + 1)]
        self.label(table)
        for i in range(0, len(words), 8):
            self.raw("        .word " + ", ".join(words[i:i + 8]))

    # ================================================================ conditions
    def branch(self, node, label, when):
        """Jump to label when the truth of node equals 'when'."""
        k = node.kind
        if k == "num":
            truth = node.val != 0
            if truth == when:
                self.ins("RJMP", label)
            return
        if k == "not":
            self.branch(node.lhs, label, not when)
            return
        if k == "logand":
            if not when:
                self.branch(node.lhs, label, False)
                self.branch(node.rhs, label, False)
            else:
                skip = self.new_label()
                self.branch(node.lhs, skip, False)
                self.branch(node.rhs, label, True)
                self.label(skip)
            return
        if k == "logor":
            if when:
                self.branch(node.lhs, label, True)
                self.branch(node.rhs, label, True)
            else:
                skip = self.new_label()
                self.branch(node.lhs, skip, True)
                self.branch(node.rhs, label, False)
                self.label(skip)
            return
        if k in ("eq", "ne", "lt", "le"):
            self.compare_branch(node, label, when)
            return
        if k == "comma":
            self.discard(node.lhs)
            self.branch(node.rhs, label, when)
            return
        if k == "cast" and node.ty.kind == "bool":
            self.branch(node.lhs, label, when)
            return
        # any other scalar: compare with zero
        ty = node.ty
        v = self.gen(node)
        if ty.is_float:
            self.ins("FCMP", self.reg_name(v), "#0")
        elif v.kind == "imm":
            truth = v.imm != 0 if isinstance(v.imm, int) else True
            if truth == when:
                self.ins("RJMP", label)
            return
        elif v.kind == "addr":
            self.free_val(v)
            if when:
                self.ins("RJMP", label)          # an array or function is never null
            return
        else:
            self.ins("TEST", self.reg_name(v))
        self.free_val(v)
        self.ins("RJNF" if when else "RJF", "Z", label)

    def is_free(self, node):
        """Does evaluating node emit no code? (A constant or a register variable.)"""
        k = node.kind
        if k == "num":
            return True
        if k == "var":
            return node.var in self.var_regs
        if k == "cast" and _free_cast(node):
            return self.is_free(node.lhs)
        return False

    def operands(self, lhs, rhs):
        """Evaluate two operands; the one with calls (or the deeper one) first,
        so fewer registers are live across calls. An operand that needs no
        code goes last, so the other may stay in R0."""
        if self.is_free(rhs):
            a = self.gen(lhs)
            return a, self.gen(rhs)
        if self.is_free(lhs):
            b = self.gen(rhs)
            return self.gen(lhs), b
        if (has_call(rhs) and not has_call(lhs)) or \
                (has_call(rhs) == has_call(lhs) and depth(rhs) > depth(lhs) + 1):
            b = self.hold(self.gen(rhs), rhs)
            a = self.gen(lhs)
            if a.kind == "r0" and b.kind == "r0":
                raise CError("internal error: two values in R0")
            return a, b
        a = self.hold(self.gen(lhs), lhs)
        b = self.gen(rhs)
        return a, b

    def compare_branch(self, node, label, when):
        kind = node.kind
        lty = node.lhs.ty
        a, b = self.operands(node.lhs, node.rhs)
        flag, positive = self.compare(kind, lty, a, b, node)
        if flag is None:                         # decided at compile time
            if positive == when:
                self.ins("RJMP", label)
            return
        jump_if_set = positive == when
        if len(flag) > 1 and not jump_if_set:
            # jump when none of the flags is set: RJNF would jump when any is clear
            skip = self.new_label()
            self.ins("RJF", flag, skip)
            self.ins("RJMP", label)
            self.label(skip)
            return
        self.ins("RJF" if jump_if_set else "RJNF", flag, label)

    def compare(self, kind, ty, a, b, node):
        """Emit a compare of a and b (consumed). Returns (flag, positive):
        the comparison is true when flag is set (positive) or clear.
        (None, truth) when the result is known without code."""
        if a.kind == "imm" and b.kind == "imm" and isinstance(a.imm, int) and \
                isinstance(b.imm, int) and not ty.is_float:
            x, y = a.imm & MASK, b.imm & MASK
            if not ty.unsigned:
                x, y = signed(x), signed(y)
            truth = {"eq": x == y, "ne": x != y, "lt": x < y, "le": x <= y}[kind]
            return None, truth
        if ty.is_float:
            return self.compare_float(kind, a, b, node)
        if kind in ("eq", "ne"):
            if a.kind == "imm":
                a, b = b, a
            ra = self.reg_name(a)
            self.ins("CMP", ra, self.operand(b))
            self.free_val(a)
            self.free_val(b)
            return "Z", kind == "eq"
        unsigned = ty.unsigned and ty.kind != "ptr"
        if unsigned:
            return self.compare_unsigned(kind, a, b, node)
        return self.compare_signed(kind, a, b, node)

    def compare_signed(self, kind, a, b, node):
        # CMP x, y sets A when x > y (signed)
        if kind == "lt":
            if b.kind == "imm" and isinstance(b.imm, int):
                c = signed(b.imm)
                if c == INT_MIN:
                    self.free_val(a)
                    return None, False
                self.ins("CMP", self.reg_name(a), f"#{c - 1}")      # a < c  <=>  !(a > c-1)
                self.free_val(a)
                return "A", False
            rb = self.reg_name(b)
            self.ins("CMP", rb, self.operand(a))                 # a < b  <=>  b > a
            self.free_val(a)
            self.free_val(b)
            return "A", True
        # le
        if a.kind == "imm" and isinstance(a.imm, int):
            c = signed(a.imm)
            if c == INT_MIN:
                self.free_val(b)
                return None, True
            self.ins("CMP", self.reg_name(b), f"#{c - 1}")          # c <= b  <=>  b > c-1
            self.free_val(b)
            return "A", True
        self.ins("CMP", self.reg_name(a), self.operand(b))        # a <= b  <=>  !(a > b)
        self.free_val(a)
        self.free_val(b)
        return "A", False

    def compare_unsigned(self, kind, a, b, node):
        # SUB x, y sets C when x < y (unsigned): a borrow
        if kind == "lt":
            if a.kind == "imm" and isinstance(a.imm, int):
                c = a.imm & MASK
                if c == UINT_MAX:
                    self.free_val(b)
                    return None, False
                self.ins("SUB", self.reg_name(b), f"#{signed(c + 1)}")  # c < b  <=>  !(b < c+1)
                self.free_val(b)
                return "C", False
            self.ins("SUB", self.reg_name(a), self.operand(b))
            self.free_val(a)
            self.free_val(b)
            return "C", True
        # le: a <= b  <=>  !(b < a)
        if b.kind == "imm" and isinstance(b.imm, int):
            c = b.imm & MASK
            if c == UINT_MAX:
                self.free_val(a)
                return None, True
            self.ins("SUB", self.reg_name(a), f"#{signed(c + 1)}")      # a < c+1
            self.free_val(a)
            return "C", True
        self.ins("SUB", self.reg_name(b), self.operand(a))
        self.free_val(a)
        self.free_val(b)
        return "C", False

    def compare_float(self, kind, a, b, node):
        # FCMP x, y: N when x < y, Z when equal (from x - y)
        if kind in ("eq", "ne"):
            if a.kind == "imm":
                a, b = b, a
            self.ins("FCMP", self.reg_name(a), self.operand(b))
            self.free_val(a)
            self.free_val(b)
            return "Z", kind == "eq"
        if kind == "lt":
            ra = self.reg_name(a)
            self.ins("FCMP", ra, self.operand(b))
            self.free_val(a)
            self.free_val(b)
            return "N", True
        # le: a < b or a == b (N or Z). Not !(b < a): with a NaN that is true,
        # and C wants every ordered comparison with a NaN to be false.
        ra = self.reg_name(a)
        self.ins("FCMP", ra, self.operand(b))
        self.free_val(a)
        self.free_val(b)
        return "NZ", True

    def gen_bool(self, node):
        """A condition's value as 0 or 1."""
        r = self.alloc(node)
        self.ins("DATA", f"R{r}", "0")
        skip = self.new_label()
        self.branch(node, skip, False)
        self.ins("DATA", f"R{r}", "1")
        self.label(skip)
        return Val("reg", reg=r)

    # ================================================================ expressions
    def gen(self, node):
        """Evaluate an expression; returns a Val."""
        k = node.kind
        ty = node.ty
        if k == "num":
            if ty.is_float:
                return Val("imm", imm=float_bits(node.val), flt=True)
            return Val("imm", imm=node.val & MASK)
        if k in ("var", "member", "deref"):
            if ty.kind in ("array", "struct", "union", "func"):
                return Val("addr", addr=self.gen_addr(node))
            if k == "member" and node.member.is_bitfield:
                addr = self.gen_addr(node.lhs).plus(node.member.offset)
                v = self.load_bitfield(addr, node.member, node)
                self.free_addr(addr)
                return v
            addr = self.gen_addr(node)
            v = self.load(addr, ty)
            return v
        if k == "addr":
            return self.materialize(self.gen_addr(node.lhs), node)
        if k == "cast":
            return self.gen_cast(node)
        if k in ("add", "sub") and ty.kind == "ptr":
            return self.materialize(self.gen_ptr(node), node)
        if k in ("add", "sub", "mul", "div", "mod", "bitand", "bitor", "bitxor", "shl", "shr"):
            a, b = self.operands(node.lhs, node.rhs)
            return self.binop(k, ty, a, b, node)
        if k == "sub" and ty.is_integer and node.lhs.ty.kind == "ptr":
            a, b = self.operands(node.lhs, node.rhs)
            return self.binop("sub", T.int_type(), a, b, node)
        if k in ("eq", "ne", "lt", "le", "logand", "logor", "not"):
            return self.gen_bool(node)
        if k == "neg":
            v = self.gen(node.lhs)
            if v.kind == "imm" and isinstance(v.imm, int) and not ty.is_float:
                return Val("imm", imm=(-v.imm) & MASK)
            r = self.reg_name(v)
            self.free_val(v)
            self.ins("FNEG" if ty.is_float else "NEG", r)
            return Val("r0")
        if k == "bitnot":
            v = self.gen(node.lhs)
            r = self.reg_name(v)
            self.free_val(v)
            self.ins("NOT", r)
            return Val("r0")
        if k == "assign":
            return self.gen_assign(node)
        if k == "assign_op":
            return self.gen_assign_op(node)
        if k in ("preinc", "predec", "postinc", "postdec"):
            return self.gen_incdec(node)
        if k == "cond":
            return self.gen_cond_expr(node)
        if k == "comma":
            self.discard(node.lhs)
            return self.gen(node.rhs)
        if k == "funcall":
            return self.gen_call(node)
        if k == "memzero":
            self.memzero(node.var)
            return Val("void")
        if k == "block_expr":
            return Val("void")
        if k == "builtin":
            return self.gen_builtin(node)
        raise self.error(node, f"internal error: can't generate '{k}'")

    # ---------------------------------------------------------------- addresses
    def gen_addr(self, node):
        """The Addr of an lvalue (or of an aggregate value)."""
        k = node.kind
        if k == "var":
            var = node.var
            if var in self.var_regs:
                return Addr("var", var_reg=self.var_regs[var])
            if var.is_local:
                return Addr("frame", off=var.offset)
            self.use(var.asm_name)
            return Addr("abs", label=var.asm_name)
        if k == "deref":
            return self.gen_ptr(node.lhs)
        if k == "member":
            if node.lhs.kind in ("var", "deref", "member"):
                base = self.gen_addr(node.lhs)
            else:
                v = self.gen(node.lhs)
                if v.kind != "addr":
                    raise self.error(node, "internal error: member of a non-aggregate")
                base = v.addr
            return base.plus(node.member.offset)
        if k == "comma":
            self.discard(node.lhs)
            return self.gen_addr(node.rhs)
        if node.ty.kind in ("struct", "union", "array", "func") or k in ("funcall", "assign", "cond"):
            v = self.gen(node)
            if v.kind == "addr":
                return v.addr
            r = self.to_reg(v, node)
            return Addr("abs", reg=r)
        raise self.error(node, "internal error: not an lvalue")

    def gen_ptr(self, node):
        """The Addr that a pointer-valued (or array) expression points at."""
        k = node.kind
        ty = node.ty
        if ty.kind == "array":
            return self.gen_addr(node)
        if ty.is_func:
            return self.gen_addr(node)
        if k == "addr":
            return self.gen_addr(node.lhs)
        if k == "cast" and (node.lhs.ty.is_ptr_like or node.lhs.ty.is_func) and ty.kind == "ptr":
            return self.gen_ptr(node.lhs)
        if k in ("add", "sub") and ty.kind == "ptr" and node.lhs.ty.is_ptr_like:
            idx = node.rhs
            if idx.kind == "num":
                base = self.gen_ptr(node.lhs)
                n = signed(idx.val)
                return base.plus(n if k == "add" else -n)
            if has_call(idx) and not has_call(node.lhs):
                iv = self.hold(self.gen(idx), idx)
                base = self.gen_ptr(node.lhs)
            else:
                base = self.gen_ptr(node.lhs)
                iv = self.gen(idx)
            if k == "sub":
                ri = self.reg_name(iv)
                self.free_val(iv)
                self.ins("NEG", ri)
                iv = Val("r0")
            return self.addr_add(base, iv, node)
        v = self.gen(node)
        if v.kind == "imm":
            if isinstance(v.imm, int):
                return Addr("abs", off=v.imm)
            return Addr("abs", reg=self.to_reg(v, node))
        if v.kind == "addr":
            return v.addr
        if v.kind == "vreg":                     # a pointer variable: use its register
            return Addr("abs", reg=v.reg, owned=False)
        r = self.to_reg(v, node)
        return Addr("abs", reg=r)

    def addr_add(self, base, iv, node):
        """base + a runtime index (a Val, consumed)."""
        if iv.kind == "imm" and isinstance(iv.imm, int):
            return base.plus(signed(iv.imm))
        if base.reg is None:
            if iv.kind == "vreg":                # an index variable: use its register
                return Addr(base.kind, reg=iv.reg, off=base.off, label=base.label, owned=False)
            r = self.to_reg(iv, node)
            return Addr(base.kind, reg=r, off=base.off, label=base.label)
        self.ins("ADD", f"R{base.reg}", self.operand(iv))
        self.free_val(iv)
        return self.own(base, node)

    def own(self, base, node=None):
        """After an ALU op left base's new register value in R0: put it in a
        register base owns."""
        if base.owned:
            self.ins("CPY", "R0", f"R{base.reg}")
            return base
        r = self.alloc(node)
        self.ins("CPY", "R0", f"R{r}")
        return Addr(base.kind, reg=r, off=base.off, label=base.label)

    def materialize(self, addr, node=None):
        """An Addr as a pointer value."""
        if addr.kind == "var":
            raise self.error(node, "internal error: the address of a register variable")
        if addr.kind == "abs":
            if addr.reg is None:
                if addr.label is not None:
                    return Val("imm", imm=addr.sym())
                return Val("imm", imm=addr.off & MASK)
            r = addr.reg
            if addr.label is not None:
                self.ins("DATA", f"R{SCRATCH}", addr.sym())
                self.ins("ADD", f"R{r}", f"R{SCRATCH}")
            elif addr.off:
                self.ins("ADD", f"R{r}", f"#{signed(addr.off)}")
            elif not addr.owned:
                return Val("vreg", reg=r)
            else:
                return Val("reg", reg=r)
            if addr.owned:
                self.ins("CPY", "R0", f"R{r}")
                return Val("reg", reg=r)
            return Val("r0")
        # a frame slot: FP + index
        self.load_fp()
        if addr.reg is not None:
            self.ins("ADD", "R0", f"R{addr.reg}")
        if addr.off:
            self.ins("ADD", "R0", f"#{signed(addr.off)}")
        if addr.reg is not None and addr.owned:
            self.ins("CPY", "R0", f"R{addr.reg}")
            return Val("reg", reg=addr.reg)
        return Val("r0")

    # ---------------------------------------------------------------- loads and stores
    def frame_index(self, addr):
        """Put a frame Addr's index in a register for STK GET/SET; returns
        the register name. Uses R0 when the index needs adding."""
        if addr.reg is None:
            self.ins("DATA", f"R{SCRATCH}", str(signed(addr.off)))
            return f"R{SCRATCH}"
        if addr.off == 0:
            return f"R{addr.reg}"
        self.ins("ADD", f"R{addr.reg}", f"#{signed(addr.off)}")
        self.ins("CPY", "R0", f"R{SCRATCH}")
        return f"R{SCRATCH}"

    def load(self, addr, ty):
        """Load the scalar at addr. The Addr's register is freed."""
        if addr.kind == "var":
            return Val("vreg", reg=addr.var_reg)
        if addr.kind == "frame":
            idx = self.frame_index(addr)
            self.ins("STK", "GET", idx)
            self.free_addr(addr)
            return Val("r0")
        if addr.reg is None:
            self.ins("DATA", f"R{SCRATCH}", addr.sym())
            r = self.alloc()
            self.ins("LD", f"R{SCRATCH}", f"R{r}")
            return Val("reg", reg=r)
        if addr.label is None and addr.off == 0:
            if addr.owned:
                self.ins("LD", f"R{addr.reg}", f"R{addr.reg}")
                return Val("reg", reg=addr.reg)
            r = self.alloc()
            self.ins("LD", f"R{addr.reg}", f"R{r}")
            return Val("reg", reg=r)
        self.ins("DATA", f"R{SCRATCH}", addr.sym())
        self.ins("ALD", f"R{addr.reg}", f"R{SCRATCH}")
        self.free_addr(addr)
        return Val("r0")

    def load_keep(self, addr, ty):
        """Load without giving up the Addr's register (for read-modify-write)."""
        if addr.kind == "var":
            return Val("vreg", reg=addr.var_reg)
        if addr.kind == "frame":
            idx = self.frame_index(addr)
            self.ins("STK", "GET", idx)
            return Val("r0")
        if addr.reg is None:
            self.ins("DATA", f"R{SCRATCH}", addr.sym())
            r = self.alloc()
            self.ins("LD", f"R{SCRATCH}", f"R{r}")
            return Val("reg", reg=r)
        if addr.label is None and addr.off == 0:
            self.ins("LD", f"R{addr.reg}", "R0")
            return Val("r0")
        self.ins("DATA", f"R{SCRATCH}", addr.sym())
        self.ins("ALD", f"R{addr.reg}", f"R{SCRATCH}")
        return Val("r0")

    def store(self, addr, v):
        """Store a scalar value at addr. Returns the value (now in R0 or its
        register). The Addr's register is kept: free it yourself."""
        if addr.kind == "var":
            r = addr.var_reg
            if v.kind == "imm":
                self.ins("DATA", f"R{r}", self.imm_text(v.imm, v.flt))
            elif not (v.kind == "vreg" and v.reg == r):
                self.ins("CPY", self.reg_name(v), f"R{r}")
                self.free_val(v)
            return Val("vreg", reg=r)
        if addr.kind == "frame":
            if addr.reg is not None and addr.off != 0:
                v = self.hold(v)
                idx = self.frame_index(addr)
            else:
                idx = self.frame_index(addr)
            self.to_r0(v)
            self.ins("STK", "SET", idx)
            return Val("r0")
        if addr.reg is None:
            if v.kind == "imm":
                self.to_r0(v)
                v = Val("r0")
            src = self.reg_name(v)
            self.ins("DATA", f"R{SCRATCH}", addr.sym())
            self.ins("ST", f"R{SCRATCH}", src)
            return v
        if addr.label is None and addr.off == 0:
            if v.kind == "imm":
                self.to_r0(v)
                v = Val("r0")
            self.ins("ST", f"R{addr.reg}", self.reg_name(v))
            return v
        self.ins("DATA", f"R{SCRATCH}", addr.sym())
        self.to_r0(v)
        self.ins("AST", f"R{addr.reg}", f"R{SCRATCH}")
        return Val("r0")

    def copy_words(self, dst, src, n):
        """Copy n words from src to dst (two Addrs; their registers kept)."""
        if n <= 0:
            return
        if n <= 8:
            for i in range(n):
                v = self.load_keep(src.plus(i), None)
                v = self.hold(v) if dst.kind == "frame" and dst.reg is not None else v
                if v.kind == "reg" and dst.kind != "frame":
                    pass
                out = self.store(dst.plus(i), v)
                self.free_val(out)
            return
        # longer: a loop over absolute addresses, from the last word down
        s = self.address_copy(src)
        d = self.address_copy(dst)
        loop = self.new_label()
        self.ins("DATA", f"R{SCRATCH}", str(n - 1))
        self.label(loop)
        self.ins("ALD", f"R{s}", f"R{SCRATCH}")
        self.ins("AST", f"R{d}", f"R{SCRATCH}")
        self.ins("--", f"R{SCRATCH}")
        self.ins("CPY", "R0", f"R{SCRATCH}")
        self.ins("RJNF", "N", loop)
        self.release(s)
        self.release(d)

    def address_copy(self, addr):
        """A new register holding addr's full address (addr is untouched)."""
        r = self.alloc()
        if addr.kind == "frame":
            self.load_fp()
            if addr.reg is not None:
                self.ins("ADD", "R0", f"R{addr.reg}")
            if addr.off:
                self.ins("ADD", "R0", f"#{signed(addr.off)}")
            self.ins("CPY", "R0", f"R{r}")
        elif addr.reg is None:
            self.ins("DATA", f"R{r}", addr.sym())
        elif addr.label is None and addr.off == 0:
            self.ins("CPY", f"R{addr.reg}", f"R{r}")
        else:
            self.ins("DATA", f"R{SCRATCH}", addr.sym())
            self.ins("ADD", f"R{addr.reg}", f"R{SCRATCH}")
            self.ins("CPY", "R0", f"R{r}")
        return r

    def memzero(self, var):
        n = var.ty.size
        if n <= 0:
            return
        if n <= 24:
            self.ins("DATA", "R0", "0")
            for i in range(n):
                self.ins("DATA", f"R{SCRATCH}", str(var.offset + i))
                self.ins("STK", "SET", f"R{SCRATCH}")
            return
        loop = self.new_label()
        self.ins("DATA", f"R{SCRATCH}", str(var.offset + n - 1))
        self.label(loop)
        self.ins("DATA", "R0", "0")
        self.ins("STK", "SET", f"R{SCRATCH}")
        self.ins("--", f"R{SCRATCH}")
        self.ins("CPY", "R0", f"R{SCRATCH}")
        self.ins("CMP", f"R{SCRATCH}", f"#{var.offset}")
        self.ins("RJF", "AZ", loop)

    # ---------------------------------------------------------------- bit-fields
    def load_bitfield(self, addr, m, node):
        word = self.load_keep(addr, None)
        word = self.hold(word, node)
        r = word.reg
        w, off = m.bit_width, m.bit_offset
        if m.ty.unsigned or m.ty.kind == "bool":
            if off:
                self.lshr_const(r, off)
                self.ins("AND", "R0", f"#{(1 << w) - 1 if w < 32 else -1}")
            elif w < 32:
                self.ins("AND", f"R{r}", f"#{(1 << w) - 1}")
            else:
                self.ins("CPY", f"R{r}", "R0")
        else:
            up = 32 - off - w
            if up:
                self.ins("MULT", f"R{r}", f"#{signed(1 << up)}")
                self.ins("CPY", "R0", f"R{r}")
            down = 32 - w
            if down:
                self.ashr_const(r, down)
            else:
                self.ins("CPY", f"R{r}", "R0")
        self.release(r)
        return Val("r0")

    def store_bitfield(self, addr, m, v, node):
        """Store v into a bit-field; returns the stored value (as the field reads)."""
        w, off = m.bit_width, m.bit_offset
        mask = (1 << w) - 1 if w < 32 else MASK
        val = self.hold(v, node)
        rv = self.to_reg(val, node)
        # the value cut to the field's width
        self.ins("AND", f"R{rv}", f"#{signed(mask)}")
        self.ins("CPY", "R0", f"R{rv}")
        word = self.hold(self.load_keep(addr, None), node)
        rw = word.reg
        self.ins("AND", f"R{rw}", f"#{signed(~(mask << off) & MASK)}")
        self.ins("CPY", "R0", f"R{rw}")
        if off:
            self.ins("MULT", f"R{rv}", f"#{signed(1 << off)}")
            self.ins("OR", f"R{rw}", "R0")
        else:
            self.ins("OR", f"R{rw}", f"R{rv}")
        self.release(rw)
        out = self.store(addr, Val("r0"))
        self.free_val(out)
        # the result of the assignment: the value as the field holds it
        if not (m.ty.unsigned or m.ty.kind == "bool") and w < 32:
            self.ins("MULT", f"R{rv}", f"#{signed(1 << (32 - w))}")
            self.ins("CPY", "R0", f"R{rv}")
            self.ashr_const(rv, 32 - w)
            self.ins("CPY", "R0", f"R{rv}")
        return Val("reg", reg=rv)

    # ---------------------------------------------------------------- shifts
    def lshr_const(self, r, k):
        """R0 = R<r> >> k, logical (k in 1..31)."""
        self.ins("SHR", f"R{r}")
        if k > 1:
            self.ins("DIV", "R0", f"#{1 << (k - 1)}")

    def ashr_const(self, r, k):
        """R0 = R<r> >> k, arithmetic (k in 1..31)."""
        neg = self.new_label()
        done = self.new_label()
        self.ins("TEST", f"R{r}")
        self.ins("RJF", "N", neg)
        self.lshr_const(r, k)
        self.ins("RJMP", done)
        self.label(neg)
        self.ins("NOT", f"R{r}")
        self.ins("CPY", "R0", f"R{SCRATCH}")
        self.lshr_const(SCRATCH, k)
        self.ins("NOT", "R0")
        self.label(done)

    def shift(self, kind, ty, a, b, node):
        ra = self.to_reg(a, node)
        if b.kind == "imm" and isinstance(b.imm, int):
            k = b.imm & MASK
            if k >= 32:
                k &= 31                         # undefined in C; keep it in range
            self.release(ra)
            if k == 0:
                self.ins("CPY", f"R{ra}", "R0")
                return Val("r0")
            if kind == "shl":
                self.ins("MULT", f"R{ra}", f"#{signed(1 << k)}")
            elif ty.unsigned:
                self.lshr_const(ra, k)
            else:
                self.ashr_const(ra, k)
            return Val("r0")
        rb = self.to_reg(b, node)
        self.use("_pow2")
        if kind == "shl":
            self.ins("DATA", "R14", "_pow2")
            self.ins("ALD", "R14", f"R{rb}")          # R0 = 2^n
            self.ins("MULT", f"R{ra}", "R0")
        else:
            zero = self.new_label()
            done = self.new_label()
            src = ra
            neg = None
            if not ty.unsigned:
                neg = self.new_label()
            self.ins("TEST", f"R{rb}")
            self.ins("RJF", "Z", zero)
            if neg:
                self.ins("TEST", f"R{ra}")
                self.ins("RJF", "N", neg)
            self.logical_shift_var(ra, rb)
            self.ins("RJMP", done)
            if neg:
                self.label(neg)
                self.ins("NOT", f"R{ra}")
                self.ins("CPY", "R0", f"R{ra}")
                self.logical_shift_var(ra, rb)
                self.ins("NOT", "R0")
                self.ins("RJMP", done)
            self.label(zero)
            self.ins("CPY", f"R{src}", "R0")
            self.label(done)
        self.release(ra)
        self.release(rb)
        return Val("r0")

    def logical_shift_var(self, ra, rb):
        """R0 = R<ra> >> R<rb>, logical, for a count of 1..31."""
        self.ins("SHR", f"R{ra}")
        self.ins("CPY", "R0", f"R{SCRATCH}")
        self.ins("DATA", "R14", "_pow2 - 1")
        self.ins("ALD", "R14", f"R{rb}")              # R0 = 2^(n-1)
        self.ins("DIV", f"R{SCRATCH}", "R0")

    # ---------------------------------------------------------------- arithmetic
    COMMUTATIVE = {"add", "mul", "bitand", "bitor", "bitxor"}
    INT_OPS = {"add": "ADD", "sub": "SUB", "mul": "MULT", "div": "DIV", "mod": "MOD",
               "bitand": "AND", "bitor": "OR", "bitxor": "XOR"}
    FLOAT_OPS = {"add": "FADD", "sub": "FSUB", "mul": "FMULT", "div": "FDIV"}

    def binop(self, kind, ty, a, b, node):
        """a op b (both consumed) -> Val (usually in R0)."""
        if kind in ("shl", "shr"):
            return self.shift(kind, ty, a, b, node)
        if ty.is_float:
            if a.kind == "imm" and kind in self.COMMUTATIVE:
                a, b = b, a
            ra = self.reg_name(a)
            self.ins(self.FLOAT_OPS[kind], ra, self.operand(b))
            self.free_val(a)
            self.free_val(b)
            return Val("r0")
        if a.kind == "imm" and kind in self.COMMUTATIVE and b.kind != "imm":
            a, b = b, a
        if kind in ("div", "mod") and ty.unsigned:
            return self.unsigned_divmod(kind, a, b, node)
        if b.kind == "imm" and isinstance(b.imm, int):
            c = b.imm & MASK
            if kind in ("add", "sub", "bitor", "bitxor") and c == 0 or \
                    kind in ("mul", "div") and c == 1:
                return a
            if kind == "add" and c == 1 or kind == "sub" and c == MASK:
                self.ins("++", self.reg_name(a))
                self.free_val(a)
                return Val("r0")
            if kind == "sub" and c == 1 or kind == "add" and c == MASK:
                self.ins("--", self.reg_name(a))
                self.free_val(a)
                return Val("r0")
        ra = self.reg_name(a)
        self.ins(self.INT_OPS[kind], ra, self.operand(b))
        self.free_val(a)
        self.free_val(b)
        return Val("r0")

    def unsigned_divmod(self, kind, a, b, node):
        if b.kind == "imm" and isinstance(b.imm, int):
            c = b.imm & MASK
            if c and c & (c - 1) == 0:                 # a power of two
                k = c.bit_length() - 1
                ra = self.to_reg(a, node)
                self.release(ra)
                if kind == "mod":
                    self.ins("AND", f"R{ra}", f"#{signed(c - 1)}")
                elif k == 0:
                    self.ins("CPY", f"R{ra}", "R0")
                else:
                    self.lshr_const(ra, k)
                return Val("r0")
        # runtime helper: R15 = a, R13 = b, return address in R14
        helper = "_udiv" if kind == "div" else "_umod"
        self.use(helper)
        if a.kind == "imm":
            self.ins("DATA", "R15", self.imm_text(a.imm))
        else:
            self.ins("CPY", self.reg_name(a), "R15")
        if b.kind == "imm":
            self.ins("DATA", f"R{SCRATCH}", self.imm_text(b.imm))
        else:
            self.ins("CPY", self.reg_name(b), f"R{SCRATCH}")
        self.free_val(a)
        self.free_val(b)
        back = self.new_label()
        self.ins("DATA", "R14", back)
        self.ins("RJMP", helper)
        self.label(back)
        return Val("r0")

    # ---------------------------------------------------------------- conversions
    def gen_cast(self, node):
        to = node.ty
        src_ty = node.lhs.ty
        if to.is_void:
            self.discard(node.lhs)
            return Val("void")
        if src_ty.kind in ("array", "func"):
            return self.materialize(self.gen_ptr(node.lhs), node)
        if to.kind == "bool":
            if src_ty.kind == "bool":
                return self.gen(node.lhs)
            return self.gen_bool(node)
        v = self.gen(node.lhs)
        return self.convert(v, src_ty, to, node)

    def convert(self, v, src, to, node):
        if src.is_float and to.is_float:
            return v
        if to.is_float and not src.is_float:
            if v.kind == "imm" and isinstance(v.imm, int):
                x = v.imm & MASK if src.unsigned else signed(v.imm)
                return Val("imm", imm=float_bits(float(x)), flt=True)
            if src.unsigned and src.kind != "bool":
                return self.unsigned_to_float(v, node)
            r = self.reg_name(v)
            self.free_val(v)
            self.ins("FLOAT", r)
            return Val("r0")
        if src.is_float and not to.is_float:
            if to.kind == "bool":
                raise CError("internal error: float to bool goes through gen_bool")
            if to.unsigned:
                return self.float_to_unsigned(v, node)
            r = self.reg_name(v)
            self.free_val(v)
            self.ins("INT", r)
            return Val("r0")
        return v                                 # integers and pointers: all one word

    def unsigned_to_float(self, v, node):
        r = self.to_reg(self.hold(v, node), node)
        big = self.new_label()
        done = self.new_label()
        self.ins("TEST", f"R{r}")
        self.ins("RJF", "N", big)
        self.ins("FLOAT", f"R{r}")
        self.ins("RJMP", done)
        self.label(big)                          # >= 2^31: halve (keeping the low bit), double
        self.ins("SHR", f"R{r}")
        self.ins("CPY", "R0", f"R{SCRATCH}")
        self.ins("AND", f"R{r}", "#1")
        self.ins("OR", f"R{SCRATCH}", "R0")
        self.ins("FLOAT", "R0")
        self.ins("FADD", "R0", "R0")
        self.label(done)
        self.release(r)
        return Val("r0")

    def float_to_unsigned(self, v, node):
        r = self.to_reg(self.hold(v, node), node)
        small = self.new_label()
        done = self.new_label()
        self.ins("FCMP", f"R{r}", "#2147483648.0")
        self.ins("RJF", "N", small)
        self.ins("FSUB", f"R{r}", "#2147483648.0")
        self.ins("INT", "R0")
        self.ins("XOR", "R0", "#0x80000000")
        self.ins("RJMP", done)
        self.label(small)
        self.ins("INT", f"R{r}")
        self.label(done)
        self.release(r)
        return Val("r0")

    # ---------------------------------------------------------------- assignment
    def gen_assign(self, node, want=True):
        lhs, rhs = node.lhs, node.rhs
        ty = lhs.ty
        if ty.is_struct:
            if has_call(rhs):
                src = self.gen(rhs)
                dst = self.gen_addr(lhs)
            else:
                dst = self.gen_addr(lhs)
                src = self.gen(rhs)
            self.copy_words(dst, src.addr, ty.size)
            self.free_addr(src.addr)
            return Val("addr", addr=dst)
        if lhs.kind == "member" and lhs.member.is_bitfield:
            v = self.hold(self.gen(rhs), rhs)
            addr = self.gen_addr(lhs.lhs).plus(lhs.member.offset)
            out = self.store_bitfield(addr, lhs.member, v, node)
            self.free_addr(addr)
            return out
        if self.simple_addr(lhs):
            v = self.gen(rhs)                    # the address needs no code: R0 is safe
            addr = self.gen_addr(lhs)
        elif has_call(rhs):
            v = self.hold(self.gen(rhs), rhs)
            addr = self.gen_addr(lhs)
        else:
            addr = self.gen_addr(lhs)
            v = self.gen(rhs)
        out = self.store(addr, v)
        self.free_addr(addr)
        if not want:
            self.free_val(out)
            return Val("void")
        return self.hold(out, node)

    def simple_addr(self, node):
        """An lvalue whose Addr needs no registers and no code."""
        if node.kind == "var":
            return True
        if node.kind == "member" and not node.member.is_bitfield:
            return self.simple_addr(node.lhs)
        return False

    def gen_assign_op(self, node, want=True):
        lhs = node.lhs
        ty = lhs.ty
        if lhs.kind == "member" and lhs.member.is_bitfield:
            # read, compute, write back through the bit-field code
            rv = self.hold(self.gen(node.rhs), node.rhs)
            addr = self.gen_addr(lhs.lhs).plus(lhs.member.offset)
            cur = self.hold(self.load_bitfield(addr, lhs.member, node), node)
            calc_ty = node.calc_ty
            res = self.binop(node.op, calc_ty, cur, rv, node)
            out = self.store_bitfield(addr, lhs.member, res, node)
            self.free_addr(addr)
            return out
        if has_call(node.rhs):
            rv = self.hold(self.gen(node.rhs), node.rhs)
            addr = self.gen_addr(lhs)
        else:
            addr = self.gen_addr(lhs)
            rv = self.hold(self.gen(node.rhs), node.rhs)
        cur = self.hold(self.load_keep(addr, ty), node)
        if ty.kind == "ptr":
            calc_ty = T.int_type()
        else:
            calc_ty = node.calc_ty
            cur = self.hold(self.convert(cur, ty, calc_ty, node), node)
        res = self.binop(node.op, calc_ty, cur, rv, node)
        if ty.kind != "ptr":
            res = self.convert(res, calc_ty, T.unqualified(ty), node)
            if ty.kind == "bool":
                res = self.to_bool(res, node)
        if addr.kind == "frame" and addr.reg is not None and addr.off != 0:
            res = self.hold(res, node)
        out = self.store(addr, res)
        self.free_addr(addr)
        if not want:
            self.free_val(out)
            return Val("void")
        return self.hold(out, node)

    def to_bool(self, v, node):
        r = self.reg_name(v)
        self.free_val(v)
        t = self.alloc(node)
        self.ins("TEST", r)
        self.ins("DATA", f"R{t}", "0")
        skip = self.new_label()
        self.ins("RJF", "Z", skip)
        self.ins("DATA", f"R{t}", "1")
        self.label(skip)
        return Val("reg", reg=t)

    def gen_incdec(self, node, want=True):
        lhs = node.lhs
        ty = lhs.ty
        pre = node.kind in ("preinc", "predec")
        up = node.kind in ("preinc", "postinc")
        if not want and not (lhs.kind == "member" and lhs.member.is_bitfield):
            # only the new value matters: no copy of the old one
            addr = self.gen_addr(lhs)
            cur = self.load_keep(addr, ty)
            if addr.kind == "frame" and addr.reg is not None and addr.off != 0:
                cur = self.hold(cur, node)
            name = self.reg_name(cur)
            if ty.is_float:
                self.ins("FADD" if up else "FSUB", name, "#1.0")
            elif ty.kind == "bool":
                if up:
                    self.ins("DATA", "R0", "1")
                else:
                    self.ins("XOR", name, "#1")
            elif node.step == 1:
                self.ins("++" if up else "--", name)
            else:
                self.ins("ADD" if up else "SUB", name, f"#{node.step}")
            self.free_val(cur)
            out = self.store(addr, Val("r0"))
            self.free_val(out)
            self.free_addr(addr)
            return Val("void")
        if lhs.kind == "member" and lhs.member.is_bitfield:
            addr = self.gen_addr(lhs.lhs).plus(lhs.member.offset)
            old = self.hold(self.load_bitfield(addr, lhs.member, node), node)
            r = old.reg
            self.ins("++" if up else "--", f"R{r}")
            new = self.store_bitfield(addr, lhs.member, Val("r0"), node)
            self.free_addr(addr)
            if pre:
                self.release(r)
                return new
            self.free_val(new)
            return Val("reg", reg=r)
        addr = self.gen_addr(lhs)
        old = self.hold(self.load_keep(addr, ty), node)
        r = self.to_reg(old, node)
        if ty.is_float:
            self.ins("FADD" if up else "FSUB", f"R{r}", "#1.0")
        elif ty.kind == "bool":
            # ++ on _Bool sets it to 1; -- flips it
            if up:
                self.ins("DATA", "R0", "1")
            else:
                self.ins("XOR", f"R{r}", "#1")
        elif node.step == 1:
            self.ins("++" if up else "--", f"R{r}")
        else:
            self.ins("ADD" if up else "SUB", f"R{r}", f"#{node.step}")
        if addr.kind == "frame" and addr.reg is not None and addr.off != 0:
            t = self.hold(Val("r0"), node)
            out = self.store(addr, t)
        else:
            out = self.store(addr, Val("r0"))
        self.free_addr(addr)
        if pre:
            self.release(r)
            return self.hold(out, node) if out.kind == "r0" else out
        self.free_val(out)
        return Val("reg", reg=r)

    def gen_cond_expr(self, node):
        ty = node.ty
        else_label = self.new_label()
        end = self.new_label()
        self.branch(node.cond, else_label, False)
        v = self.gen(node.then)
        if ty.is_void:
            self.free_val(v)
            self.ins("RJMP", end)
            self.label(else_label)
            self.free_val(self.gen(node.els))
            self.label(end)
            return Val("void")
        if v.kind == "addr":
            v = self.materialize(v.addr, node)
        r = self.to_reg(v, node)
        self.ins("RJMP", end)
        self.label(else_label)
        w = self.gen(node.els)
        if w.kind == "addr":
            w = self.materialize(w.addr, node)
        if w.kind == "reg" and w.reg == r:
            pass
        elif w.kind == "imm":
            self.ins("DATA", f"R{r}", self.imm_text(w.imm))
        else:
            src = self.reg_name(w)
            self.ins("CPY", src, f"R{r}")
            self.free_val(w)
        self.label(end)
        if ty.is_struct:
            return Val("addr", addr=Addr("abs", reg=r))
        return Val("reg", reg=r)

    # ---------------------------------------------------------------- calls
    def save_live(self, var_regs=()):
        """SAVE the live temporaries (and these variable registers) before a
        call; the temporaries are free for the call's arguments."""
        temps = self.live()
        regs = sorted(set(temps) | set(var_regs))
        if regs:
            self.ins("SAVE", *[f"R{r}" for r in regs])
            for r in temps:
                self.release(r)
        return temps, regs

    def restore_live(self, saved):
        temps, regs = saved
        if regs:
            for r in temps:
                if r in self.free:
                    self.free.remove(r)
            self.ins("RESTORE", *[f"R{r}" for r in regs])

    def vars_across(self, node):
        """Register variables a call (or asm statement) must keep: (kept with
        SAVE/RESTORE, kept in their stack slot because the call's own
        arguments change them)."""
        if not self.var_regs:
            return [], []
        pos = self.call_pos.get(id(node))
        live = [v for v in self.var_regs
                if pos is None or self.analysis.live_at(v, pos)]
        changed = regalloc.assigned_vars(node, self.var_regs) if node.kind == "funcall" else set()
        keep = [v for v in live if v not in changed]
        spill = [v for v in live if v in changed]
        return keep, spill

    def var_slot(self, var):
        if var.offset is None:
            var.offset = self.alloc_slot()
        return var.offset

    def push(self, v):
        self.to_r0(v)
        self.ins("STK", "PUSH")

    def push_arg(self, arg):
        """Push one argument; returns how many words it took."""
        v = self.gen(arg)
        if arg.ty.is_struct:
            a = v.addr
            for i in range(arg.ty.size):
                w = self.load_keep(a.plus(i), None)
                self.push(w)
            self.free_addr(a)
            return arg.ty.size
        self.push(v)
        return 1

    def gen_call(self, node, want=True):
        fty = node.func_ty
        keep, spill = self.vars_across(node)
        saved = self.save_live([self.var_regs[v] for v in keep])
        nfixed = len(fty.params)
        pushed = 0
        fixed_args = node.args[:nfixed] if fty.variadic else node.args
        var_args = node.args[nfixed:] if fty.variadic else []
        if fty.variadic:
            for a in var_args:
                pushed += self.push_arg(a)
        nvar = pushed
        if node.ret_buf is not None:
            self.push(self.materialize(Addr("frame", off=node.ret_buf.offset), node))
            pushed += 1
        for a in fixed_args:
            pushed += self.push_arg(a)
        if fty.variadic:
            self.ins("DATA", "R0", str(nvar))
            self.ins("STK", "PUSH")
            pushed += 1
        f = node.func
        direct = f.kind == "var" and f.var.is_function
        if not direct:
            fv = self.gen(f)
            fr = self.to_reg(fv, node) if fv.kind != "addr" else \
                self.to_reg(self.materialize(fv.addr, node), node)
        for v in spill:                          # changed by the arguments: keep in memory
            self.ins("CPY", f"R{self.var_regs[v]}", "R0")
            self.ins("DATA", f"R{SCRATCH}", str(self.var_slot(v)))
            self.ins("STK", "SET", f"R{SCRATCH}")
        # the call: like the CALL pseudo-instruction, with RJMP for a direct
        # call (one instruction less than DATA + JMRB)
        back = self.new_label()
        self.ins("DATA", "R0", back)
        self.ins("STK", "PUSH")
        self.ins("STK", "CALL")
        if direct:
            self.use(f.var.asm_name)
            self.ins("RJMP", f.var.asm_name)
        else:
            self.ins("JMRB", f"R{fr}")
            self.release(fr)
        self.label(back)
        # after it: drop the arguments, put back what was saved, keeping
        # R0 (in R15) only when the result is used
        temps, regs = saved
        keep_r0 = want and not node.ty.is_void and node.ret_buf is None
        busy = pushed or regs or spill
        if keep_r0 and busy:
            self.ins("CPY", "R0", "R15")
        for _ in range(pushed):
            self.ins("STK", "POP")
        for r in reversed(regs):
            self.ins("STK", "POP")
            self.ins("CPY", "R0", f"R{r}")
        for r in temps:
            if r in self.free:
                self.free.remove(r)
        for v in spill:                          # changed by the arguments: read back
            self.ins("DATA", f"R{SCRATCH}", str(self.var_slot(v)))
            self.ins("STK", "GET", f"R{SCRATCH}")
            self.ins("CPY", "R0", f"R{self.var_regs[v]}")
        if keep_r0 and busy:
            self.ins("CPY", "R15", "R0")
        if node.ret_buf is not None:
            return Val("addr", addr=Addr("frame", off=node.ret_buf.offset))
        if node.ty.is_void or not want:
            return Val("void")
        return Val("r0")

    def gen_builtin(self, node):
        if node.name == "va_start":
            # the first variadic word: FP - F - 2 - V, with V at EBP - 2
            r = self.alloc(node)
            self.ins("DATA", f"R{SCRATCH}", "-2")
            self.ins("STK", "GET", f"R{SCRATCH}")
            self.ins("CPY", "R0", f"R{r}")
            self.load_fp()
            self.ins("SUB", "R0", f"R{r}")
            self.ins("ADD", "R0", f"#{-(self.fixed_words + 2)}")
            self.ins("CPY", "R0", f"R{r}")
            return Val("reg", reg=r)
        if node.name == "halt":
            self.ins("HALT")
            return Val("void")
        if node.name == "out":
            dev, value = node.args
            d, v = self.operands(dev, value)
            rd = self.reg_name(d)
            rv = self.reg_name(v)
            self.ins("COMM", "OUTADDR", rd)
            self.ins("COMM", "OUTDATA", rv)
            self.free_val(d)
            self.free_val(v)
            return Val("void")
        if node.name == "in":
            d = self.gen(node.args[0])
            rd = self.reg_name(d)
            r = self.alloc(node)
            self.ins("DATA", f"R{r}", "0")          # a device that isn't there reads 0
            self.ins("COMM", "INADDR", rd)
            self.ins("COMM", "INDATA", f"R{r}")
            self.free_val(d)
            return Val("reg", reg=r)
        raise self.error(node, f"internal error: unknown builtin {node.name}")


def generate(program, unit, source=None, unit_file=None):
    gen = CodeGen(program, unit, source)
    if unit_file:
        gen.unit_file = unit_file
    return gen.run()
