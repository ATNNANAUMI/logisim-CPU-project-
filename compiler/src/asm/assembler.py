"""Assembler: one .asm file in, one object file out.

Pass 1 reads every line, works out how many words it takes and where each
label lands. Pass 2 builds the words.

Addresses depend on where the linker puts this file, so a word that holds a
label's address is left as 0 plus a relocation, and the linker fills it in.
Jumps to labels in the same file are finished here: the distance between
two places in one file doesn't change when the file moves.
"""

from dataclasses import dataclass

import encoding as enc
from errors import AsmError, AsmErrors
from objfile import ObjectFile, Reloc
from parser import (MASK, NAME_RE, is_register, parse_expression,
                    parse_register, parse_string, split_operands,
                    split_statement, split_sub_operation, strip_comment)

INT_MIN = -(1 << 31)
ROM_SIZE = 0x10000


@dataclass
class Label:
    section: str      # "rom" or "ram"
    offset: int       # position inside this file's part of that section
    line: int


@dataclass
class Statement:
    """A line that puts words in ROM, saved in pass 1 for pass 2."""
    line: int
    op: str               # mnemonic (upper case) or directive (lower case)
    rest: str             # operand text
    offset: int           # where its first word goes in this file's ROM part
    size: int             # how many words
    data: list | None = None     # words already known in pass 1 (.string, .space)


def assemble(text, source="<input>"):
    """Assemble source text. Returns (ObjectFile, warnings); raises AsmErrors."""
    return Assembler(text, source).run()


class Assembler:
    def __init__(self, text, source):
        self.text = text
        self.source = source
        self.section = "rom"
        self.sizes = {"rom": 0, "ram": 0}
        self.labels = {}       # name -> Label
        self.constants = {}    # name -> (value, is_float)
        self.globals = {}      # name -> line of its .global
        self.externs = {}      # name -> line of its .extern
        self.statements = []
        self.rom = []
        self.relocs = []
        self.errors = []
        self.warnings = []

    def run(self):
        self.pass1()
        self.check_symbols()
        self.pass2()
        if self.sizes["rom"] > ROM_SIZE:
            self.errors.append(AsmError(
                f"this file needs {self.sizes['rom']} words of ROM, only {ROM_SIZE} fit",
                self.source))
        if self.errors:
            self.errors.sort(key=lambda e: e.line or 0)
            raise AsmErrors(self.errors)
        obj = ObjectFile(
            source=self.source,
            rom=self.rom,
            ram_size=self.sizes["ram"],
            labels={name: (lab.section, lab.offset) for name, lab in self.labels.items()},
            globals=sorted(self.globals),
            externs=sorted(self.externs),
            relocs=self.relocs,
        )
        return obj, self.warnings

    def error(self, err, line):
        err.file = self.source
        err.line = err.line or line
        self.errors.append(err)

    def warn(self, message, line):
        self.warnings.append(AsmError(message, self.source, line))

    # ------------------------------------------------------------ pass 1

    def pass1(self):
        for line, raw in enumerate(self.text.splitlines(), start=1):
            try:
                label, op, rest = split_statement(strip_comment(raw))
                if label is not None:
                    self.define_label(label, line)
                if op is None:
                    continue
                if op.startswith("."):
                    self.directive(op.lower(), rest, line)
                else:
                    self.instruction(op.upper(), rest, line)
            except AsmError as err:
                self.error(err, line)

    def check_name(self, name, what):
        if not NAME_RE.fullmatch(name):
            raise AsmError(f"'{name}' is not a valid {what} name")
        if name.startswith("__"):
            raise AsmError(f"'{name}': names starting with '__' are reserved")
        if is_register(name):
            raise AsmError(f"'{name}' is a register, it can't be a {what} name")
        if name.upper() in enc.MNEMONICS:
            raise AsmError(f"'{name}' is an instruction, it can't be a {what} name")

    def define_label(self, name, line):
        self.check_name(name, "label")
        if name in self.labels:
            raise AsmError(f"label '{name}' is already defined on line "
                           f"{self.labels[name].line}")
        if name in self.constants:
            raise AsmError(f"'{name}' is already a constant (.equ)")
        self.labels[name] = Label(self.section, self.sizes[self.section], line)

    def add_statement(self, line, op, rest, size, data=None):
        self.statements.append(
            Statement(line, op, rest, self.sizes["rom"], size, data))
        self.sizes["rom"] += size

    def instruction(self, op, rest, line):
        if op not in enc.MNEMONICS:
            raise AsmError(f"unknown instruction '{op}'")
        if self.section != "rom":
            raise AsmError("instructions can't go in RAM (RAM holds no code); "
                           "put .rom before them")
        self.add_statement(line, op, rest, self.instruction_size(op, rest))

    def instruction_size(self, op, rest):
        if op in enc.PSEUDO_OPS:
            return enc.PSEUDO_OPS[op]
        if op in enc.SYSTEM_OPS:
            return 2 if enc.SYSTEM_OPS[op][1] in enc.TWO_WORD_SHAPES else 1
        if enc.ALU_OPS[op][2] == "alu2":
            args = split_operands(rest)
            return 2 if len(args) == 2 and args[1].startswith("#") else 1
        return 1

    def rom_only(self, name):
        if self.section != "rom":
            raise AsmError(f"{name} can't be used in RAM: RAM holds no starting "
                           "values (use .space to reserve room)")

    def directive(self, name, rest, line):
        if name in (".rom", ".ram"):
            if rest:
                raise AsmError(f"{name} takes no operands")
            self.section = name[1:]

        elif name in (".global", ".extern"):
            names = split_operands(rest)
            if not names:
                raise AsmError(f"{name} needs at least one label name")
            table = self.globals if name == ".global" else self.externs
            for n in names:
                self.check_name(n, "label")
                table.setdefault(n, line)

        elif name == ".equ":
            args = split_operands(rest)
            if len(args) != 2:
                raise AsmError("expected .equ NAME, value")
            const = args[0]
            self.check_name(const, "constant")
            if const in self.constants:
                raise AsmError(f"constant '{const}' is already defined")
            if const in self.labels or const in self.externs:
                raise AsmError(f"'{const}' is already a label")
            self.constants[const] = self.constant(args[1])

        elif name == ".word":
            self.rom_only(name)
            args = split_operands(rest)
            if not args:
                raise AsmError(".word needs at least one value")
            self.add_statement(line, name, rest, len(args))

        elif name == ".string":
            self.rom_only(name)
            args = split_operands(rest)
            if len(args) != 1:
                raise AsmError('expected .string "text"')
            codes = parse_string(args[0]) + [0]
            self.add_statement(line, name, rest, len(codes), codes)

        elif name == ".space":
            args = split_operands(rest)
            if len(args) != 1:
                raise AsmError("expected .space count")
            count, is_float = self.constant(args[0])
            if is_float or count < 0:
                raise AsmError(".space needs a whole number of words, 0 or more")
            if self.section == "rom":
                self.add_statement(line, name, rest, count, [0] * count)
            else:
                self.sizes["ram"] += count

        else:
            raise AsmError(f"unknown directive '{name}'")

    def constant(self, text):
        """A value that must be known right now (for .equ and .space)."""
        number, label, is_float = self.evaluate(text, labels_allowed=False)
        return number, is_float

    def check_symbols(self):
        """Check .global and .extern once every label is known."""
        for name, line in self.globals.items():
            if name in self.externs:
                self.error(AsmError(f"'{name}' can't be both .global and .extern"), line)
            elif name in self.constants:
                self.error(AsmError(f"'{name}' is a constant; only labels can be .global"), line)
            elif name not in self.labels:
                self.error(AsmError(f"'{name}' is listed in .global but never defined"), line)
        for name, line in self.externs.items():
            if name in self.labels:
                self.error(AsmError(
                    f"'{name}' is .extern but is also defined here "
                    f"(line {self.labels[name].line})"), line)
            elif name in self.constants:
                self.error(AsmError(f"'{name}' is .extern but is also a constant"), line)

    # ------------------------------------------------------------ values

    def evaluate(self, text, labels_allowed=True):
        """Work out a value. Returns (number, label or None, is_float).

        With a label, number is what gets added to the label's address.
        """
        expr = parse_expression(text)
        if expr.float_bits is not None:
            return expr.float_bits, None, True
        number = expr.number
        label = None
        for sign, name in expr.names:
            if name in self.constants:
                value, is_float = self.constants[name]
                if is_float:
                    if expr.terms > 1:
                        raise AsmError(f"'{name}' is a float and can't be added to "
                                       "or subtracted from other values")
                    return (value ^ 0x80000000 if sign < 0 else value), None, True
                number += sign * value
            elif name in self.labels or name in self.externs:
                if not labels_allowed:
                    raise AsmError(f"'{name}' is a label; only constants (.equ) "
                                   "can be used here")
                if label is not None:
                    raise AsmError("a value can use only one label")
                if sign < 0:
                    raise AsmError(f"label '{name}' can only be added, not subtracted")
                label = name
            elif not labels_allowed:
                raise AsmError(f"unknown name '{name}' (constants used by .equ "
                               "and .space must be defined above them)")
            else:
                raise AsmError(f"unknown name '{name}' (a typo, or a missing .extern?)")
        if label is None and not INT_MIN <= number <= MASK:
            raise AsmError(f"'{text.strip()}' doesn't fit in 32 bits")
        return number, label, False

    def put_value(self, text, words, relocs, line):
        """Append a value word. Returns (number, label, is_float)."""
        number, label, is_float = self.evaluate(text)
        at = len(words)
        if label is None:
            words.append(number & MASK)
        elif label in self.labels:
            lab = self.labels[label]
            words.append(0)
            relocs.append(Reloc(at, "abs", None, lab.section, lab.offset + number, line))
        else:
            words.append(0)
            relocs.append(Reloc(at, "abs", label, None, number, line))
        return number, label, is_float

    def put_jump(self, text, words, relocs, stmt):
        """Append a relative jump offset: target - address of this word."""
        number, label, _ = self.evaluate(text)
        if label is None:
            raise AsmError("a jump target must be a label")
        at = len(words)
        if label in self.labels:
            lab = self.labels[label]
            if lab.section != "rom":
                raise AsmError(f"can't jump to '{label}': it is a RAM label")
            words.append((lab.offset + number - (stmt.offset + at)) & MASK)
        else:
            words.append(0)
            relocs.append(Reloc(at, "rel", label, None, number, stmt.line))

    # ------------------------------------------------------------ pass 2

    def pass2(self):
        for stmt in self.statements:
            try:
                words, relocs = self.encode(stmt)
                if len(words) != stmt.size:
                    raise AsmError(f"internal error: expected {stmt.size} words, "
                                   f"made {len(words)}")
            except AsmError as err:
                self.error(err, stmt.line)
                words, relocs = [0] * stmt.size, []
            for r in relocs:
                r.at += stmt.offset
                self.relocs.append(r)
            self.rom.extend(words)

    def encode(self, stmt):
        """Build one statement's words. Reloc positions count from its start."""
        op, line = stmt.op, stmt.line
        words, relocs = [], []

        if stmt.data is not None:                       # .string, .space
            return list(stmt.data), relocs

        if op == ".word":
            for text in split_operands(stmt.rest):
                self.put_value(text, words, relocs, line)
            return words, relocs

        if op == "CALL":
            args = split_operands(stmt.rest)
            if len(args) != 1:
                raise AsmError("expected CALL label")
            number, label, _ = self.evaluate(args[0])
            if label is None:
                raise AsmError("CALL needs a label to call")
            if label in self.labels and self.labels[label].section != "rom":
                raise AsmError(f"can't call '{label}': it is a RAM label")
            words.append(enc.sys_word("DATA", rb=0))       # DATA R0, <return>
            words.append(0)
            relocs.append(Reloc(1, "abs", None, "rom", stmt.offset + stmt.size, line))
            words.append(enc.stk_word("PUSH"))              # STK PUSH
            words.append(enc.stk_word("CALL"))              # STK CALL
            words.append(enc.sys_word("DATA", rb=0))       # DATA R0, target
            self.put_value(args[0], words, relocs, line)
            words.append(enc.sys_word("JMRB", rb=0))       # JMRB R0
            return words, relocs

        if op == "RET":
            if stmt.rest:
                raise AsmError("RET takes no operands")
            words += [
                enc.sys_word("CPY", 0, 15),     # CPY R0, R15   save return value
                enc.stk_word("RET"),            # STK RET       drop the frame
                enc.stk_word("POP"),            # STK POP       R0 = return address
                enc.sys_word("CPY", 0, 14),     # CPY R0, R14
                enc.sys_word("CPY", 15, 0),     # CPY R15, R0   R0 = return value
                enc.sys_word("JMRB", rb=14),    # JMRB R14
            ]
            return words, relocs

        if op in enc.SYSTEM_OPS:
            return self.encode_system(stmt)
        return self.encode_alu(stmt)

    def expect(self, op, shape, args, count):
        if len(args) != count:
            raise AsmError("expected " + enc.USAGE[shape].format(op=op))

    def encode_system(self, stmt):
        op, line = stmt.op, stmt.line
        opcode, shape = enc.SYSTEM_OPS[op]
        words, relocs = [], []

        if shape in ("comm", "stk"):
            sub, args = split_sub_operation(stmt.rest)
            if shape == "comm":
                if sub not in enc.COMM_OPS:
                    raise AsmError("expected " + enc.USAGE[shape].format(op=op))
                if len(args) != 1:
                    raise AsmError(f"expected COMM {sub}, RB")
                words.append(enc.word(enc.SYSTEM, opcode, enc.COMM_OPS[sub], parse_register(args[0])))
            else:
                if sub not in enc.STK_OPS:
                    raise AsmError("expected " + enc.USAGE[shape].format(op=op))
                code, takes_register = enc.STK_OPS[sub]
                if takes_register:
                    if len(args) != 1:
                        raise AsmError(f"expected STK {sub}, RB")
                    words.append(enc.word(enc.SYSTEM, opcode, code, parse_register(args[0])))
                else:
                    if args:
                        raise AsmError(f"STK {sub} takes no register")
                    words.append(enc.word(enc.SYSTEM, opcode, code, 0))
            return words, relocs

        args = split_operands(stmt.rest)
        if shape == "none":
            self.expect(op, shape, args, 0)
            words.append(enc.word(enc.SYSTEM, opcode))
        elif shape == "ra_rb":
            self.expect(op, shape, args, 2)
            words.append(enc.word(enc.SYSTEM, opcode,
                                  parse_register(args[0]), parse_register(args[1])))
        elif shape == "rb":
            self.expect(op, shape, args, 1)
            words.append(enc.word(enc.SYSTEM, opcode, 0, parse_register(args[0])))
        elif shape == "rb_value":
            self.expect(op, shape, args, 2)
            if args[1].startswith("#"):
                raise AsmError(f"{op} takes a plain value, without '#'")
            words.append(enc.word(enc.SYSTEM, opcode, 0, parse_register(args[0])))
            self.put_value(args[1], words, relocs, line)
        elif shape == "jump":
            self.expect(op, shape, args, 1)
            words.append(enc.word(enc.SYSTEM, opcode))
            self.put_jump(args[0], words, relocs, stmt)
        elif shape == "flagjump":
            self.expect(op, shape, args, 2)
            words.append(enc.word(enc.SYSTEM, opcode, 0, self.parse_flags(args[0])))
            self.put_jump(args[1], words, relocs, stmt)
        return words, relocs

    def parse_flags(self, text):
        letters = text.strip().upper()
        if not letters or any(ch not in enc.FLAGS for ch in letters):
            raise AsmError(f"'{text.strip()}' is not a flag list: use letters from "
                           "C A N Z, like Z or NZ")
        nibble = 0
        for ch in letters:
            nibble |= enc.FLAGS[ch]
        return nibble

    def encode_alu(self, stmt):
        op, line = stmt.op, stmt.line
        prefix, opcode, shape = enc.ALU_OPS[op]
        args = split_operands(stmt.rest)
        words, relocs = [], []

        if shape == "alu1":
            if len(args) == 1 and args[0].startswith("#"):
                raise AsmError(f"{op} takes a register, not an immediate")
            self.expect(op, shape, args, 1)
            words.append(enc.word(prefix, opcode, 0, parse_register(args[0])))
            return words, relocs

        self.expect(op, shape, args, 2)
        ra = parse_register(args[0])
        if not args[1].startswith("#"):
            words.append(enc.word(prefix, opcode, ra, parse_register(args[1])))
            return words, relocs

        words.append(enc.word(prefix | enc.IMMEDIATE, opcode, ra, 0))
        number, label, is_float = self.put_value(args[1][1:], words, relocs, line)
        if label is None:
            if prefix == enc.INT_ALU and is_float:
                self.warn(f"float value in {op}: its bit pattern is used, not the "
                          "number (did you mean the F version?)", line)
            elif prefix == enc.FLOAT_ALU and not is_float and number != 0:
                self.warn(f"whole number in {op}: it is used as raw float bits; "
                          f"write {number}.0 for the number", line)
        return words, relocs
