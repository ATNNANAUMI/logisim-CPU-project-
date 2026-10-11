"""Linker: object files in, one ROM image out.

Memory layout it builds:

    ROM  0x00000   RJMP start          (2 words, added here)
         0x00002   each file's ROM part, in the order given
    RAM  0x10000   stack, never touched by the linker
         0x14000   each file's RAM part, in the order given

Libraries: of a file given as a library, only the parts (see assembler.py)
the program needs are linked: the parts other files refer to, the parts
those refer to, and so on, plus the part each kept part falls through into.
A library nothing refers to is left out entirely, RAM included.
"""

import bisect
from dataclasses import dataclass

import encoding as enc
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


@dataclass
class _View:
    """The part of an object file that gets linked (all of it, unless it is a
    library), with offsets renumbered."""
    source: str
    rom: list
    ram_size: int
    labels: dict
    globals: list
    externs: list
    relocs: list


def _parts(obj):
    """(start, end, falls_through) for each part of an object's ROM."""
    raw = obj.parts or [[0, True]]
    out = []
    for i, (start, falls) in enumerate(raw):
        end = raw[i + 1][0] if i + 1 < len(raw) else len(obj.rom)
        out.append((start, end, falls))
    return out


def _part_index(parts, offset):
    """The part an offset is in (the end of the ROM counts as the last part)."""
    starts = [p[0] for p in parts]
    i = bisect.bisect_right(starts, offset) - 1
    return max(i, 0)


def _choose_parts(objects, libraries):
    """For each object, the set of part indexes to link (None: the object is
    not linked at all)."""
    defs = {}
    for obj in objects:
        for name in obj.globals:
            if name in obj.labels:
                sec, off = obj.labels[name]
                defs.setdefault(name, (obj, sec, off))
    parts = {id(o): _parts(o) for o in objects}
    kept = {id(o): set() for o in objects}
    used = {id(o): id(o) not in libraries for o in objects}
    work = []

    def need(obj, section, offset):
        used[id(obj)] = True
        if id(obj) not in libraries or section != "rom":
            return
        i = _part_index(parts[id(obj)], offset)
        if i not in kept[id(obj)]:
            kept[id(obj)].add(i)
            work.append((obj, i))

    for obj in objects:
        if id(obj) not in libraries:
            kept[id(obj)] = set(range(len(parts[id(obj)])))
            work.extend((obj, i) for i in kept[id(obj)])
    if ENTRY in defs:
        need(*defs[ENTRY])
    while work:
        obj, i = work.pop()
        start, end, falls = parts[id(obj)][i]
        if falls and i + 1 < len(parts[id(obj)]):
            need(obj, "rom", parts[id(obj)][i + 1][0])
        for r in obj.relocs:
            if not start <= r.at < end:
                continue
            if r.symbol is None:
                need(obj, r.section, r.addend)
            elif r.symbol in defs:
                target, section, offset = defs[r.symbol]
                need(target, section, offset + r.addend)
    return {id(o): (kept[id(o)] if used[id(o)] else None) for o in objects}


def _view(obj, keep):
    """The object with only the kept parts, offsets renumbered."""
    parts = _parts(obj)
    if keep == set(range(len(parts))):
        return _View(obj.source, list(obj.rom), obj.ram_size, dict(obj.labels),
                     list(obj.globals), list(obj.externs), list(obj.relocs))
    pieces = []                       # (old start, old end, new start)
    rom = []
    for i, (start, end, _) in enumerate(parts):
        if i in keep:
            pieces.append((start, end, len(rom)))
            rom.extend(obj.rom[start:end])

    def move(offset):
        for start, end, new in pieces:
            if start <= offset < end or (offset == end and end == len(obj.rom)):
                return new + offset - start
        if offset == len(obj.rom):
            return len(rom)
        return None

    labels = {}
    for name, (sec, off) in obj.labels.items():
        if sec == "ram":
            labels[name] = (sec, off)
        else:
            new = move(off)
            if new is not None:
                labels[name] = (sec, new)
    relocs = []
    for r in obj.relocs:
        at = move(r.at)
        if at is None or not any(s <= r.at < e for s, e, _ in pieces):
            continue
        addend = r.addend
        if r.symbol is None and r.section == "rom":
            addend = move(r.addend)
        relocs.append(type(r)(at, r.kind, r.symbol, r.section, addend, r.line, r.rom_only))
    globals_ = [g for g in obj.globals if g in labels]
    return _View(obj.source, rom, obj.ram_size, labels, globals_, list(obj.externs), relocs)


def link(objects, libraries=()):
    """Join object files. Returns a Program; raises AsmErrors.

    libraries: the objects (from the list) to link as libraries: only the
    parts the program needs."""
    lib_ids = {id(o) for o in libraries}
    exported = {name for o in objects for name in o.globals}   # before anything is dropped
    keep = _choose_parts(objects, lib_ids)
    objects = [_view(o, keep[id(o)]) for o in objects if keep[id(o)] is not None]
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

    # 3. The entry jump at address 0; its offset word is at address 1.
    start = table.get(ENTRY)
    if start is None:
        errors.append(AsmError("no file has '.global start', so the program "
                               "has nowhere to begin"))
    elif start.section != "rom":
        errors.append(AsmError(f"'start' in {start.source} is a RAM label, "
                               "it must be in ROM"))
    rom = [ENTRY_WORD, enc.jump_offset(start.address, 1) if start else 0]

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
                if r.rom_only and section != "rom":
                    errors.append(AsmError(f"can't call '{r.symbol}': it is a RAM label",
                                           obj.source, r.line))
                words[r.at] = target & MASK
            elif section != "rom":
                errors.append(AsmError(f"can't jump to '{r.symbol}': it is a RAM label",
                                       obj.source, r.line))
            else:
                words[r.at] = enc.jump_offset(target, base["rom"] + r.at)
        rom.extend(words)

    # 5. Every .extern must be exported somewhere, even if it is never used:
    #    a declared name nobody provides is a typo or a missing file.
    for obj in objects:
        for name in obj.externs:
            if name not in table and name not in exported and (obj.source, name) not in reported:
                reported.add((obj.source, name))
                errors.append(AsmError(f"'{name}' is listed in .extern but isn't .global "
                                       "in any of the files (is its file in the list?)",
                                       obj.source))

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
