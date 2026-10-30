"""The CPU itself: 16 registers, 25-bit IAR, C A N Z flags, a RAM stack."""

from dataclasses import dataclass, field

import alu as alu
import config as config
import isa as isa
from devices import DeviceBus
from isa import decode, disassemble
from memory import Memory


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
    esp: int = 0
    ebp: int = 0

    breakpoints: set = field(default_factory=set)   # addresses to stop before
    halted: bool = False
    stopped: bool = False   # hard stop (stack wrap, when enabled)
    error: str = ""
    instructions: int = 0

    # --------------------------------------------------------------- state
    def reset(self, clear_ram: bool = True) -> None:
        self.regs = [0] * 16
        self.iar = 0
        self.flags = 0
        self.esp = self.ebp = 0
        self.halted = self.stopped = False
        self.error = ""
        self.instructions = 0
        self.bus.reset()
        if clear_ram:
            self.mem.clear_ram()

    def resume(self) -> None:
        self.halted = False

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

        address = self.iar
        word = self._fetch()
        ins = decode(word)

        operand = operand_addr = None
        if ins.takes_operand:
            operand_addr = self.iar
            operand = self._fetch()

        note = self._execute(ins, operand, operand_addr)
        self.instructions += 1
        return Step(address, word, operand, disassemble(word, operand), note)

    def run(self, max_steps: int = 1_000_000, stop_at=()) -> int:
        """Execute up to max_steps instructions; returns how many ran.

        Does what calling step() max_steps times does, about ten times
        faster: no Step records, no disassembly, machine state kept in local
        variables. It stops early at HALT, at a stack wrap (when that stops
        the CPU), or before an instruction whose address is in stop_at (not
        checked for the first one, so a run can leave a breakpoint).

        The common integer ALU ops are written out here for speed; DIV, MOD
        and the float group go through alu.py. selftest.py checks that both
        paths agree, so keep them in step when an instruction changes.
        """
        if self.halted or self.stopped:
            return 0

        regs = self.regs
        rom, ram = self.mem.rom, self.mem.ram
        bus = self.bus
        int_op, float_op = alu.int_op, alu.float_op
        int_names, float_names = isa.INT_OPS, isa.FLOAT_OPS
        MASK, SIGN = config.WORD_MASK, config.SIGN_BIT
        ADDR_MASK, STACK_MASK = config.ADDR_MASK, config.STACK_MASK
        RAM_BIT, BANK_MASK = config.RAM_BIT, config.BANK_MASK
        INDEX_MASK = config.STACK_INDEX_MASK
        a_signed, shr_arith = config.A_FLAG_SIGNED, config.SHR_ARITHMETIC

        iar, flags, esp, ebp = self.iar, self.flags, self.esp, self.ebp
        count = 0
        try:
            while count < max_steps:
                if iar in stop_at and count:
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

                if op == 0x3:                               # DATA
                    regs[rb] = ram[iar & BANK_MASK] if iar & RAM_BIT else rom[iar]
                    iar = (iar + 1) & ADDR_MASK
                elif op == 0xC:                             # ALD
                    addr = (regs[(word >> 4) & 0xF] + regs[rb]) & ADDR_MASK
                    regs[0] = ram[addr & BANK_MASK] if addr & RAM_BIT else rom[addr]
                elif op == 0xD:                             # AST
                    addr = (regs[(word >> 4) & 0xF] + regs[rb]) & ADDR_MASK
                    if addr & RAM_BIT:
                        ram[addr & BANK_MASK] = regs[0]
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
                    iar = (iar + offset) & ADDR_MASK if take else (iar + 1) & ADDR_MASK
                elif op == 0xE:                             # CPY
                    regs[rb] = regs[(word >> 4) & 0xF]
                elif op == 0xB:                             # STK
                    kind = (word >> 4) & 7
                    if kind == 0:                           # PUSH
                        ram[esp] = regs[0]
                        esp += 1
                        if esp > STACK_MASK:
                            esp = self._bump(esp - 1, +1)
                    elif kind == 1:                         # POP
                        esp -= 1
                        if esp < 0:
                            esp = self._bump(esp + 1, -1)
                        regs[0] = ram[esp]
                    elif kind == 2:                         # CALL (frame only)
                        ram[esp] = ebp
                        ebp = esp
                        esp += 1
                        if esp > STACK_MASK:
                            esp = self._bump(esp - 1, +1)
                    elif kind == 3:                         # RET
                        esp = ebp
                        ebp = ram[ebp] & STACK_MASK
                    elif kind == 4:                         # SET
                        ram[(ebp + regs[rb]) & INDEX_MASK] = regs[0]
                    elif kind == 5:                         # GET
                        regs[0] = ram[(ebp + regs[rb]) & INDEX_MASK]
                    if self.stopped:
                        break
                elif op == 0x8:                             # COMM
                    mode = (word >> 4) & 3
                    if mode == 2:
                        bus.out_data(regs[rb])
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
                elif op == 0x9:                             # ADDR
                    regs[rb] = iar
                elif op == 0xA:                             # JMRB
                    iar = regs[rb] & ADDR_MASK
                elif op == 0x7:                             # CLF
                    flags = 0
                elif op == 0xF:                             # HALT
                    self.halted = True
                    break
                # 0x0 NOP
        finally:
            self.iar, self.flags, self.esp, self.ebp = iar, flags, esp, ebp
            self.instructions += count
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
            return f"[0x{addr:0{config.ADDR_DIGITS}X}] <- R0" if ok else "write to ROM ignored"

        if name == "CPY":
            self.regs[rb] = self.regs[ra]
            return ""

        if name == "HALT":
            self.halted = True
            return "halted"

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

    def _stack(self, op: int, rb: int) -> str:
        name = isa.STK_OPS.get(op)

        if name == "PUSH":
            self.mem.stack_write(self.esp, self.regs[0])
            self.esp = self._bump(self.esp, +1)
            return ""
        if name == "POP":
            self.esp = self._bump(self.esp, -1)
            self.regs[0] = self.mem.stack_read(self.esp)
            return ""
        if name == "CALL":                      # frame only, no jump
            self.mem.stack_write(self.esp, self.ebp)
            self.ebp = self.esp
            self.esp = self._bump(self.esp, +1)
            return f"frame at 0x{self.ebp:04X}"
        if name == "RET":
            self.esp = self.ebp
            self.ebp = self.mem.stack_read(self.ebp) & config.STACK_MASK
            return f"frame back to 0x{self.ebp:04X}"
        if name == "SET":                       # EBP + RB, wrapping across all RAM
            index = (self.ebp + self.regs[rb]) & config.STACK_INDEX_MASK
            self.mem.stack_write(index, self.regs[0])
            return f"stack[0x{index:0{config.ADDR_DIGITS - 1}X}] <- R0"
        if name == "GET":
            index = (self.ebp + self.regs[rb]) & config.STACK_INDEX_MASK
            self.regs[0] = self.mem.stack_read(index)
            return f"R0 <- stack[0x{index:0{config.ADDR_DIGITS - 1}X}]"
        return "undefined stack op"

    def _bump(self, pointer: int, delta: int) -> int:
        new = pointer + delta
        if not 0 <= new <= config.STACK_MASK:
            if config.STOP_ON_STACK_WRAP:
                self.stopped = True
                self.error = "stack pointer wrapped"
            new &= config.STACK_MASK
        return new