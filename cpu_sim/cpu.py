"""The CPU itself: 16 registers, 17-bit IAR, C A N Z flags, a RAM stack."""

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

    def run(self, max_steps: int = 1_000_000) -> int:
        count = 0
        while count < max_steps and self.step() is not None:
            count += 1
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
            self.regs[rb] = self.mem.read(self.regs[ra])
            return f"R{rb} <- [0x{self.regs[ra] & config.ADDR_MASK:05X}]"

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
            return f"R0 <- [0x{addr:05X}]"

        if name == "AST":
            addr = (self.regs[ra] + self.regs[rb]) & config.ADDR_MASK
            ok = self.mem.write(addr, self.regs[0])
            return f"[0x{addr:05X}] <- R0" if ok else "write to ROM ignored"

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
        return f"-> 0x{target:05X}"

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
        if name == "SET":
            self.mem.stack_write(self.regs[rb], self.regs[0])
            return f"stack[{self.regs[rb]+self.ebp & config.STACK_MASK}] <- R0"
        if name == "GET":
            self.regs[0] = self.mem.stack_read(self.regs[rb])
            return f"R0 <- stack[{self.regs[rb]+self.ebp & config.STACK_MASK}]"
        return "undefined stack op"

    def _bump(self, pointer: int, delta: int) -> int:
        new = pointer + delta
        if not 0 <= new <= config.STACK_MASK:
            if config.STOP_ON_STACK_WRAP:
                self.stopped = True
                self.error = "stack pointer wrapped"
            new &= config.STACK_MASK
        return new