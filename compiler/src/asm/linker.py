"""Linker: object files in, one ROM image out.

Memory layout it builds:

    ROM  0x00000   RJMP start          (2 words, added here)
         0x00002   each file's ROM part, in the order given
    RAM  0x10000   stack, never touched by the linker
         0x14000   each file's RAM part, in the order given
"""

from dataclasses import dataclass

from errors import AsmError, AsmErrors

MASK = 0xFFFFFFFF
ROM_SIZE = 0x10000
RAM_DATA_START = 0x14000
RAM_END = 0x20000
ENTRY = "start"
ENTRY_WORD = 0x0400        # RJMP; the next word is the offset to start
ENTRY_SIZE = 2


@dataclass
class Symbol:
    address: int
    name: str
    source: str
    section: str
    is_global: bool


@dataclass
class Program:
    rom: list          # the ROM image, from address 0
    ram_used: int      # words of RAM reserved above the stack
    symbols: list      # every label's final address (for the map file)


def link(objects):
    """Join object files. Returns a Program; raises AsmErrors."""
    errors = []

    # 1. Give each file its place in ROM and RAM.
    bases = []
    rom_next, ram_next = ENTRY_SIZE, RAM_DATA_START
    for obj in objects:
        bases.append({"rom": rom_next, "ram": ram_next})
        rom_next += len(obj.rom)
        ram_next += obj.ram_size
    if rom_next > ROM_SIZE:
        errors.append(AsmError(f"the program needs {rom_next} words of ROM, "
                               f"only {ROM_SIZE} fit"))
    if ram_next > RAM_END:
        errors.append(AsmError(f"RAM data needs {ram_next - RAM_DATA_START} words, "
                               f"only {RAM_END - RAM_DATA_START} fit above the stack"))

    # 2. Work out every label's final address; collect the .global ones.
    symbols, table = [], {}
    for obj, base in zip(objects, bases):
        for name, (section, offset) in obj.labels.items():
            sym = Symbol(base[section] + offset, name, obj.source, section,
                         name in obj.globals)
            symbols.append(sym)
            if not sym.is_global:
                continue
            if name in table:
                errors.append(AsmError(f"'{name}' is .global in both "
                                       f"{table[name].source} and {obj.source}"))
            else:
                table[name] = sym

    # 3. The entry jump at address 0. Its offset word sits at address 1.
    start = table.get(ENTRY)
    if start is None:
        errors.append(AsmError("no file has '.global start', so the program "
                               "has nowhere to begin"))
    elif start.section != "rom":
        errors.append(AsmError(f"'start' in {start.source} is a RAM label, "
                               "it must be in ROM"))
    rom = [ENTRY_WORD, (start.address - 1) & MASK if start else 0]

    # 4. Copy each file's words, filling in the relocations.
    reported = set()
    for obj, base in zip(objects, bases):
        words = list(obj.rom)
        for r in obj.relocs:
            if r.symbol is None:
                target, section = base[r.section] + r.addend, r.section
            else:
                sym = table.get(r.symbol)
                if sym is None:
                    if (obj.source, r.symbol) not in reported:
                        reported.add((obj.source, r.symbol))
                        errors.append(AsmError(
                            f"'{r.symbol}' isn't .global in any of the files "
                            "(is its file in the list?)", obj.source, r.line))
                    continue
                target, section = sym.address + r.addend, sym.section
            if r.kind == "abs":
                words[r.at] = target & MASK
            elif section != "rom":
                errors.append(AsmError(f"can't jump to '{r.symbol}': it is a RAM label",
                                       obj.source, r.line))
            else:
                words[r.at] = (target - (base["rom"] + r.at)) & MASK
        rom.extend(words)

    if errors:
        raise AsmErrors(errors)
    symbols.sort(key=lambda s: (s.address, s.name))
    return Program(rom, ram_next - RAM_DATA_START, symbols)


def format_raw(words, per_line=8):
    """Logisim 'v2.0 raw' text. Runs of 4 or more equal words become count*value."""
    items, i = [], 0
    while i < len(words):
        j = i
        while j < len(words) and words[j] == words[i]:
            j += 1
        if j - i >= 4:
            items.append(f"{j - i}*{words[i]:x}")
        else:
            items.extend(f"{words[i]:x}" for _ in range(j - i))
        i = j
    lines = ["v2.0 raw"]
    for k in range(0, len(items), per_line):
        lines.append(" ".join(items[k:k + per_line]))
    return "\n".join(lines) + "\n"


def format_map(program, title):
    """A text list of every label and its final address."""
    lines = [f"# labels in {title}",
             "# address  section  label                     file",
             f"{0:05x}      rom      (entry: RJMP start)"]
    for s in program.symbols:
        mark = "  (global)" if s.is_global else ""
        lines.append(f"{s.address:05x}      {s.section:<7}  {s.name:<25} {s.source}{mark}")
    return "\n".join(lines) + "\n"
