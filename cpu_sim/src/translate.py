"""Turns the program's code into Python functions, for CPU.run().

Decoding an instruction costs more than doing it, so run() decodes each
piece of code once: translate() makes a *block*, the code from one address
on, into one Python function that does what executing those instructions
one at a time does. A block goes on through conditional jumps (a taken one
leaves the block) and follows unconditional ones (RJMP, and a JMRB whose
address the block knows, like CALL's), up to a JMRB to an address only
known when it runs (RET's), HALT, MAX_LENGTH instructions or the end of
the ROM.

In the function the registers are local variables (written back to the
list on the way out), operands, addresses and jump targets are constants,
a register loaded with DATA stays a constant until it changes, and the
flags of an ALU instruction are only worked out where something sees
them: a jump that tests them, or a way out of the block. So

    CMP R12, #7 ; RJNF A, loop     becomes    if not ((r12 ^ 0x80000000) > 0x80000007):
                                                  flags = ...
                                                  return 0x1234, flags, esp, ebp, 2

A block function is

    block(regs, rom, ram, flags, esp, ebp, cpu) -> (iar, flags, esp, ebp, executed)

It raises Stop(iar, flags, esp, ebp, executed) at HALT, and at a stack wrap
when config.STOP_ON_STACK_WRAP stops the CPU. Only ROM code is translated:
the CPU can't write ROM, so a block stays right until the ROM is loaded or
changed from outside (CPU.forget_code()). Code in RAM is run one
instruction at a time.

selftest.py's test_run_matches_step runs random code through this and
through CPU.step(); keep the two in step when an instruction changes.
"""

import types

import alu as alu
import config as config
import isa as isa

MASK = config.WORD_MASK
ADDR_MASK = config.ADDR_MASK
RAM_BIT = config.RAM_BIT
BANK_MASK = config.BANK_MASK
STACK_MASK = config.STACK_MASK
INDEX_MASK = config.STACK_INDEX_MASK

MAX_LENGTH = 64             # instructions in a block at most
HOT = 50                    # jumps to an address before its code is translated
REDISPATCH = 1000           # blocks run outside dispatcher() before it is made again
                            # (then twice as many before the next time)

ONE_OPERAND = {0x4, 0x5, 0x6, 0xB, 0xC, 0xD, 0xE}  # SHL SHR NOT ++ -- NEG TEST: RA only for flag A


class Stop(Exception):
    """A block stopped the CPU: args are (iar, flags, esp, ebp, executed)."""


def options():
    """The TWEAKS a translation depends on: a block is made for one setting."""
    return (config.A_FLAG_SIGNED, config.SHR_ARITHMETIC, config.STOP_ON_STACK_WRAP,
            config.DIV_TRUNCATE, config.FLOAT_NOP_RESULT)


def _namespace(name):
    """Globals for generated code: a module's dict, as pypy3 treats a
    module's globals as constants (until one is assigned again) and looks up
    a plain dict's every time."""
    space = types.ModuleType(name).__dict__
    space.update(Stop=Stop, int_op=alu.int_op, float_op=alu.float_op)
    return space


# Blocks and dispatchers already made, shared by every CPU: the same code
# gives the same function (and pypy3 keeps what it compiled for it).
_made = {}
_dispatchers = {}
_LIMIT = 50_000


def translate(rom, start):
    """(function, length, items) for the ROM code at start, or None when
    there is no whole instruction there (an operand would be in RAM).
    items: what _scan() read, to check later that the ROM still holds it."""
    items = _scan(rom, start)
    if not items:
        return None
    key = (start, options(), tuple(items))
    made = _made.get(key)
    if made is None:
        if len(_made) >= _LIMIT:
            _made.clear()
        space = _namespace(f"block_{start:X}")
        exec(compile(_Writer(items).source(), f"<block 0x{start:07X}>", "exec"), space)
        made = _made[key] = (space["block"], len(items), key[2])
    return made


def still_there(rom, items):
    """Does the ROM still hold the words a block was made from?"""
    for pc, word, operand, _ in items:
        if rom[pc] != word or operand is not None and rom[pc + 1] != operand:
            return False
    return True


def dispatcher(code):
    """A function that runs the blocks in code ({address: translate()'s
    result}) one after the other for as long as the IAR is at one of them
    and the next one fits under the limit:

        dispatch(regs, rom, ram, flags, esp, ebp, cpu, iar, count, limit)
            -> (iar, flags, esp, ebp, count, stopped)

    It finds the block with a binary search written out as if/else on the
    address, and calls each block by its own name: then pypy3 sees one
    function at each call (and compiles it in), instead of one call that can
    be any block. stopped: a block raised Stop."""
    key = tuple(sorted((a, block[0]) for a, block in code.items()))
    made = _dispatchers.get(key)
    if made is not None:
        return made
    space = _namespace("dispatch")
    lines = ["def dispatch(regs, rom, ram, flags, esp, ebp, cpu, iar, count, limit):",
             "    try:",
             "        while True:"]

    def tree(keys, pad):
        if len(keys) <= 3:
            for k in keys:
                function, length, _ = code[k]
                name = f"b{k:X}"
                space[name] = function
                lines.extend([f"{pad}if iar == 0x{k:X}:",
                              f"{pad}    if count + {length} > limit:",
                              f"{pad}        break",
                              f"{pad}    iar, flags, esp, ebp, done = {name}(regs, rom, ram, flags, esp, ebp, cpu)",
                              f"{pad}    count += done",
                              f"{pad}    continue"])
            return
        middle = len(keys) // 2
        lines.append(f"{pad}if iar < 0x{keys[middle]:X}:")
        tree(keys[:middle], pad + "    ")
        lines.append(f"{pad}else:")
        tree(keys[middle:], pad + "    ")

    tree(sorted(code), " " * 12)
    lines += ["            break",
              "    except Stop as stop:",
              "        iar, flags, esp, ebp, done = stop.args",
              "        return iar, flags, esp, ebp, count + done, True",
              "    return iar, flags, esp, ebp, count, False"]
    exec(compile("\n".join(lines) + "\n", "<dispatch>", "exec"), space)
    if len(_dispatchers) >= 64:
        _dispatchers.clear()
    made = _dispatchers[key] = space["dispatch"]
    return made


# ------------------------------------------------------------------ scanning
def _scan(rom, start):
    """The instructions of the block at start, in the order they run:
    (address, word, operand or None, followed), followed = the address a jump
    goes on at inside the block (None: not followed)."""
    items = []
    seen = set()
    data = {}                       # register -> value from DATA just before (for JMRB)
    pc = start
    while len(items) < MAX_LENGTH and not pc & RAM_BIT and pc not in seen:
        word = rom[pc]
        nxt = pc + 1
        alu_op = word & 0x1000
        op = (word >> 8) & 0xF
        takes = bool(word & 0x4000) if alu_op else op in (0x3, 0x4, 0x5, 0x6)
        if takes and nxt & RAM_BIT:
            break                           # its operand would be the first RAM word
        operand = rom[nxt] if takes else None
        after = nxt + 1 if takes else nxt
        seen.add(pc)
        target = None
        if not alu_op and op == 0x4:                        # RJMP
            target = (nxt + operand) & ADDR_MASK
        elif not alu_op and op == 0xA and (word & 0xF) in data:  # JMRB to a known address
            target = data[word & 0xF] & ADDR_MASK
        if target is not None and not target & RAM_BIT:
            items.append((pc, word, operand, target))
            pc = target
            data = {}
            continue
        items.append((pc, word, operand, None))
        if not alu_op and op in (0x4, 0xA, 0xF):            # RJMP, JMRB, HALT: the end
            break
        data = {word & 0xF: operand} if not alu_op and op == 0x3 else {}
        pc = after
    if items and items[-1][3] is not None:
        items[-1] = items[-1][:3] + (None,)             # the block ends at that jump after all
    return items


def _flags_seen(items):
    """For each instruction: whether the flags it sets (an ALU instruction,
    CLF) are seen before others replace them: by a jump that tests them, or
    by a way out of the block."""
    stops = config.STOP_ON_STACK_WRAP
    seen = [False] * len(items)
    live = True                                 # the block's last way out
    for i in range(len(items) - 1, -1, -1):
        _, word, _, followed = items[i]
        op = (word >> 8) & 0xF
        if word & 0x1000 or op == 0x7:          # ALU, CLF
            seen[i] = live
            live = False
        elif op in (0x5, 0x6, 0xF):             # RJF, RJNF, HALT
            live = True
        elif op in (0x4, 0xA) and followed is None:     # a jump out
            live = True
        elif op == 0xB and stops and (word >> 4) & 7 in (0, 1, 2):   # PUSH POP CALL can stop
            live = True
    return seen


# ------------------------------------------------------------------- writing
def _hex(value):
    return f"0x{value:X}"


class _Flags:
    """The flags of the last ALU instruction, not worked out yet: a, b the
    two ALU inputs, value what N and Z come from, carry a condition for C
    (None: C is 0), zero a cheaper condition for Z (or None). All are
    expressions; refs are the registers whose local variables they read."""

    def __init__(self, a, b, value, carry, zero, refs):
        self.a, self.b, self.value, self.carry, self.zero = a, b, value, carry, zero
        self.refs = refs

    def above(self):
        if config.A_FLAG_SIGNED:
            return f"({self.a} ^ 0x80000000) > ({self.b} ^ 0x80000000)"
        return f"{self.a} > {self.b}"

    def bit(self, mask):
        """A condition for one flag."""
        if mask == 8:
            return self.carry or "False"
        if mask == 4:
            return self.above()
        if mask == 2:
            return f"{self.value} >> 31"
        return self.zero or f"{self.value} == 0"

    def nibble(self):
        parts = [f"(4 if {self.above()} else 0)", f"(({self.value} >> 30) & 2)",
                 f"({self.bit(1)})"]
        if self.carry:
            parts.insert(0, f"(8 if {self.carry} else 0)")
        return " | ".join(parts)


class _Writer:
    """The Python source of one block (see the module docstring)."""

    def __init__(self, items):
        self.items = items
        self.lines = ["def block(regs, rom, ram, flags, esp, ebp, cpu):"]
        self.val = [None] * 16      # per register: None (in regs), int (known) or "rN" (local)
        self.dirty = set()          # registers to write back
        self.flags = None           # _Flags waiting to be worked out
        self.const_flags = None     # or the flags as a number, when they are known
        self.temps = 0
        self.bus = False

    # ------------------------------------------------------------ helpers
    def emit(self, line, indent=1):
        self.lines.append("    " * indent + line)

    def temp(self, prefix):
        self.temps += 1
        return f"{prefix}{self.temps}"

    def known(self, r):
        v = self.val[r]
        return v if isinstance(v, int) else None

    def reg(self, r):
        """An expression for register r (loaded the first time)."""
        v = self.val[r]
        if v is None:
            self.emit(f"r{r} = regs[{r}]")
            v = self.val[r] = f"r{r}"
        return v if isinstance(v, str) else _hex(v)

    def set_reg(self, r, value):
        """Register r = value: an int, or an expression."""
        if self.flags is not None and r in self.flags.refs:
            self.settle_flags()             # they read r's local: work them out first
        if isinstance(value, int):
            self.val[r] = value & MASK
        else:
            self.emit(f"r{r} = {value}")
            self.val[r] = f"r{r}"
        self.dirty.add(r)

    def settle_flags(self):
        if self.flags is not None:
            self.emit(f"flags = {self.flags.nibble()}")
            self.flags = None

    def leave(self, target, done, indent=1, stop=False, r0=None):
        """Leave the block: flags and registers back, then return (or raise
        Stop). r0: what to write back as R0 instead of its local."""
        if self.flags is not None:
            self.emit(f"flags = {self.flags.nibble()}", indent)
        elif self.const_flags is not None:
            self.emit(f"flags = {self.const_flags}", indent)
        for r in sorted(self.dirty | ({0} if r0 else set())):
            v = r0 if r == 0 and r0 else self.val[r]
            self.emit(f"regs[{r}] = {v if isinstance(v, str) else _hex(v)}", indent)
        word = "raise Stop(" if stop else "return "
        self.emit(f"{word}{target}, flags, esp, ebp, {done}{')' if stop else ''}", indent)

    def condition(self, mask, any_on):
        """The condition that takes RJF (any_on) or RJNF: an expression, or
        True/False when it is known."""
        if self.const_flags is not None:
            on = self.const_flags & mask
            return on != 0 if any_on else on != mask
        bits = [m for m in (8, 4, 2, 1) if mask & m]
        if not bits:
            return False                    # no flags listed: never taken
        if self.flags is None:
            return f"flags & {mask}" if any_on else f"flags & {mask} != {mask}"
        tests = [f"({self.flags.bit(m)})" for m in bits]
        return " or ".join(tests) if any_on else "not (" + " and ".join(tests) + ")"

    def address(self, expr):
        """A 25-bit address: an int, or the name of a local holding it."""
        if isinstance(expr, int):
            return expr & ADDR_MASK
        name = self.temp("a")
        self.emit(f"{name} = ({expr}) & 0x{ADDR_MASK:X}")
        return name

    @staticmethod
    def load(addr):
        """An expression for the word at an address from address()."""
        if isinstance(addr, int):
            return f"ram[{_hex(addr & BANK_MASK)}]" if addr & RAM_BIT else f"rom[{_hex(addr)}]"
        return f"(ram[{addr} & 0x{BANK_MASK:X}] if {addr} & 0x{RAM_BIT:X} else rom[{addr}])"

    def store(self, addr, value):
        """Write value at an address from address(), if it is in RAM."""
        if isinstance(addr, int):
            if addr & RAM_BIT:
                self.emit(f"ram[{_hex(addr & BANK_MASK)}] = {value}")
            return
        self.emit(f"if {addr} & 0x{RAM_BIT:X}:")
        self.emit(f"ram[{addr} & 0x{BANK_MASK:X}] = {value}", 2)

    def operand(self, r):
        """Register r as an int when known, else as an expression."""
        k = self.known(r)
        return k if k is not None else self.reg(r)

    def plus(self, a, b):
        ka, kb = self.known(a), self.known(b)
        if ka is not None and kb is not None:
            return ka + kb
        return f"{self.reg(a)} + {self.reg(b)}"

    # ------------------------------------------------------------- source
    def source(self):
        seen = _flags_seen(self.items)
        done = 0
        last = len(self.items) - 1
        for i, (pc, word, operand, followed) in enumerate(self.items):
            done += 1
            nxt = (pc + (1 if operand is None else 2)) & ADDR_MASK
            op = (word >> 8) & 0xF
            ra, rb = (word >> 4) & 0xF, word & 0xF
            if word & 0x1000:
                self.alu(word, operand, seen[i])
            elif op == 0x4:                                 # RJMP
                if followed is None:
                    self.leave(_hex((pc + 1 + operand) & ADDR_MASK), done)
                    break
                continue
            elif op in (0x5, 0x6):                          # RJF, RJNF
                target = _hex((pc + 1 + operand) & ADDR_MASK)
                cond = self.condition(rb, op == 0x5)
                if cond is True:
                    self.leave(target, done)
                    break
                if cond is not False:
                    self.emit(f"if {cond}:")
                    self.leave(target, done, indent=2)
            elif op == 0xA:                                 # JMRB
                k = self.known(rb)
                if followed is not None and k is not None and k & ADDR_MASK == followed:
                    continue
                target = _hex(k & ADDR_MASK) if k is not None else f"{self.reg(rb)} & 0x{ADDR_MASK:X}"
                self.leave(target, done)
                break
            elif op == 0xF:                                 # HALT
                self.emit("cpu.halted = True")
                self.leave(_hex(nxt), done, stop=True)
                break
            elif op == 0x7:                                 # CLF
                self.flags, self.const_flags = None, 0
            else:
                self.system(op, ra, rb, pc, operand, done)
            if i == last:
                self.leave(_hex(nxt), done)
        return "\n".join(self.lines) + "\n"

    def system(self, op, ra, rb, pc, operand, done):
        if op == 0x3:                                       # DATA
            self.set_reg(rb, operand)
        elif op == 0xE:                                     # CPY
            self.set_reg(rb, self.operand(ra))
        elif op == 0x1:                                     # LD
            self.set_reg(rb, self.load(self.address(self.operand(ra))))
        elif op == 0xC:                                     # ALD
            self.set_reg(0, self.load(self.address(self.plus(ra, rb))))
        elif op == 0x2:                                     # ST
            self.store(self.address(self.operand(ra)), self.reg(rb))
        elif op == 0xD:                                     # AST
            self.store(self.address(self.plus(ra, rb)), self.reg(0))
        elif op == 0xB:                                     # STK
            self.stack(ra & 7, rb, (pc + 1) & ADDR_MASK, done)
        elif op == 0x8:                                     # COMM
            if not self.bus:
                self.emit("bus = cpu.bus")
                self.bus = True
            mode = ra & 3
            if mode == 2:
                self.emit(f"bus.out_data({self.reg(rb)})")
            elif mode == 3:
                self.emit(f"bus.out_address({self.reg(rb)})")
            elif mode == 1:
                self.emit(f"bus.in_address({self.reg(rb)})")
            else:                                           # INDATA: nothing there keeps RB
                old = self.reg(rb)
                got = self.temp("v")
                self.emit(f"{got} = bus.in_data()")
                self.set_reg(rb, f"{old} if {got} is None else {got} & 0xFFFFFFFF")
        elif op == 0x9:                                     # ADDR
            self.set_reg(rb, (pc + 1) & ADDR_MASK)
        # 0x0 NOP

    def stack(self, kind, rb, nxt, done):
        stops = config.STOP_ON_STACK_WRAP
        if kind in (0, 2):                                  # PUSH, CALL (the frame only)
            if kind == 0:
                self.emit(f"ram[esp] = {self.reg(0)}")
            else:
                self.emit("ram[esp] = ebp")
                self.emit("ebp = esp")
            self.emit("esp += 1")
            self.emit(f"if esp > 0x{STACK_MASK:X}:")
            self.emit("esp = cpu._bump(esp - 1, 1)", 2)
            if stops:
                self.emit("if cpu.stopped:", 2)
                self.leave(_hex(nxt), done, indent=3, stop=True)
        elif kind == 1:                                     # POP
            self.emit("esp -= 1")
            self.emit("if esp < 0:")
            self.emit("esp = cpu._bump(esp + 1, -1)", 2)
            if stops:                                       # R0 is popped, then it stops
                self.emit("if cpu.stopped:", 2)
                self.leave(_hex(nxt), done, indent=3, stop=True, r0="ram[esp]")
            self.set_reg(0, "ram[esp]")
        elif kind == 3:                                     # RET
            self.emit("esp = ebp")
            self.emit(f"ebp = ram[ebp] & 0x{STACK_MASK:X}")
        elif kind == 4:                                     # SET
            self.emit(f"ram[{self.stack_index(rb)}] = {self.reg(0)}")
        elif kind == 5:                                     # GET
            self.set_reg(0, f"ram[{self.stack_index(rb)}]")

    def stack_index(self, rb):
        """EBP + RB, wrapping across the RAM."""
        k = self.known(rb)
        if k is not None:
            return f"(ebp + 0x{k & INDEX_MASK:X}) & 0x{INDEX_MASK:X}"
        return f"(ebp + {self.reg(rb)}) & 0x{INDEX_MASK:X}"

    # ---------------------------------------------------------------- ALU
    def alu(self, word, operand, seen):
        op = (word >> 8) & 0xF
        ra, rb = (word >> 4) & 0xF, word & 0xF
        is_float = word & 0x2000
        name = (isa.FLOAT_OPS if is_float else isa.INT_OPS)[op]
        ka = self.known(ra)
        kb = operand & MASK if operand is not None else self.known(rb)
        self.flags = None                                   # this instruction replaces them
        self.const_flags = None
        if ka is not None and kb is not None:               # both known: work it out now
            value, flags = (alu.float_op if is_float else alu.int_op)(name, ka, kb)
            self.const_flags = flags
            self.set_reg(0, value)
            return
        b = _hex(kb) if kb is not None else self.reg(rb)
        if is_float or op in (0x3, 0xA):                    # floats, DIV, MOD: alu.py
            a = _hex(ka) if ka is not None else self.reg(ra)
            fn = "float_op" if is_float else "int_op"
            self.emit(f"r0, flags = {fn}({name!r}, {a}, {b})" if seen
                      else f"r0 = {fn}({name!r}, {a}, {b})[0]")
            self.val[0] = "r0"
            self.dirty.add(0)
            return
        uses_a = seen or op not in ONE_OPERAND
        a = (_hex(ka) if ka is not None else self.reg(ra)) if uses_a else None
        refs = set()
        if seen:                    # the flags read a and b after R0 has changed: keep them
            if ka is None:
                refs.add(ra)
            if kb is None:
                refs.add(rb)
            if 0 in refs:
                keep = self.temp("t")
                self.emit(f"{keep} = r0")
                a = keep if ra == 0 and ka is None else a
                b = keep if rb == 0 and kb is None else b
                refs.discard(0)
        carry = None
        if op == 0xF:                                       # CMP: R0 = 0, C = 0
            self.set_reg(0, 0)
            if seen:
                self.flags = _Flags(a, b, f"(({a} - {b}) & 0xFFFFFFFF)", None,
                                    f"{a} == {b}", refs)
            return
        if op == 0x0:                                       # ADD: C = carry out
            result, carry = f"({a} + {b}) & 0xFFFFFFFF", f"r0 < {a}"
        elif op == 0x1:                                     # SUB: C = borrow
            result, carry = f"({a} - {b}) & 0xFFFFFFFF", f"{a} < {b}"
        elif op == 0x2:                                     # MULT (low 32 bits)
            result = f"({a} * {b}) & 0xFFFFFFFF"
        elif op == 0x4:                                     # SHL: C = the bit out
            result, carry = f"({b} << 1) & 0xFFFFFFFF", f"{b} >> 31"
        elif op == 0x5:                                     # SHR: C = the bit out
            result, carry = f"{b} >> 1", f"{b} & 1"
            if config.SHR_ARITHMETIC:
                result = f"({b} >> 1) | ({b} & 0x80000000)"
        elif op == 0x6:                                     # NOT
            result = f"{b} ^ 0xFFFFFFFF"
        elif op == 0x7:
            result = f"{a} & {b}"
        elif op == 0x8:
            result = f"{a} | {b}"
        elif op == 0x9:
            result = f"{a} ^ {b}"
        elif op == 0xB:                                     # ++: C when it wraps to 0
            result, carry = f"({b} + 1) & 0xFFFFFFFF", "r0 == 0"
        elif op == 0xC:                                     # --
            result = f"({b} - 1) & 0xFFFFFFFF"
        elif op == 0xD:                                     # NEG
            result = f"-{b} & 0xFFFFFFFF"
        else:                                               # TEST
            result = b
        self.set_reg(0, result)
        if seen:
            refs.add(0)                                     # value (and some carries) read r0
            self.flags = _Flags(a, b, "r0", carry, None, refs)
