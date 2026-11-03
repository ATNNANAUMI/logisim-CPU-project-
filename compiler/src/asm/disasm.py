"""A ROM image or a program for the OS, back to assembly that builds the same words.

    python compiler/src/asm disasm prog.rom [--map prog.map] [-o prog.asm] [--raw]
    python compiler/src/asm disasm prog.exe [--map prog.map] [-o prog.asm] [--raw]

What it writes assembles and links into exactly the words it read: every
instruction is checked by assembling it once (a word the assembler would
write differently, like NOT with two different registers, becomes a
`.word`), and the layout is rebuilt as the linker made it.

* A ROM image (.rom, Logisim "v2.0 raw"): the linker's vectors and start-up
  code (ROM words 0 to 22) are not written; they give `start`, the interrupt
  handlers that are not the default ones (`_nmi`, `_irq`, `_trap`, `_fault`,
  made .global), the RAM the files reserve (one `.space` in `.ram`, with
  labels where the code points) and the stack's size (a comment when it is
  not the linker's 16K words: `link(stack_words=...)` then). Rebuild it with
  `python compiler/src/asm build prog.asm`.
* A program for the OS (.exe, TEX2): the entry jump is not written; its
  relocation list says exactly which words hold an address. Rebuild it with
  `linker.link([obj], base=linker.PROGRAM_BASE, exe_stack=...)` and
  `driver.exe_bytes(program, region)` (the numbers are in the first lines).

Code is found by following it from `start`, the interrupt handlers, the
`.map`'s ROM labels (with --map) and the return addresses and targets of the
`CALL`/`DATA Rn, x` + `JMRB Rn` patterns; the rest is data (`.word`, or
`.string` for a run of chars ending in 0). Jump targets get labels (the
`.map`'s names, else `L_<address>`), and so do the values that are
addresses: in a .exe the relocated words, in a ROM image the `DATA`/`.word`
values that land on a label of the map, on code found, or in the RAM the
files reserve, marked `; guess` (a number that happens to equal an address
would get a label too; the words come out the same either way). `CALL` and
`RET` are written back as the pseudo-ops unless --raw.
"""

import re
from pathlib import Path

import encoding as enc
import linker
from assembler import assemble
from errors import AsmError, AsmErrors

MASK = 0xFFFFFFFF
ALU_BIT, FLOAT_BIT, IMM_BIT = 0x1000, 0x2000, 0x4000
GROUP2 = {code: name for name, (code, _) in enc.SYSTEM_OPS.items() if code >= 0x20}
SYSTEM = {code: (name, shape) for name, (code, shape) in enc.SYSTEM_OPS.items() if code < 0x20}
ALU = {}
for _name, (_prefix, _op, _shape) in enc.ALU_OPS.items():
    ALU.setdefault((_prefix, _op), (_name, _shape))     # "++" before "INC": the first name
COMM_NAMES = {v: k for k, v in enc.COMM_OPS.items()}
STK_NAMES = {code: (name, reg) for name, (code, reg) in enc.STK_OPS.items()}
FLAG_ORDER = "CANZ"
# labels the C compiler gives to data (TECHNICAL 10.4): not code to follow
DATA_LABEL = re.compile(r"^_(S|F|C|G|V\d+_)\d*")


# ------------------------------------------------------------------- input

def read_rom(path):
    """The words of a Logisim 'v2.0 raw' image (count*value runs too)."""
    words = []
    lines = Path(path).read_text().splitlines()
    if not lines or lines[0].strip() != "v2.0 raw":
        raise AsmError(f"{path}: not a Logisim 'v2.0 raw' image")
    for line in lines[1:]:
        for item in line.split():
            if "*" in item:
                count, value = item.split("*")
                words += [int(value, 16)] * int(count)
            else:
                words.append(int(item, 16))
    return words


def read_map(path):
    """[(address, section, name)] of a .map, without the linker's own symbols."""
    labels = []
    for line in Path(path).read_text().splitlines():
        if line.startswith("# source lines"):
            break
        m = re.match(r"^([0-9a-fA-F]+)\s+(rom|ram)\s+(\S+)\s+(\S+)", line)
        if m and m.group(4) != "<linker>":
            labels.append((int(m.group(1), 16), m.group(2), m.group(3)))
    return labels


class Image:
    """What was read: the words of the program part and where things are.

    origin   the address of words[0]
    code     [start, end) of the words to write out (after the header)
    ram      [start, end) of the RAM the files reserve (their .space)
    """

    def __init__(self, words, origin, code, ram, start, kind, stack, relocs=None,
                 vectors=None, region=0, extra=()):
        self.words, self.origin, self.code, self.ram = words, origin, code, ram
        self.start, self.kind, self.stack = start, kind, stack
        self.relocs = None if relocs is None else {origin + r for r in relocs}
        self.vectors = vectors or {}
        self.region = region
        self.extra = dict(extra)        # linker symbols past the data: address -> name

    def word(self, address):
        return self.words[address - self.origin]


def _target(words, offset_word):
    """Where RJMP's offset word at that address points."""
    off = words[offset_word]
    off = off - (1 << 32) if off & 0x80000000 else off
    return (offset_word + off) & MASK


def image_from_rom(words):
    head = linker.ROM_HEADER
    if len(words) < head or words[0] != linker.ENTRY_WORD or words[linker.STARTUP] != linker.DATA_R1:
        raise AsmError("this ROM image does not start with the linker's vectors and start-up code")
    start = _target(words, linker.STARTUP + 10)
    vectors = {}
    default = {"_nmi": linker.STARTUP + 11, "_irq": linker.STARTUP + 11,
               "_trap": linker.STARTUP + 11, "_fault": linker.STARTUP + 12}
    for name, vector in linker.VECTORS.items():
        target = _target(words, vector + 1)
        if target != default[name]:
            vectors[name] = target
    stack_base = linker.RAM_BASE + words[linker.STARTUP + 1]
    end = linker.RAM_BASE + words[linker.STARTUP + 5]
    return Image(words, 0, (head, len(words)), (linker.RAM_DATA_START, stack_base), start, "rom",
                 end - stack_base, vectors=vectors,
                 extra={stack_base: "_stack_base", end: "_end"})


def image_from_exe(data):
    words = [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data) - 3, 4)]
    if len(words) < 8 or words[0] != 0x32584554:
        raise AsmError("not a TEX2 program (cc build --exe)")
    _, base, n, entry, zero, stack, region, r = words[:8]
    code = words[8:8 + n]
    relocs = words[8 + n:8 + n + r]
    if len(code) != n or len(relocs) != r or code[:1] != [linker.ENTRY_WORD]:
        raise AsmError("a damaged TEX2 program")
    start = _target({base + 1: code[1]}, base + 1)
    data_start = base + n
    return Image(code, base, (base + linker.ENTRY_SIZE, base + n), (data_start, data_start + zero),
                 start, "exe", stack, relocs=relocs, region=region,
                 extra={data_start + zero: "_stack_base", data_start + zero + stack: "_end"})


# ----------------------------------------------------------- instructions

def decode(word):
    """(text with {0} for the operand, shape) of one instruction word, or None.
    shape: None (one word), 'value', 'jump' (the operand word is a jump offset)."""
    if word > 0xFFFF:
        return None
    prefix, op, ra, rb = word >> 12, word >> 8 & 0xF, word >> 4 & 0xF, word & 0xF
    if prefix in (1, 3, 5, 7):
        name, shape = ALU.get((prefix & 3, op), (None, None))
        if name is None:
            return None
        imm = prefix & 4
        if shape == "alu1":
            return (f"{name} #{{0}}", "value") if imm else (f"{name} R{rb}", None)
        return (f"{name} R{ra}, #{{0}}", "value") if imm else (f"{name} R{ra}, R{rb}", None)
    if prefix == 2:
        name = GROUP2.get(word >> 8)
        if name is None:
            return None
        return (name, None) if enc.SYSTEM_OPS[name][1] == "none" else (f"{name} R{rb}", None)
    if prefix != 0:
        return None
    name, shape = SYSTEM[op]
    if shape == "none":
        return name, None
    if shape == "ra_rb":
        return f"{name} R{ra}, R{rb}", None
    if shape == "rb":
        return f"{name} R{rb}", None
    if shape == "rb_value":
        return f"{name} R{rb}, {{0}}", "value"
    if shape == "jump":
        return f"{name} {{0}}", "jump"
    if shape == "flagjump":
        flags = "".join(f for f in FLAG_ORDER if rb & enc.FLAGS[f])
        return (f"{name} {flags}, {{0}}", "jump") if flags else None
    if shape == "comm":
        return f"COMM {COMM_NAMES[ra & 3]}, R{rb}", None
    if shape == "stk":
        if ra not in STK_NAMES:
            return None
        sub, reg = STK_NAMES[ra]
        return (f"STK {sub}, R{rb}", None) if reg else (f"STK {sub}", None)
    return None


_checked = {}


def exact(word):
    """decode(word) when the assembler writes that text as exactly this word."""
    if word not in _checked:
        d = decode(word)
        if d is not None:
            text = d[0].format("x" if d[1] == "jump" else "0")
            try:
                obj, _ = assemble(f".global start\nstart:\nx:\n{text}\n", "<check>")
                if obj.rom[0] != word:
                    d = None
            except AsmErrors:
                d = None
        _checked[word] = d
    return _checked[word]


# ------------------------------------------------------------- the walk

class Disassembler:
    def __init__(self, image, map_labels=(), raw=False):
        self.im = image
        self.raw = raw
        self.map = {}                   # address -> name (ROM/code labels of the map)
        self.ram_map = {}               # address -> name (RAM labels of the map)
        for address, section, name in map_labels:
            in_code = image.code[0] <= address < image.code[1] or address == image.code[1]
            if in_code and (section == "rom" or image.kind == "exe"):
                self.map.setdefault(address, name)
            elif image.ram[0] <= address < image.ram[1]:
                self.ram_map.setdefault(address, name)
        self.items = {}                 # address -> (kind, size): ("ins", 1|2) or ("word", 1)

    def in_code(self, a):
        return self.im.code[0] <= a < self.im.code[1]

    def find_code(self):
        im = self.im
        todo = [im.start, *im.vectors.values()]
        todo += [a for a, n in self.map.items() if not DATA_LABEL.match(n)]
        seen = set()
        self.entries = set()
        while todo:
            a = todo.pop()
            if self.in_code(a) and a not in seen:
                self.entries.add(a)
            while self.in_code(a) and a not in seen:
                d = exact(im.word(a))
                size = 2 if d and d[1] else 1
                if d is None or a + size > im.code[1] or any(
                        a + i in self.items for i in range(size)) or (size == 2 and a + 1 in seen):
                    break
                seen.add(a)
                self.items[a] = ("ins", size)
                if size == 2:
                    self.items[a + 1] = ("operand", 0)
                text, shape = d
                name = text.split()[0]
                if shape == "jump":
                    todo.append(_target({a + 1: im.word(a + 1)}, a + 1))
                    if name == "RJMP":
                        break
                elif name == "DATA" and self.in_code(a + 2):
                    nxt = exact(im.word(a + 2))
                    reg = text.split()[1].rstrip(",")
                    if nxt and (nxt[0] == f"JMRB {reg}" or (reg == "R0" and nxt[0] == "STK PUSH")):
                        todo.append(im.word(a + 1))     # a call's target, or its return address
                elif name in ("JMRB", "HALT"):
                    break
                a += size
        for a in range(*im.code):
            self.items.setdefault(a, ("word", 1))

    # ---------------------------------------------------------- references

    def is_address(self, at, value):
        """Whether the word at `at` (an operand or a .word) holds an address,
        and whether that is a guess."""
        im = self.im
        if im.relocs is not None:
            return at in im.relocs, False
        kind = self.items.get(at, ("",))[0]
        if kind == "operand" and im.word(at - 1) >> 8 != 0x03:
            return False, False         # an ALU immediate: a number
        if value in self.map or value in self.ram_map or im.ram[0] <= value < im.ram[1]:
            return True, True
        if kind != "operand":
            return False, False         # a .word: only the map's names
        if self.in_code(value) and (value in self.entries or self.looks_like_string(value)):
            return True, True           # DATA Rn, x: x is code found, or a string
        return False, False

    def looks_like_string(self, a):
        im = self.im
        b = a
        while self.in_code(b) and self.items.get(b, ("",))[0] == "word" and \
                (32 <= im.word(b) < 127 or im.word(b) in (9, 10)):
            b += 1
        return b - a >= 2 and self.in_code(b) and im.word(b) == 0

    def collect(self):
        """The addresses that need a label, and the CALL/RET sequences to fold."""
        im = self.im
        self.refs = set()
        self.folded = {}                # address -> (text, size)
        self.inner = set()              # addresses inside a folded sequence
        if not self.raw:
            self.fold()
        for a, (kind, size) in sorted(self.items.items()):
            if a in self.inner and a not in self.folded:
                continue
            if a in self.folded:
                target = self.folded[a][2]
                if target is not None:
                    self.refs.add(target)
                continue
            if kind == "ins" and size == 2:
                text, shape = exact(im.word(a))
                if shape == "jump":
                    self.refs.add(_target({a + 1: im.word(a + 1)}, a + 1))
                elif self.is_address(a + 1, im.word(a + 1))[0]:
                    self.refs.add(im.word(a + 1))
            elif kind == "word" and self.is_address(a, im.word(a))[0]:
                self.refs.add(im.word(a))

    def fold(self):
        """CALL target[, n] and RET, when their words are exactly the expansion
        and nothing else points inside them."""
        im = self.im
        w = lambda a: im.word(a) if self.in_code(a) else None
        ins = lambda a: self.items.get(a, ("",))[0] == "ins"
        pointed = {}                    # address -> how many words point there
        for a, (kind, size) in self.items.items():
            t = None
            if kind == "ins" and size == 2:
                if exact(im.word(a))[1] == "jump":
                    t = _target({a + 1: im.word(a + 1)}, a + 1)
                elif self.is_address(a + 1, im.word(a + 1))[0]:
                    t = im.word(a + 1)
            elif kind == "word" and self.is_address(a, im.word(a))[0]:
                t = im.word(a)
            if t is not None:
                pointed[t] = pointed.get(t, 0) + 1
        for name_at in list(self.map) + list(self.ram_map):
            pointed[name_at] = pointed.get(name_at, 0) + 1

        def clear(a, end, ret=None):
            return all(pointed.get(x, 0) <= (1 if x == ret else 0) for x in range(a + 1, end))
        for a in sorted(a for a, (k, _) in self.items.items() if k == "ins"):
            if a in self.inner:
                continue
            # CALL: DATA R0, ret ; STK PUSH ; STK CALL ; DATA R0, target ; JMRB R0
            if (w(a) == 0x0300 and w(a + 2) == 0x0B00 and w(a + 3) == 0x0B20
                    and w(a + 4) == 0x0300 and w(a + 6) == 0x0A00 and w(a + 1) == a + 7
                    and all(ins(a + i) for i in (2, 3, 4, 6))
                    and clear(a, a + 7)
                    and (im.relocs is None or {a + 1, a + 5} <= im.relocs)):
                target = w(a + 5)
                if not (self.in_code(target) and ins(target)):
                    continue
                n, end = 0, a + 7
                # CALL target, n: CPY R0, R15 ; STK POP x n ; CPY R15, R0
                if w(end) == 0x0E0F and ins(end):
                    k = end + 1
                    while w(k) == 0x0B10 and ins(k):
                        k += 1
                    if w(k) == 0x0EF0 and ins(k) and k > end + 1 and clear(a, k + 1, ret=end):
                        n, end = k - end - 1, k + 1
                text = f"CALL {{0}}, {n}" if n else "CALL {0}"
                self.folded[a] = (text, end - a, target)
                self.inner.update(range(a, end))
                continue
            # RET: CPY R0, R15 ; STK RET ; STK POP ; CPY R0, R14 ; CPY R15, R0 ; JMRB R14
            if [w(a + i) for i in range(6)] == [0x0E0F, 0x0B30, 0x0B10, 0x0E0E, 0x0EF0, 0x0A0E] \
                    and all(ins(a + i) for i in range(6)) and clear(a, a + 6):
                self.folded[a] = ("RET", 6, None)
                self.inner.update(range(a, a + 6))

    # ------------------------------------------------------------- naming

    def name_labels(self):
        im = self.im
        names, used = {}, set()

        def give(a, name):
            base, k = name, 2
            while name in used:
                name = f"{base}__{k}"
                k += 1
            used.add(name)
            names[a] = name

        give(im.start, "start")
        for name, a in im.vectors.items():
            if a not in names:
                give(a, name)
        self.aliases = {name: a for name, a in im.vectors.items() if names.get(a) != name}
        for a, name in sorted(self.map.items()):
            if a not in names and a not in self.inner and name not in ("start", *linker.VECTORS):
                give(a, name)
        for a, name in sorted(self.ram_map.items()):
            if a not in names and name not in ("start", *linker.VECTORS):
                give(a, name)
        for a in sorted(self.refs):
            if a in names or a in im.extra or (a in self.inner and a not in self.folded):
                continue
            if self.in_code(a) and self.items.get(a, ("operand",))[0] != "operand" and \
                    (a not in self.inner or a in self.folded):
                give(a, f"L_{a:x}")
            elif im.ram[0] <= a < im.ram[1]:
                give(a, f"R_{a:x}")
        self.names = names

    def value(self, at, v):
        """A word's value as written: a label (+ k), or a number; and a note."""
        im = self.im
        is_addr, guess = self.is_address(at, v)
        if not is_addr:
            return self.number(v), ""
        note = "  ; guess" if guess else ""
        if v in self.names:
            return self.names[v], note
        if v in im.extra:
            self.externs.add(im.extra[v])
            return im.extra[v], note
        if self.in_code(v) or v == im.code[1]:
            below = [a for a in self.names if im.code[0] <= a <= v]
        elif im.ram[0] <= v < im.ram[1]:
            below = [a for a in self.names if im.ram[0] <= a <= v]
        else:
            below = []
        if below:
            a = max(below)
            return f"{self.names[a]} + {v - a}", note
        return self.number(v), ""

    @staticmethod
    def number(v):
        return f"0x{v:X}" if v > 9 else str(v)

    # -------------------------------------------------------------- output

    def text(self, title):
        im = self.im
        self.find_code()
        self.collect()
        self.name_labels()
        self.externs = set()
        body = []
        a = im.code[0]
        while a < im.code[1]:
            if a in self.names:
                body.append(f"{self.names[a]}:")
            for name, at in self.aliases.items():
                if at == a:
                    body.append(f"{name}:")
            if a in self.folded:
                text, size, target = self.folded[a]
                body.append(f"        {text if target is None else text.format(self.value_of_target(target))}")
                a += size
                continue
            kind, size = self.items[a]
            w = im.word(a)
            if kind == "ins":
                text, shape = exact(w)
                if size == 1:
                    body.append(f"        {text}")
                elif shape == "jump":
                    target = _target({a + 1: im.word(a + 1)}, a + 1)
                    ref = self.label_expr(target)
                    if ref is None:         # a jump the assembler can't write: as words
                        body.append(f"        .word 0x{w:X}, 0x{im.word(a + 1):X}  ; {text.format('?')}")
                    else:
                        body.append(f"        {text.format(ref)}")
                else:
                    val, note = self.value(a + 1, im.word(a + 1))
                    body.append(f"        {text.format(val)}{note}")
                a += size
                continue
            s = self.string_at(a)
            if s is not None:
                text, n = s
                body.append(f"        .string {text}")
                a += n
                continue
            val, note = self.value(a, w)
            body.append(f"        .word {val}{note or self.char_note(w)}")
            a += 1
        for name, at in self.aliases.items():       # a handler at the very end
            if at == im.code[1]:
                body.append(f"{name}:")
        ram = self.ram_text()
        head = [f"; {title}", f"; disassembled by `python compiler/src/asm disasm`"]
        if im.kind == "rom":
            head.append(f"; a ROM image: rebuild with `python compiler/src/asm build`")
            if im.stack != linker.STACK_WORDS:
                head.append(f"; linked with a stack of {im.stack} words: link(stack_words={im.stack})")
        else:
            head.append(f"; a program for the OS (TEX2): link(base=0x{im.origin:X}, "
                        f"exe_stack={im.stack}), exe_bytes(program, {im.region})")
        globals_ = ["start"] + [n for n in linker.VECTORS if n in im.vectors]
        head.append(f".global {', '.join(globals_)}")
        if self.externs:
            head.append(f".extern {', '.join(sorted(self.externs))}")
        return "\n".join(head + [""] + body + ram) + "\n"

    def value_of_target(self, target):
        return self.label_expr(target) or self.number(target)

    def label_expr(self, target):
        if target in self.names:
            return self.names[target]
        below = [a for a in self.names if self.im.code[0] <= a <= target and self.in_code(a)]
        if not self.in_code(target) or not below:
            return None
        a = max(below)
        return f"{self.names[a]} + {target - a}"

    def string_at(self, a):
        """`.string "..."` for printable chars then a 0, with no label inside."""
        im = self.im
        chars = []
        b = a
        while b < im.code[1] and self.items.get(b, ("",))[0] == "word" and (b == a or b not in self.names):
            c = im.word(b)
            if c == 0:
                break
            if not (32 <= c < 127 or c in (9, 10)):
                return None
            chars.append(c)
            b += 1
        if len(chars) < 2 or b >= im.code[1] or im.word(b) != 0 or b in self.names \
                or self.items.get(b, ("",))[0] != "word" or any(self.is_address(x, im.word(x))[0]
                                                                  for x in range(a, b + 1)):
            return None
        esc = {9: "\\t", 10: "\\n", 34: '\\"', 92: "\\\\"}
        return '"' + "".join(esc.get(c, chr(c)) for c in chars) + '"', len(chars) + 1

    @staticmethod
    def char_note(w):
        return f"  ; '{chr(w)}'" if 33 <= w < 127 and w != 39 else ""

    def ram_text(self):
        im = self.im
        start, end = im.ram
        if end <= start:
            return []
        lines = ["", ".ram"]
        at = start
        for a in sorted(x for x in self.names if start <= x < end):
            if a > at:
                lines.append(f"        .space {a - at}")
            lines.append(f"{self.names[a]}:")
            at = a
        if end > at:
            lines.append(f"        .space {end - at}")
        return lines


def disassemble_file(path, map_path=None, raw=False):
    path = Path(path)
    data = path.read_bytes()
    if data[:4] == b"TEX2":
        image = image_from_exe(data)
    elif data[:4] == b"TEX1":
        raise AsmError(f"{path}: a TEX1 program (the old format): only TEX2 is read")
    else:
        image = image_from_rom(read_rom(path))
    labels = read_map(map_path) if map_path else ()
    return Disassembler(image, labels, raw).text(path.name)


def round_trip(path, map_path=None, raw=False):
    """Disassemble, assemble and link again; None when the words are the same,
    else what differs (the self-checks use it)."""
    path = Path(path)
    data = path.read_bytes()
    image = image_from_exe(data) if data[:4] == b"TEX2" else image_from_rom(read_rom(path))
    text = Disassembler(image, read_map(map_path) if map_path else (), raw).text(path.name)
    try:
        obj, _ = assemble(text, path.name + ".dis.asm")
        if image.kind == "rom":
            program = linker.link([obj], stack_words=image.stack)
            got, want = program.rom, image.words
        else:
            program = linker.link([obj], base=image.origin, exe_stack=image.stack)
            got = (program.rom, sorted(program.relocs), program.ram_used, program.stack_words)
            want = (image.words, sorted(r - image.origin for r in image.relocs),
                    image.ram[1] - image.ram[0], image.stack)
    except AsmErrors as e:
        return f"{path.name}: {e.errors[0]}"
    if got == want:
        return None
    if image.kind == "rom":
        bad = next(i for i in range(max(len(got), len(want)))
                   if i >= len(got) or i >= len(want) or got[i] != want[i])
        return f"{path.name}: word {bad:#x} differs ({len(got)} words, want {len(want)})"
    return f"{path.name}: the program differs"
