"""Turns the program's code into Python functions, for CPU.run().

Decoding an instruction costs more than doing it, so run() decodes code
that runs often once: translate() makes a *block*, the code from one
address on, into one Python function that does what executing those
instructions one at a time does. A block goes on through conditional jumps
(a taken one leaves the block) and follows unconditional ones (RJMP, and a
JMRB whose address the block knows, like CALL's), up to a JMRB to an
address only known when it runs (RET's), HALT, MAX_LENGTH instructions or
the end of its bank.

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

It raises Stop(iar, flags, esp, ebp, executed) at HALT, at a stack wrap
when config.STOP_ON_STACK_WRAP stops the CPU, and (a RAM block, with no
stop) after a store over translated RAM code. The CPU can't write ROM, so a
ROM block stays right until the ROM is changed from outside; RAM code can
change under its blocks, so the CPU keeps a map of the RAM words they were
made from, which every RAM store checks (CPU._code_written() drops them).
dispatcher() makes the loop that runs blocks one after the other.

selftest.py's test_translated_code_matches_step runs random code through
this and through CPU.step(); keep them in step when an instruction changes.
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
    space.update(Stop=Stop, div=alu.div, mod=alu.mod, to_float=alu.bits_to_float,
                 to_bits=alu.float_to_bits, fdiv=alu._float_divide,
                 float_to_int=alu._float_to_int)
    return space


# Blocks and dispatchers already made, shared by every CPU: the same code
# gives the same function (and pypy3 keeps what it compiled for it).
_made = {}
_dispatchers = {}
_LIMIT = 50_000


def translate(rom, ram, start, guard=True):
    """(function, length, items) for the code at start, or None when there
    is no whole instruction there (an operand would be in the other bank).
    items: what _scan() read, to check later that memory still holds it
    (words(items) are the addresses). guard: check RAM stores against
    translated RAM code (needed once there is any; RAM blocks always do)."""
    items = _scan(rom, ram, start)
    if not items:
        return None
    guard = guard or bool(start & RAM_BIT)
    key = (start, options(), guard, tuple(items))
    made = _made.get(key)
    if made is None:
        if len(_made) >= _LIMIT:
            _made.clear()
        space = _namespace(f"block_{start:X}")
        exec(compile(_Writer(items, guard).source(), f"<block 0x{start:07X}>", "exec"), space)
        made = _made[key] = (space["block"], len(items), key[3])
    return made


def words(items):
    """The addresses of the words a block was made from."""
    for pc, _, operand, _ in items:
        yield pc
        if operand is not None:
            yield (pc + 1) & ADDR_MASK


def still_there(rom, ram, items):
    """Does memory still hold the words a block was made from?"""
    for pc, word, operand, _ in items:
        bank, at = (ram, pc & BANK_MASK) if pc & RAM_BIT else (rom, pc)
        if bank[at] != word or operand is not None and bank[at + 1] != operand:
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
def _scan(rom, ram, start):
    """The instructions of the block at start, in the order they run:
    (address, word, operand or None, followed), followed = the address a jump
    goes on at inside the block (None: not followed). A block stays in the
    bank (ROM or RAM) it starts in."""
    items = []
    seen = set()
    data = {}                       # register -> value from DATA just before (for JMRB)
    bank = start & RAM_BIT
    words = ram if bank else rom
    pc = start
    while len(items) < MAX_LENGTH and pc & RAM_BIT == bank and pc not in seen:
        word = words[pc & BANK_MASK]
        nxt = (pc + 1) & ADDR_MASK
        alu_op = word & 0x1000
        op = (word >> 8) & 0xF
        takes = bool(word & 0x4000) if alu_op else op in (0x3, 0x4, 0x5, 0x6)
        if takes and nxt & RAM_BIT != bank:
            break                           # its operand would be in the other bank
        operand = words[nxt & BANK_MASK] if takes else None
        after = (nxt + 1) & ADDR_MASK if takes else nxt
        seen.add(pc)
        target = None
        if not alu_op and op == 0x4:                        # RJMP
            target = (nxt + operand) & ADDR_MASK
        elif not alu_op and op == 0xA and (word & 0xF) in data:  # JMRB to a known address
            target = data[word & 0xF] & ADDR_MASK
        if target is not None and target & RAM_BIT == bank:
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
    by a way out of the block (in RAM, a store can be one)."""
    stores_leave = bool(items[0][0] & RAM_BIT)
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
        elif stores_leave and (op in (0x2, 0xD) or op == 0xB and (word >> 4) & 7 in (0, 2, 4)):
            live = True                         # ST AST PUSH CALL SET: may leave (rewritten code)
        elif op == 0xB and stops and (word >> 4) & 7 == 1:   # POP can stop
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

    def __init__(self, items, guard=True):
        self.items = items
        self.guard = guard          # check RAM stores against translated RAM code
        self.lines = ["def block(regs, rom, ram, flags, esp, ebp, cpu):"]
        self.val = [None] * 16      # per register: None (in regs), int (known) or "rN" (local)
        self.dirty = set()          # registers to write back
        self.flags = None           # _Flags waiting to be worked out
        self.const_flags = None     # or the flags as a number, when they are known
        self.temps = 0
        self.bus = False
        self.rc = False             # rc (cpu._ram_code) loaded
        self.here = None            # (address after, instructions done) of the instruction

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
                self.ram_store(_hex(addr & BANK_MASK), value, 1)
            return
        self.code_map()
        self.emit(f"if {addr} & 0x{RAM_BIT:X}:")
        self.ram_store(f"{addr} & 0x{BANK_MASK:X}", value, 2)

    def code_map(self):
        """rc = which RAM words translated code was made from (a block with
        guard only runs while there is that map)."""
        if self.guard and not self.rc:
            self.emit("rc = cpu._ram_code")
            self.rc = True

    def ram_store(self, offset, value, indent, written=None):
        """ram[offset] = value; then, if translated code was made from that
        word, drop it and leave the block (after this instruction).
        written: the offset to check, when the store comes before the end
        of the instruction (PUSH, CALL: the caller checks)."""
        self.code_map()
        self.emit(f"ram[{offset}] = {value}", indent)
        if written is None:
            self.rewritten(offset, indent)

    def rewritten(self, offset, indent):
        """The store went to a word translated RAM code was made from: drop
        that code. A block in RAM then leaves (it may be some of that code,
        and so may the RAM dispatcher that called it); one in ROM goes on."""
        if not self.guard:
            return
        self.emit(f"if rc[{offset}]:", indent)
        self.emit(f"cpu._code_written({offset})", indent + 1)
        if self.items[0][0] & RAM_BIT:
            nxt, done = self.here
            self.leave(_hex(nxt), done, indent=indent + 1, stop=True)

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
            self.here = (nxt, done)
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
            slot = self.temp("s")
            if self.guard:
                self.emit(f"{slot} = esp")
            if kind == 0:
                self.ram_store("esp", self.reg(0), 1, written=slot)
            else:
                self.ram_store("esp", "ebp", 1, written=slot)
                self.emit("ebp = esp")
            self.emit("esp += 1")
            self.emit(f"if esp > 0x{STACK_MASK:X}:")
            self.emit("esp = cpu._bump(esp - 1, 1)", 2)
            if stops:
                self.emit("if cpu.stopped:", 2)
                self.leave(_hex(nxt), done, indent=3, stop=True)
            self.rewritten(slot, 1)
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
            index = self.stack_index(rb)
            if self.guard:
                slot = self.temp("s")
                self.emit(f"{slot} = {index}")
                index = slot
            self.ram_store(index, self.reg(0), 1)
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
        if is_float:
            self.float_alu(op, ka, ra, b, seen)
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
        elif op == 0x3:                                     # DIV, MOD: alu.py's
            result = f"div({a}, {b})"
        elif op == 0xA:
            result = f"mod({a}, {b})"
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

    def float_alu(self, op, ka, ra, b, seen):
        """The float group, as alu.float_op() does it: inputs and results
        through float32, A = RA > RB as floats, N and Z from the result (as
        a float, so -0.0 is zero; an integer for INT), C = 0."""
        a = _hex(ka) if ka is not None else (self.reg(ra) if seen or op in (0, 1, 2, 3, 0xF) else None)
        fa = fb = None
        if a is not None:
            fa = self.temp("f")
            self.emit(f"{fa} = to_float({a})")
        if seen or op in (0, 1, 2, 3, 4, 7, 0xD, 0xF):
            fb = self.temp("f")
            self.emit(f"{fb} = to_float({b})")
        above = f"(4 if {fa} > {fb} else 0)" if seen else ""
        if op == 0x7:                                       # INT: float -> int
            self.set_reg(0, f"float_to_int({fb})")
            if seen:
                self.emit(f"flags = {above} | ((r0 >> 30) & 2) | (r0 == 0)")
            return
        if op in (0x5, 0x8, 0x9, 0xA, 0xB, 0xC, 0xE):        # no result: config.FLOAT_NOP_RESULT
            value = config.FLOAT_NOP_RESULT & MASK
            self.set_reg(0, value)
            if seen:
                self.emit(f"flags = {above} | {2 if value & 0x80000000 else 0} | {int(value == 0)}")
            return
        result = {0x0: f"{fa} + {fb}", 0x1: f"{fa} - {fb}", 0x2: f"{fa} * {fb}",
                  0x3: f"fdiv({fa}, {fb})", 0x4: f"{fb} * 2", 0xD: f"-{fb}", 0xF: f"{fa} - {fb}",
                  0x6: f"float(({b} ^ 0x80000000) - 0x80000000)"}[op]
        if op == 0xF:                                       # CMP: flags from RA - RB, R0 = 0
            value = self.temp("d")
            self.emit(f"{value} = to_bits({result})")
            self.set_reg(0, 0)
        else:
            self.set_reg(0, f"to_bits({result})")
            value = "r0"
        if seen:
            self.emit(f"flags = {above} | (2 if {value} > 0x80000000 else 0)"
                      f" | (({value} & 0x7FFFFFFF) == 0)")
