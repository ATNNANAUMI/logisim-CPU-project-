"""The CPU itself: 16 registers, 25-bit IAR, C A N Z flags, a RAM stack, interrupts."""

import time
from dataclasses import dataclass, field

import alu as alu
import config as config
import isa as isa
import translate as translate
from devices import DeviceBus
from isa import decode, disassemble
from memory import Memory
from translate import Stop


@dataclass
class Step:
    """What one executed instruction did (for the trace panel)."""
    address: int
    word: int
    operand: int | None
    text: str
    note: str = ""


@dataclass
class CPU:
    mem: Memory = field(default_factory=Memory)
    bus: DeviceBus = field(default_factory=DeviceBus)

    regs: list[int] = field(default_factory=lambda: [0] * 16)
    iar: int = 0
    flags: int = 0          # C A N Z, bit3 .. bit0
    esp: int = 0            # 24-bit indices into RAM (the stack can be anywhere)
    ebp: int = 0
    slimit: int = config.STACK_LIMIT_RESET   # a PUSH/CALL at ESP >= this faults (SLIM)

    # interrupts (TECHNICAL 1.8)
    ie: int = 0             # the enable latch (EI/DI); off at reset
    in_nmi: int = 0         # inside an NMI handler: the next NMI waits for its RTI
    inhibit: int = 0        # 1 right after RTI/EI: one instruction runs before the next one
    waiting: bool = False   # WAIT: asleep until an interrupt
    nmi_pending: bool = False
    fault_pending: bool = False     # a PUSH/CALL went past the limit (vector 8)

    breakpoints: set = field(default_factory=set)   # addresses to stop before
    halted: bool = False
    stopped: bool = False   # hard stop (nothing sets it now: the stack limit faults instead)
    error: str = ""
    instructions: int = 0

    # translated ROM code (translate.py), made for the ROM list _code_rom
    # and the TWEAKS _code_options: see forget_code()
    _code: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _code_rom: object = field(default=None, init=False, repr=False, compare=False)
    _code_options: tuple = field(default=(), init=False, repr=False, compare=False)
    _code_check: bool = field(default=False, init=False, repr=False, compare=False)
    _code_ram: object = field(default=None, init=False, repr=False, compare=False)
    _ram_code: object = field(default=None, init=False, repr=False, compare=False)
    _heat: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    _trees: list = field(default_factory=lambda: [None, None], init=False, repr=False,
                         compare=False)
    _outside: list = field(default_factory=lambda: [0, 0], init=False, repr=False,
                           compare=False)
    _redispatch: list = field(default_factory=lambda: [0, 0], init=False, repr=False,
                              compare=False)

    # --------------------------------------------------------------- state
    def reset(self, clear_ram: bool = True) -> None:
        self.regs = [0] * 16
        self.iar = 0
        self.flags = 0
        self.esp = self.ebp = 0
        self.slimit = config.STACK_LIMIT_RESET
        self.ie = self.in_nmi = self.inhibit = 0
        self.waiting = self.nmi_pending = self.fault_pending = False
        self.halted = self.stopped = False
        self.error = ""
        self.instructions = 0
        self.bus.reset()
        self._code_check = True     # keep the translated code that is still right
        if clear_ram:
            self._code_ram = None   # (so the old 128 MB list goes now, not in the next run())
            self.mem.clear_ram()

    def forget_code(self) -> None:
        """Drop the translated code. Call it after changing memory words
        from outside while a program runs; a new ROM or RAM list (load_rom(),
        load_ram()) and a reset() need no call (a reset drops the code whose
        words changed). The CPU's own RAM writes drop RAM code themselves."""
        self._code = {}             # address -> translate.translate()'s block
        self._heat = {}             # address -> times the interpreter jumped there
        # per bank (ROM, RAM): translate.dispatcher() of its blocks, the
        # blocks run outside it since, and how many more make it again
        self._trees, self._outside = [None, None], [0, 0]
        self._redispatch = [translate.REDISPATCH] * 2
        self._code_rom = self._code_ram = None
        self._ram_code = None       # bytearray: 1 for each RAM word a block was made from
        self._code_check = False

    def _check_code(self) -> None:
        """After a reset: drop the blocks whose words have changed."""
        self._code_check = False
        rom, ram = self.mem.rom, self.mem.ram
        stale = [a for a, block in self._code.items()
                 if not translate.still_there(rom, ram, block[2])]
        if any(a & config.RAM_BIT for a in stale):
            self._drop_ram_code()
        for address in stale:
            if self._code.pop(address, None):
                self._trees[0] = None

    def _drop_ram_code(self) -> None:
        """Forget every block made from RAM (the map of their words too)."""
        marks = self._ram_code
        for address in [a for a in self._code if a & config.RAM_BIT]:
            if marks is not None:
                for word in translate.words(self._code[address][2]):
                    marks[word & config.BANK_MASK] = 0
            del self._code[address]
        self._trees[1] = None
        self._outside[1], self._redispatch[1] = 0, translate.REDISPATCH

    def _guard_stores(self) -> None:
        """The first RAM block: from now on stores check the RAM code map, so
        the ROM blocks made without that check are made again (with it)."""
        self._ram_code = bytearray(config.BANK_WORDS)
        for address in [a for a in self._code if not a & config.RAM_BIT]:
            del self._code[address]
        self._trees[0] = None
        self._outside[0], self._redispatch[0] = 0, translate.REDISPATCH

    def _code_written(self, offset: int) -> None:
        """A store went to RAM word offset, which translated code was made
        from: that code is wrong now (the store's instruction then leaves its
        block, and running goes on from the new words)."""
        self._drop_ram_code()

    def _stored(self, addr: int) -> None:
        """step()'s writes: the same check as translated code's."""
        offset = addr & config.BANK_MASK
        if addr & config.RAM_BIT and self._ram_code is not None and self._ram_code[offset]:
            self._code_written(offset)

    def resume(self) -> None:
        self.halted = False

    def nmi(self) -> None:
        """The non-maskable interrupt (the kill switch): taken before the next
        instruction, and the only thing besides a reset that wakes a HALT."""
        self.nmi_pending = True
        self.halted = False
        self.waiting = False

    # ----------------------------------------------------------- interrupts
    def _enter(self, vector: int, return_to: int) -> None:
        """What the hardware does for an interrupt: push two words, turn
        interrupts off and jump to the vector. First the selected devices
        (COMM's OUTADDR in bits 15-0, INADDR in 31-16: they are global state
        and OUTADDR + OUTDATA are two instructions, so a handler that talks
        to a device must not leave the program's selection changed), then the
        word with the address to return to (bits 24-0), in-NMI (26), the enable
        bit (27) and the flags C A N Z (31-28). No stack limit check for
        these pushes; the FAULT vector also switches the limit off (SLIM sets
        it again), so its handler can use the stack."""
        bus, ram, mask = self.bus, self.mem.ram, config.BANK_MASK
        first, second = self.esp, (self.esp + 1) & mask
        ram[first] = bus.out_addr & 0xFFFF | (bus.in_addr & 0xFFFF) << 16
        ram[second] = return_to | self.in_nmi << 26 | self.ie << 27 | self.flags << 28
        self._stored(config.RAM_BIT | first)
        self._stored(config.RAM_BIT | second)
        self.esp = (second + 1) & mask
        self.ie = 0
        if vector == config.VECTOR_NMI:
            self.in_nmi = 1
        elif vector == config.VECTOR_FAULT:
            self.slimit = config.STACK_LIMIT_RESET      # the handler needs room: SLIM sets a new one
        self.iar = vector
        self.instructions += 1

    def _return(self) -> None:
        """RTI: pop the two words _enter() pushed."""
        mask = config.BANK_MASK
        self.esp = (self.esp - 1) & mask
        word = self.mem.ram[self.esp]
        self.esp = (self.esp - 1) & mask
        devices = self.mem.ram[self.esp]
        self.bus.out_address(devices & 0xFFFF)
        self.bus.in_address(devices >> 16)
        self.iar = word & config.ADDR_MASK
        self.in_nmi = word >> 26 & 1
        self.ie = word >> 27 & 1
        self.flags = word >> 28 & 0xF
        self.inhibit = 1

    def _service(self, blocked: int):
        """Take the interrupt that is due, if there is one: returns its
        vector or None. A fault (stack limit) is due at once; the others wait
        one instruction after RTI/EI (blocked), the NMI also for the end of
        the NMI handler, and an IRQ needs the enable latch."""
        if self.fault_pending:
            self.fault_pending = False
            vector = config.VECTOR_FAULT
        elif blocked:
            return None
        elif self.nmi_pending and not self.in_nmi:
            self.nmi_pending = False
            vector = config.VECTOR_NMI
        elif self.ie and self.bus.irq_line():
            vector = config.VECTOR_IRQ
        else:
            return None
        self._enter(vector, self.iar)
        return vector

    def _wake(self) -> bool:
        """Is something there that ends a WAIT?"""
        if (self.nmi_pending and not self.in_nmi) or (self.ie and self.bus.irq_line()):
            self.waiting = False
            return True
        return False

    def idle_seconds(self):
        """For a caller that finds the CPU asleep (WAIT): how long to wait
        before the timer raises something, or None when only a key or the NMI
        can wake it."""
        return self.bus.timer.until_tick() if self.ie else None

    def flag(self, name: str) -> bool:
        return bool(self.flags & isa.FLAG_BITS[name])

    @property
    def flag_text(self) -> str:
        return " ".join(f"{n}={int(self.flag(n))}" for n in isa.FLAG_NAMES)

    # ------------------------------------------------------------ fetching
    def _fetch(self) -> int:
        word = self.mem.read(self.iar)
        self.iar = (self.iar + 1) & config.ADDR_MASK
        return word

    # ------------------------------------------------------------ stepping
    def step(self) -> Step | None:
        """Execute one instruction.  Returns None while halted or stopped."""
        if self.halted or self.stopped:
            return None
        blocked, self.inhibit = self.inhibit, 0
        if self.waiting and not self._wake():
            return None
        address = self.iar
        vector = self._service(blocked)
        if vector is not None:
            names = {config.VECTOR_NMI: "NMI", config.VECTOR_IRQ: "IRQ",
                     config.VECTOR_FAULT: "FAULT"}
            return Step(address, 0, None, f"<{names[vector]}>",
                        f"pushed 0x{address:0{config.ADDR_DIGITS}X}, jump to {vector}")

        address = self.iar
        word = self._fetch()
        ins = decode(word)

        operand = operand_addr = None
        if ins.takes_operand:
            operand_addr = self.iar
            operand = self._fetch()

        note = self._execute(ins, operand, operand_addr)
        if self.fault_pending:          # a PUSH/CALL past the limit: not executed, not counted
            self._service(0)
            return Step(address, word, operand, disassemble(word, operand),
                        f"{note}, jump to {config.VECTOR_FAULT}")
        self.instructions += 1
        return Step(address, word, operand, disassemble(word, operand), note)

    def run(self, max_steps: int = 1_000_000, stop_at=()) -> int:
        """Execute up to max_steps instructions; returns how many ran (taking
        an interrupt counts as one).

        Does what calling step() max_steps times does, much faster: code
        that has run often runs as translated blocks (translate.py), the
        rest (cold code, the last instructions before max_steps, and
        everything when there are breakpoints) through _interpret(). It
        stops early at HALT, at a WAIT that nothing ends yet, or before an
        instruction whose address is in stop_at (not checked for the first
        one, so a run can leave a breakpoint).

        Interrupts are looked for between chunks of config.INTERRUPT_CHUNK
        instructions (step() looks before every instruction), so one that
        arrives while a chunk runs is taken up to a chunk later; with the
        timer off and nothing latched, there are no chunks (see _chunk()).
        """
        total = 0
        while total < max_steps:
            if self.halted or self.stopped:
                break
            blocked, self.inhibit = self.inhibit, 0
            if self.waiting and not self._wake():
                break
            if self._service(blocked) is not None:
                total += 1
                if total >= max_steps:
                    break
            if stop_at and total and self.iar in stop_at:
                break
            # after RTI/EI exactly one instruction runs before interrupts are looked for
            chunk = 1 if blocked else self._chunk(max_steps - total)
            done = self._run(min(max_steps - total, chunk), stop_at)
            total += done
            if self.halted or self.stopped or self.waiting:
                break
            if done == 0 and not self.fault_pending:
                break
        return total

    def _chunk(self, left: int) -> int:
        """How far run() goes before it looks for an interrupt again. With
        the timer off and no enabled request latched, only the outside (a
        typed key, an NMI) can raise one, and that happens between run()
        calls, so the whole run is one chunk: starting _run() is not free
        (it halved the speed). EI and RTI end a run anyway (inhibit); what is
        left is a program that enables a latched source while interrupts are
        on already: it is taken when this run() ends."""
        bus = self.bus
        if bus.timer.period or bus.interrupts.line or self.nmi_pending:
            return config.INTERRUPT_CHUNK
        return left

    def run_sleeping(self, max_steps: int = 1_000_000) -> int:
        """run(), but a CPU that goes to sleep (WAIT) is let sleep until the
        timer raises something, as a real one would; it gives up when nothing
        can wake it (no timer, no enabled interrupts: only a key or the NMI
        from outside could). Returns the instructions run."""
        done = 0
        while done < max_steps:
            done += self.run(max_steps - done)
            if not self.waiting:
                break
            sleep = self.idle_seconds()
            if sleep is None:
                break
            time.sleep(min(sleep, 0.05))
        return done

    def _run(self, max_steps: int, stop_at=()) -> int:
        """run() without the interrupt check: one chunk."""
        if self.halted or self.stopped:
            return 0
        if stop_at:
            return self._interpret(max_steps, stop_at)
        rom, ram, regs = self.mem.rom, self.mem.ram, self.regs
        options = translate.options()
        if self._code_rom is not rom or self._code_options != options:
            self.forget_code()
            self._code_rom, self._code_options, self._code_ram = rom, options, ram
        elif self._code_check:
            self._check_code()
        if self._code_ram is not ram:                       # a new RAM list
            self._drop_ram_code()
            self._code_ram = ram
        code, heat = self._code, self._heat
        hot = translate.HOT
        trees, outside, redispatch = self._trees, self._outside, self._redispatch
        bank_bits = config.BANK_BITS

        iar, flags, esp, ebp = self.iar, self.flags, self.esp, self.ebp
        count = 0               # instructions run, by blocks and by _interpret()
        interpreted = 0         # those of _interpret(), which counts them itself
        try:
            while count < max_steps:
                bank = iar >> bank_bits
                tree = trees[bank]
                if tree is not None:
                    iar, flags, esp, ebp, count, stopped = tree(
                        regs, rom, ram, flags, esp, ebp, self, iar, count, max_steps)
                    if stopped:                     # HALT, a fault, or RAM code rewritten
                        if self.halted or self.stopped or self.fault_pending:
                            break
                        continue
                    if count >= max_steps:
                        break
                    if iar >> bank_bits != bank:    # on in the other bank
                        continue
                block = code.get(iar)
                if block is None:
                    warm = heat.get(iar, 0) + 1
                    heat[iar] = warm
                    if warm >= hot:
                        block = translate.translate(rom, ram, iar, self._ram_code is not None)
                    if block is None:
                        # cold code (or an operand in the other bank): one at
                        # a time, up to a jump to hot or translated code
                        self.iar, self.flags, self.esp, self.ebp = iar, flags, esp, ebp
                        iar = None                  # self has it (if _interpret raises)
                        done = self._interpret(max_steps - count, watch=True)
                        iar, flags, esp, ebp = self.iar, self.flags, self.esp, self.ebp
                        count += done
                        interpreted += done
                        if (self.halted or self.stopped or self.waiting or self.fault_pending
                                or self.inhibit):
                            break
                        continue
                    code[iar] = block
                    if iar & config.RAM_BIT:        # stores there must drop it
                        if self._ram_code is None:
                            self._guard_stores()
                        for word in translate.words(block[2]):
                            self._ram_code[word & config.BANK_MASK] = 1
                function, length, _ = block
                if count + length > max_steps:      # the last few: one at a time
                    self.iar, self.flags, self.esp, self.ebp = iar, flags, esp, ebp
                    iar = None
                    done = self._interpret(max_steps - count)
                    iar, flags, esp, ebp = self.iar, self.flags, self.esp, self.ebp
                    count += done
                    interpreted += done
                    break
                try:
                    iar, flags, esp, ebp, done = function(regs, rom, ram, flags, esp, ebp, self)
                except Stop as stop:                # HALT, a stop, or RAM code rewritten
                    iar, flags, esp, ebp, done = stop.args
                    count += done
                    if self.halted or self.stopped or self.fault_pending:
                        break
                    continue
                count += done
                outside[bank] += 1                  # a block its bank's tree doesn't have yet
                if outside[bank] >= redispatch[bank]:
                    outside[bank] = 0
                    redispatch[bank] *= 2
                    trees[bank] = translate.dispatcher(
                        {a: b for a, b in code.items() if a >> bank_bits == bank})
        finally:
            if iar is not None:
                self.iar, self.flags, self.esp, self.ebp = iar, flags, esp, ebp
            self.instructions += count - interpreted
        return count

    def _interpret(self, max_steps: int, stop_at=(), watch: bool = False) -> int:
        """run() one instruction at a time (no translation). watch: also
        stop at a jump to code that is translated or has become hot (jumps
        are counted in _heat, see translate.HOT).

        The common integer ALU ops are written out here for speed; DIV, MOD
        and the float group go through alu.py. selftest.py checks that this,
        the translated blocks and step() agree, so keep them in step when an
        instruction changes.
        """
        regs = self.regs
        rom, ram = self.mem.rom, self.mem.ram
        bus = self.bus
        int_op, float_op = alu.int_op, alu.float_op
        int_names, float_names = isa.INT_OPS, isa.FLOAT_OPS
        MASK, SIGN = config.WORD_MASK, config.SIGN_BIT
        ADDR_MASK = config.ADDR_MASK
        RAM_BIT, BANK_MASK = config.RAM_BIT, config.BANK_MASK
        INDEX_MASK = config.STACK_INDEX_MASK
        a_signed, shr_arith = config.A_FLAG_SIGNED, config.SHR_ARITHMETIC

        if watch:
            code, heat = self._code, self._heat
            hot = translate.HOT
        marks = self._ram_code              # RAM words translated code was made from
        slimit = self.slimit
        inhibited = -1                      # the count at which RTI/EI ran last

        iar, flags, esp, ebp = self.iar, self.flags, self.esp, self.ebp
        count = 0
        try:
            while count < max_steps:
                if count and iar in stop_at:
                    break
                word = ram[iar & BANK_MASK] if iar & RAM_BIT else rom[iar]
                iar = (iar + 1) & ADDR_MASK
                count += 1
                op = (word >> 8) & 0xF
                rb = word & 0xF

                if word & 0x1000:                           # ALU
                    a = regs[(word >> 4) & 0xF]
                    if word & 0x4000:                       # immediate operand
                        b = ram[iar & BANK_MASK] if iar & RAM_BIT else rom[iar]
                        iar = (iar + 1) & ADDR_MASK
                    else:
                        b = regs[rb]
                    if word & 0x2000 or op == 3 or op == 0xA:   # float, DIV, MOD
                        if word & 0x2000:
                            regs[0], flags = float_op(float_names[op], a, b)
                        else:
                            regs[0], flags = int_op(int_names[op], a, b)
                        continue
                    carry = 0
                    if op == 0x0:                           # ADD
                        value = a + b
                        if value > MASK:
                            carry, value = 8, value & MASK
                        result = value
                    elif op == 0x1:                         # SUB: C = borrow
                        if a < b:
                            carry = 8
                        result = value = (a - b) & MASK
                    elif op == 0xF:                         # CMP: R0 = 0, C = 0
                        value = (a - b) & MASK
                        result = 0
                    elif op == 0x7:
                        result = value = a & b
                    elif op == 0x8:
                        result = value = a | b
                    elif op == 0x9:
                        result = value = a ^ b
                    elif op == 0xB:                         # ++
                        value = b + 1
                        if value > MASK:
                            carry, value = 8, 0
                        result = value
                    elif op == 0xC:                         # --
                        result = value = (b - 1) & MASK
                    elif op == 0xE:                         # TEST
                        result = value = b
                    elif op == 0x4:                         # SHL
                        if b & SIGN:
                            carry = 8
                        result = value = (b << 1) & MASK
                    elif op == 0x5:                         # SHR
                        if b & 1:
                            carry = 8
                        value = b >> 1
                        if shr_arith:
                            value |= b & SIGN
                        result = value
                    elif op == 0x6:                         # NOT
                        result = value = ~b & MASK
                    elif op == 0xD:                         # NEG
                        result = value = -b & MASK
                    else:                                   # MULT (low 32 bits)
                        result = value = (a * b) & MASK
                    if a_signed:
                        bigger = (a ^ SIGN) > (b ^ SIGN)
                    else:
                        bigger = a > b
                    regs[0] = result
                    flags = carry | (4 if bigger else 0) | ((value >> 30) & 2) | (value == 0)
                    continue

                if word & 0x2000 and op < 10:               # interrupts, ESP/EBP/limit
                    if op == 0:                             # RTI
                        esp = (esp - 2) & BANK_MASK
                        back = ram[(esp + 1) & BANK_MASK]
                        bus.out_address(ram[esp] & 0xFFFF)
                        bus.in_address(ram[esp] >> 16)
                        iar = back & ADDR_MASK
                        self.in_nmi = back >> 26 & 1
                        self.ie = back >> 27 & 1
                        flags = back >> 28 & 0xF
                        inhibited = count
                        break                               # run() looks for interrupts
                    elif op == 1:                           # EI
                        self.ie = 1
                        inhibited = count
                        break
                    elif op == 2:                           # DI
                        self.ie = 0
                    elif op == 3:                           # TRAP: vector 6, back to the next word
                        ram[esp] = bus.out_addr & 0xFFFF | (bus.in_addr & 0xFFFF) << 16
                        ram[(esp + 1) & BANK_MASK] = iar | self.in_nmi << 26 | self.ie << 27 | flags << 28
                        if marks is not None and (marks[esp] or marks[(esp + 1) & BANK_MASK]):
                            self._code_written(esp)
                        esp = (esp + 2) & BANK_MASK
                        self.ie = 0
                        iar = config.VECTOR_TRAP
                    elif op == 4:                           # WAIT
                        self.waiting = True
                        break
                    elif op == 5:                           # GSP
                        regs[rb] = esp
                    elif op == 6:                           # SSP
                        esp = regs[rb] & BANK_MASK
                    elif op == 7:                           # GBP
                        regs[rb] = ebp
                    elif op == 8:                           # SBP
                        ebp = regs[rb] & BANK_MASK
                    else:                                   # SLIM
                        slimit = self.slimit = regs[rb] & BANK_MASK
                elif op == 0x3:                             # DATA
                    regs[rb] = ram[iar & BANK_MASK] if iar & RAM_BIT else rom[iar]
                    iar = (iar + 1) & ADDR_MASK
                elif op == 0xC:                             # ALD
                    addr = (regs[(word >> 4) & 0xF] + regs[rb]) & ADDR_MASK
                    regs[0] = ram[addr & BANK_MASK] if addr & RAM_BIT else rom[addr]
                elif op == 0xD:                             # AST
                    addr = (regs[(word >> 4) & 0xF] + regs[rb]) & ADDR_MASK
                    if addr & RAM_BIT:
                        ram[addr & BANK_MASK] = regs[0]
                        if marks is not None and marks[addr & BANK_MASK]:
                            self._code_written(addr & BANK_MASK)
                elif op == 0x4 or op == 0x5 or op == 0x6:   # RJMP, RJF, RJNF
                    offset = ram[iar & BANK_MASK] if iar & RAM_BIT else rom[iar]
                    if op == 0x4:
                        take = True
                    elif op == 0x5:
                        take = flags & rb != 0
                    else:
                        take = flags & rb != rb
                    # relative to the offset word; adding the unsigned offset
                    # gives the same low address bits as adding the signed one
                    if not take:
                        iar = (iar + 1) & ADDR_MASK
                        continue
                    iar = (iar + offset) & ADDR_MASK
                    if watch:                               # translated or hot code there?
                        if iar in code:
                            break
                        warm = heat.get(iar, 0) + 1
                        heat[iar] = warm
                        if warm >= hot:
                            break
                elif op == 0xE:                             # CPY
                    regs[rb] = regs[(word >> 4) & 0xF]
                elif op == 0xB:                             # STK
                    kind = (word >> 4) & 7
                    if kind == 0:                           # PUSH
                        if esp >= slimit:                   # past the limit: not executed
                            self.fault_pending = True
                            iar = (iar - 1) & ADDR_MASK
                            count -= 1
                            break
                        ram[esp] = regs[0]
                        if marks is not None and marks[esp]:
                            self._code_written(esp)
                        esp += 1
                    elif kind == 1:                         # POP
                        esp = (esp - 1) & BANK_MASK
                        regs[0] = ram[esp]
                    elif kind == 2:                         # CALL (frame only)
                        if esp >= slimit:
                            self.fault_pending = True
                            iar = (iar - 1) & ADDR_MASK
                            count -= 1
                            break
                        ram[esp] = ebp
                        if marks is not None and marks[esp]:
                            self._code_written(esp)
                        ebp = esp
                        esp += 1
                    elif kind == 3:                         # RET
                        esp = ebp
                        ebp = ram[ebp] & BANK_MASK
                    elif kind == 4:                         # SET
                        addr = (ebp + regs[rb]) & INDEX_MASK
                        ram[addr] = regs[0]
                        if marks is not None and marks[addr]:
                            self._code_written(addr)
                    elif kind == 5:                         # GET
                        regs[0] = ram[(ebp + regs[rb]) & INDEX_MASK]
                elif op == 0x8:                             # COMM
                    mode = (word >> 4) & 3
                    if mode == 2:
                        bus.send(regs[rb])
                    elif mode == 3:
                        bus.out_address(regs[rb])
                    elif mode == 1:
                        bus.in_address(regs[rb])
                    else:
                        value = bus.in_data()
                        if value is not None:
                            regs[rb] = value & MASK
                elif op == 0x1:                             # LD
                    addr = regs[(word >> 4) & 0xF] & ADDR_MASK
                    regs[rb] = ram[addr & BANK_MASK] if addr & RAM_BIT else rom[addr]
                elif op == 0x2:                             # ST
                    addr = regs[(word >> 4) & 0xF] & ADDR_MASK
                    if addr & RAM_BIT:
                        ram[addr & BANK_MASK] = regs[rb]
                        if marks is not None and marks[addr & BANK_MASK]:
                            self._code_written(addr & BANK_MASK)
                elif op == 0x9:                             # ADDR
                    regs[rb] = iar
                elif op == 0xA:                             # JMRB
                    iar = regs[rb] & ADDR_MASK
                    if watch:                               # translated or hot code there?
                        if iar in code:
                            break
                        warm = heat.get(iar, 0) + 1
                        heat[iar] = warm
                        if warm >= hot:
                            break
                elif op == 0x7:                             # CLF
                    flags = 0
                elif op == 0xF:                             # HALT
                    self.halted = True
                    break
                # 0x0 NOP
        finally:
            self.iar, self.flags, self.esp, self.ebp = iar, flags, esp, ebp
            self.instructions += count
            self.inhibit = 1 if inhibited == count else 0
        return count

    # ----------------------------------------------------------- execution
    def _execute(self, ins: isa.Instr, operand, operand_addr) -> str:
        if ins.is_alu:
            return self._execute_alu(ins, operand)

        name = ins.name
        ra, rb = ins.ra, ins.rb

        if name == "NOP":
            return ""

        if name == "LD":
            addr = self.regs[ra] & config.ADDR_MASK     # before the load, when ra == rb
            self.regs[rb] = self.mem.read(addr)
            return f"R{rb} <- [0x{addr:0{config.ADDR_DIGITS}X}]"

        if name == "ST":
            ok = self.mem.write(self.regs[ra], self.regs[rb])
            self._stored(self.regs[ra] & config.ADDR_MASK)
            return "" if ok else "write to ROM ignored"

        if name == "DATA":
            self.regs[rb] = operand & config.WORD_MASK
            return ""

        if name == "RJMP":
            return self._jump(operand_addr, operand)

        if name in ("RJF", "RJNF"):
            mask = rb
            tested = self.flags & mask
            take = tested != 0 if name == "RJF" else tested != mask
            if take:
                return self._jump(operand_addr, operand)
            return "not taken"

        if name == "CLF":
            self.flags = 0
            return ""

        if name == "COMM":
            return self._comm(ins.ra & 3, rb)

        if name == "ADDR":
            self.regs[rb] = self.iar
            return ""

        if name == "JMRB":
            self.iar = self.regs[rb] & config.ADDR_MASK
            return ""

        if name == "STK":
            return self._stack(ins.ra & 7, rb)

        if name == "ALD":
            addr = (self.regs[ra] + self.regs[rb]) & config.ADDR_MASK
            self.regs[0] = self.mem.read(addr)
            return f"R0 <- [0x{addr:0{config.ADDR_DIGITS}X}]"

        if name == "AST":
            addr = (self.regs[ra] + self.regs[rb]) & config.ADDR_MASK
            ok = self.mem.write(addr, self.regs[0])
            self._stored(addr)
            return f"[0x{addr:0{config.ADDR_DIGITS}X}] <- R0" if ok else "write to ROM ignored"

        if name == "CPY":
            self.regs[rb] = self.regs[ra]
            return ""

        if name == "HALT":
            self.halted = True
            return "halted"

        if name == "RTI":
            self._return()
            return f"back to 0x{self.iar:0{config.ADDR_DIGITS}X}"
        if name == "EI":
            self.ie = self.inhibit = 1
            return "interrupts on"
        if name == "DI":
            self.ie = 0
            return "interrupts off"
        if name == "TRAP":
            self._enter(config.VECTOR_TRAP, self.iar)
            self.instructions -= 1              # step() counts the TRAP itself
            return f"jump to {config.VECTOR_TRAP}"
        if name == "WAIT":
            self.waiting = True
            return "waiting"
        if name == "GSP":
            self.regs[rb] = self.esp
            return ""
        if name == "SSP":
            self.esp = self.regs[rb] & config.BANK_MASK
            return ""
        if name == "GBP":
            self.regs[rb] = self.ebp
            return ""
        if name == "SBP":
            self.ebp = self.regs[rb] & config.BANK_MASK
            return ""
        if name == "SLIM":
            self.slimit = self.regs[rb] & config.BANK_MASK
            return f"stack limit 0x{self.slimit:X}"

        return ""

    # ---------------------------------------------------------------- parts
    def _execute_alu(self, ins: isa.Instr, operand) -> str:
        a = self.regs[ins.ra]
        b = operand & config.WORD_MASK if ins.is_imm else self.regs[ins.rb]
        engine = alu.float_op if ins.is_float else alu.int_op
        result, flags = engine(ins.name, a, b)
        self.regs[0] = result
        self.flags = flags
        return f"R0 = 0x{result:08X}"

    def _jump(self, operand_addr: int, operand: int) -> str:
        target = (operand_addr + alu.to_signed(operand)) & config.ADDR_MASK
        self.iar = target
        return f"-> 0x{target:0{config.ADDR_DIGITS}X}"

    def _comm(self, mode: int, rb: int) -> str:
        if mode == 0b11:                                   # OUTADDR
            self.bus.out_address(self.regs[rb])
            return f"device 0x{self.regs[rb]:X} selected"
        if mode == 0b10:                                   # OUTDATA
            self.bus.out_data(self.regs[rb])
            return ""
        if mode == 0b01:                                   # INADDR
            self.bus.in_address(self.regs[rb])
            return f"input device 0x{self.regs[rb]:X} selected"
        value = self.bus.in_data()                         # INDATA
        if value is None:
            return "no input, register unchanged"
        self.regs[rb] = value & config.WORD_MASK
        return f"R{rb} <- 0x{value:X}"

    def _overflow(self) -> str:
        """A PUSH or CALL at or past the stack limit is not executed: the
        FAULT vector is taken before the next instruction, with the address
        of this one saved (the PUSH/CALL has no operand word)."""
        self.fault_pending = True
        self.iar = (self.iar - 1) & config.ADDR_MASK
        return "stack limit reached"

    def _stack(self, op: int, rb: int) -> str:
        name = isa.STK_OPS.get(op)
        mask = config.BANK_MASK

        if name == "PUSH":
            if self.esp >= self.slimit:
                return self._overflow()
            self.mem.stack_write(self.esp, self.regs[0])
            self._stored(config.RAM_BIT | self.esp)
            self.esp += 1
            return ""
        if name == "POP":
            self.esp = (self.esp - 1) & mask
            self.regs[0] = self.mem.stack_read(self.esp)
            return ""
        if name == "CALL":                      # frame only, no jump
            if self.esp >= self.slimit:
                return self._overflow()
            self.mem.stack_write(self.esp, self.ebp)
            self._stored(config.RAM_BIT | self.esp)
            self.ebp = self.esp
            self.esp += 1
            return f"frame at 0x{self.ebp:06X}"
        if name == "RET":
            self.esp = self.ebp
            self.ebp = self.mem.stack_read(self.ebp) & mask
            return f"frame back to 0x{self.ebp:06X}"
        if name == "SET":                       # EBP + RB, wrapping across all RAM
            index = (self.ebp + self.regs[rb]) & config.STACK_INDEX_MASK
            self.mem.stack_write(index, self.regs[0])
            self._stored(config.RAM_BIT | index)
            return f"stack[0x{index:0{config.ADDR_DIGITS - 1}X}] <- R0"
        if name == "GET":
            index = (self.ebp + self.regs[rb]) & config.STACK_INDEX_MASK
            self.regs[0] = self.mem.stack_read(index)
            return f"R0 <- stack[0x{index:0{config.ADDR_DIGITS - 1}X}]"
        return "undefined stack op"
