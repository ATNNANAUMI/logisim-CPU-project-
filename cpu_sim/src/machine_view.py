"""What the running machine holds, read the way the window's Stack, Heap and
Map panes need it (and the self-check): the call chain, malloc's blocks, the
memory layout. Nothing here changes the machine.

Read-only functions of (cpu, info), where info is the ROM's DebugInfo (its
.map): a program built without a map gets empty answers.
"""

import config as config

MAX_FRAMES = 256
MAX_BLOCKS = 20000


def frames(cpu, info, limit=MAX_FRAMES):
    """The call chain, innermost first: (function, address, (file, line) or
    None, ebp, three words after the frame's return address). A CALL pushes
    the return address and STK CALL saves EBP, so stack[EBP] is the caller's
    EBP and stack[EBP-1] the return address; the arguments are below that.
    The chain stops at EBP 0, a frame that is not below its caller's, a
    return address outside the code, or `limit` frames.
    Between a CALL and the function's STK CALL the top frame is not built yet
    and is shown as the caller's (shortcut: v1 does not detect the prologue)."""
    if info is None:
        return []
    out = []
    pc, ebp = cpu.iar, cpu.ebp
    seen = set()
    while len(out) < limit:
        name = info.function_at(pc)
        if name is None:
            break
        out.append((name, pc, info.line_at(pc), ebp, tuple(cpu.mem.stack_read(ebp - 2 - i) for i in range(3))))
        if ebp == 0 or ebp in seen:
            break
        seen.add(ebp)
        caller, ret = cpu.mem.stack_read(ebp), cpu.mem.stack_read(ebp - 1)
        # the return address is the word after the CALL's jump: the call is one before
        if caller == 0 or caller >= ebp or ret == 0 or ret >= config.RAM_BIT:
            break
        pc, ebp = ret - 1, caller
    return out


def heap(cpu, info, limit=MAX_BLOCKS):
    """malloc's blocks: (address, size in words with the header, used) from
    the first block to the heap's end, and the address of a damaged header
    or None. Empty before the first malloc (malloc.c's `heap` is 0)."""
    if info is None or not {"heap", "_heap_end"} <= set(info.symbols):
        return [], None
    start = cpu.mem.read(info.symbols["heap"])
    end = cpu.mem.read(info.symbols["_heap_end"])
    blocks, a = [], start
    if start == 0:
        return [], None
    while a < end and len(blocks) < limit:
        size = cpu.mem.read(a)
        size = size - (1 << 32) if size >= 1 << 31 else size
        if size == 0 or a + abs(size) > end:
            return blocks, a                  # what malloc.c refuses too
        blocks.append((a, abs(size), size < 0))
        a += abs(size)
    return blocks, None


def regions(cpu, info):
    """RAM split into its parts: (name, start, end) in address order, end
    exclusive: the data, the stack up to its limit, the heap (used part: up
    to its last block), and the free rest. Empty without a map."""
    if info is None or "_end" not in info.symbols:
        return []
    s = info.symbols
    base = config.RAM_BIT
    end_data = s["_end"]
    stack_base = s.get("_stack_base", base)
    out = [("data", base, stack_base), ("stack", stack_base, end_data)]
    heap_end = cpu.mem.read(s["_heap_end"]) if "_heap_end" in s else end_data
    out += [("heap", end_data, heap_end)]
    if heap_end < base + config.BANK_WORDS:
        out.append(("free", heap_end, base + config.BANK_WORDS))
    return [r for r in out if r[2] > r[1]]


REGISTER_NAMES = {f"R{i}": i for i in range(16)}


def resolve_address(text, cpu, info=None):
    """The window's go-to box: a sum of terms joined by + and -, each a
    register (R3, IAR, ESP, EBP: the value it holds), a label from the .map,
    or a hex number (0x optional). "ESP-4", "main+10", "1000a". Raises
    ValueError saying which term it could not read."""
    total, sign, term = 0, 1, ""
    for char in text.replace(" ", "") + "\0":
        if char in "+-\0" and term:
            total += sign * _term(term, cpu, info)
            term = ""
        elif char in "+-" and not term:
            raise ValueError(f"a number is missing before '{char}'")
        if char == "+" or char == "-":
            sign = 1 if char == "+" else -1
        elif char != "\0":
            term += char
    if text.strip() == "" or text.strip()[-1] in "+-":
        raise ValueError("a number is missing")
    return total


def _term(term, cpu, info):
    upper = term.upper()
    if upper in REGISTER_NAMES:
        return cpu.regs[REGISTER_NAMES[upper]]
    if upper in ("IAR", "ESP", "EBP"):
        return getattr(cpu, upper.lower())
    if info is not None and term in info.symbols:
        return info.symbols[term]
    try:
        return int(term, 16)
    except ValueError:
        raise ValueError(f"'{term}' is not a register, a label or a hex number") from None
