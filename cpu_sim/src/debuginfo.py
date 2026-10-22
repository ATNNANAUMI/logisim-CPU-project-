"""What the .map file next to a ROM says: label names and C source lines.

The linker writes "name.map" next to "name.rom" (the C compiler always does,
the assembler with --map). Its label table gives the function an address is
in; its "source lines" section (from the C compiler's .loc directives) gives
the C line. The window uses this to show the C source, to step one C line
at a time, and to put breakpoints on lines.
"""

import bisect
import re
from pathlib import Path

import config as config

_LABEL_RE = re.compile(r"^([0-9a-fA-F]+)\s+(rom|ram)\s+(\S+)\s+(.*?)(\s+\(global\))?$")
_LINE_RE = re.compile(r"^([0-9a-fA-F]+)\s+(\d+)\s+(.+)$")
# labels the C compiler makes up: not function names
_GENERATED = re.compile(r"^_(K|L|S|F|C|G|A|T_|I_|V\d+_|crt0_|init_)")


class DebugInfo:
    def __init__(self, labels=(), lines=()):
        """labels: (address, name); lines: (address, file, line)."""
        rom = sorted((a, n) for a, n in labels if a < config.RAM_BIT and not _GENERATED.match(n))
        self.func_addrs = [a for a, _ in rom]
        self.func_names = [n for _, n in rom]
        self.lines = sorted(lines)
        self.line_addrs = [a for a, _, _ in self.lines]
        self.starts = set(self.line_addrs)
        self.files = sorted({f for _, f, _ in self.lines})

    @classmethod
    def load(cls, map_path):
        """Read a .map file; None if there is none."""
        path = Path(map_path)
        if not path.is_file():
            return None
        labels, lines = [], []
        in_lines = False
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.startswith("# source lines"):
                in_lines = True
                continue
            if raw.startswith("#") or not raw.strip():
                continue
            if in_lines:
                m = _LINE_RE.match(raw.strip())
                if m:
                    lines.append((int(m.group(1), 16), m.group(3), int(m.group(2))))
            else:
                m = _LABEL_RE.match(raw.strip())
                if m and m.group(2) == "rom" and not m.group(3).startswith("("):
                    labels.append((int(m.group(1), 16), m.group(3)))
        return cls(labels, lines)

    @classmethod
    def for_rom(cls, rom_path):
        return cls.load(Path(rom_path).with_suffix(".map")) if rom_path else None

    # ------------------------------------------------------------ lookups
    def function_at(self, address):
        i = bisect.bisect_right(self.func_addrs, address) - 1
        return self.func_names[i] if i >= 0 else None

    def _function_start(self, address):
        i = bisect.bisect_right(self.func_addrs, address) - 1
        return self.func_addrs[i] if i >= 0 else -1

    def line_at(self, address):
        """(file, line) of the C line this address belongs to, or None (no
        line information there, e.g. assembly code)."""
        i = bisect.bisect_right(self.line_addrs, address) - 1
        if i < 0:
            return None
        start, path, line = self.lines[i]
        if self._function_start(start) != self._function_start(address):
            return None                    # the nearest line is in another function
        return path, line

    def is_line_start(self, address):
        return address in self.starts

    def addresses_of(self, path, line):
        """Where the code of a C line starts (a line can have several pieces,
        e.g. a for loop's test)."""
        return [a for a, f, n in self.lines if f == path and n == line]

    def lines_in(self, path):
        return sorted({n for _, f, n in self.lines if f == path})


def step_line(cpu, info, over=False, limit=2_000_000):
    """Run until the CPU reaches the start of another C line.

    over=True steps over calls: lines inside a deeper frame (EBP is larger
    while a called function runs: the stack grows upward) don't count.
    Returns why it stopped: "line", "breakpoint", "halted" or "limit".
    """
    start = info.line_at(cpu.iar)
    start_ebp = cpu.ebp
    over = over and start is not None   # from assembly code: stop at the first C line
    for _ in range(limit):
        if cpu.step() is None:
            return "halted"
        if cpu.iar in cpu.breakpoints:
            return "breakpoint"
        if not info.is_line_start(cpu.iar):
            continue
        if over and cpu.ebp > start_ebp:
            continue
        here = info.line_at(cpu.iar)
        if here is not None and (here != start or cpu.ebp != start_ebp):
            return "line"
    return "limit"


def step_out(cpu, info, limit=2_000_000):
    """Run until the current function has returned to C code (EBP below
    where it is now). Like gdb's finish, it stops just after the call, in
    the middle of the caller's line."""
    start_ebp = cpu.ebp
    returned = False
    for _ in range(limit):
        step = cpu.step()
        if step is None:
            return "halted"
        if cpu.iar in cpu.breakpoints:
            return "breakpoint"
        # the frame goes (STK RET) a few instructions before the jump back
        jumped = cpu.iar != step.address + (1 if step.operand is None else 2)
        returned = returned or (cpu.ebp < start_ebp and jumped)
        if returned and info.line_at(cpu.iar) is not None:
            return "line"
    return "limit"
