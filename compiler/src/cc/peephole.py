"""Small clean-ups on a function's instructions, after code generation.

The code generator works one expression at a time, so it repeats some
work. These passes remove it, each one only where it can't change what the
program does:

    known values   DATA Rn, x is dropped when Rn already holds x (the same
                   DATA earlier in the straight-line code, nothing changed
                   Rn since); CPY Ra, Rb is dropped when Rb already equals Ra
    stack reload   STK GET, Rn straight after STK SET, Rn is dropped: R0 already
                   holds what SET stored (neither touches the flags)
    flags          TEST R0 (or TEST Rn just after CPY R0, Rn) is dropped
                   right after an integer ALU instruction that set the flags
                   for R0, when the next jump tests only Z and/or N
    jumps          a jump to the very next instruction goes; a jump to a
                   jump goes straight to the end; "RJF x, A / RJMP B / A:"
                   becomes "RJNF x, B / A:"; code after RJMP/RET/JMRB that no
                   label leads to goes

Items are the code generator's tuples: ("ins", op, args), ("label", name),
("comment", text), ("loc", file, line) (a .loc: treated like a comment),
("raw", text).
"""

import re

ALU_INT = {"ADD", "SUB", "MULT", "DIV", "MOD", "AND", "OR", "XOR", "NOT", "NEG",
           "++", "--", "INC", "DEC", "SHL", "SHR", "TEST"}
ALU_ALL = ALU_INT | {"CMP", "FADD", "FSUB", "FMULT", "FDIV", "FCMP", "FNEG", "FLOAT", "INT"}
JUMPS = {"RJMP", "RJF", "RJNF"}
ENDS = {"RJMP", "RET", "JMRB", "HALT"}


def written(item):
    """Registers an instruction may change (None: any register)."""
    kind = item[0]
    if kind != "ins":
        return None if kind == "raw" else set()
    op, args = item[1], item[2]
    if op in ALU_ALL:
        return {0}
    if op in ("CPY", "LD"):
        return {reg(args[1])}
    if op in ("DATA", "ADDR"):
        return {reg(args[0])}
    if op in ("ALD",):
        return {0}
    if op == "STK":
        return {0} if args[0] in ("GET", "POP") else set()
    if op == "COMM":
        return {reg(args[1])} if args[0] == "INDATA" else set()
    if op == "SAVE":
        return {0}
    if op == "RESTORE":
        return {reg(a) for a in args} | {0, 15}
    if op in ("CALL", "RET", "JMRB"):
        return None
    return set()


def reg(text):
    return int(text.strip()[1:])


def optimize(items):
    items = known_values(items)
    items = stack_reload(items)
    items = flags(items)
    for _ in range(4):
        before = len(items)
        items = jumps(items)
        items = unreachable(items)
        if len(items) == before:
            break
    return items


def known_values(items):
    """Drop DATA/CPY that would put a value in a register that already has it."""
    out = []
    value = {}            # register -> the DATA operand it holds
    same = {}             # register -> set of registers known equal to it

    def forget(r):
        value.pop(r, None)
        for other in same.pop(r, set()):
            same.get(other, set()).discard(r)

    def forget_all():
        value.clear()
        same.clear()

    for item in items:
        kind = item[0]
        if kind == "label" or kind == "raw":
            forget_all()
            out.append(item)
            continue
        if kind != "ins":
            out.append(item)
            continue
        op, args = item[1], item[2]
        if op == "DATA":
            r = reg(args[0])
            if value.get(r) == args[1]:
                continue                          # already there
            forget(r)
            value[r] = args[1]
            out.append(item)
            continue
        if op == "CPY":
            a, b = reg(args[0]), reg(args[1])
            if a == b or b in same.get(a, set()):
                continue                          # b already equals a
            forget(b)
            if a in value:
                value[b] = value[a]
            group = same.get(a, set()) | {a}
            for r in group:
                same.setdefault(r, set()).add(b)
            same[b] = set(group)
            out.append(item)
            continue
        changed = written(item)
        if changed is None:
            forget_all()
        else:
            for r in changed:
                forget(r)
        out.append(item)
    return out


def stack_reload(items):
    """Drop STK GET, Rn when the instruction just before it is STK SET, Rn."""
    out = []
    last = None           # the last real instruction, if only comments came since
    for item in items:
        if item[0] == "ins":
            if (item[1] == "STK" and item[2][0] == "GET" and last is not None
                    and last[1] == "STK" and last[2][0] == "SET"
                    and reg(last[2][1]) == reg(item[2][1])):
                continue                              # R0 already holds that word
            last = item
        elif item[0] not in ("comment", "loc"):
            last = None                               # a label or raw text: someone may jump in
        out.append(item)
    return out


def flags(items):
    """Drop a TEST whose flags the previous ALU instruction already set."""
    out = []
    for i, item in enumerate(items):
        if item[0] == "ins" and item[1] == "TEST" and out:
            target = reg(item[2][0])
            nxt = next_ins(items, i + 1)
            tests_zn = nxt is not None and nxt[1] in ("RJF", "RJNF") and \
                set(nxt[2][0].upper()) <= {"Z", "N"}
            if tests_zn:
                prev = out[-1]
                if target == 0 and prev[0] == "ins" and prev[1] in ALU_INT:
                    continue
                if (prev[0] == "ins" and prev[1] == "CPY" and reg(prev[2][0]) == 0
                        and reg(prev[2][1]) == target and len(out) >= 2
                        and out[-2][0] == "ins" and out[-2][1] in ALU_INT):
                    continue
        out.append(item)
    return out


def next_ins(items, i):
    while i < len(items):
        if items[i][0] == "ins":
            return items[i]
        if items[i][0] in ("label", "raw"):
            return None
        i += 1
    return None


def jumps(items):
    # where each label is
    target_of = {}
    for i, item in enumerate(items):
        if item[0] == "label":
            target_of[item[1]] = i

    def final(label, seen=None):
        """Follow a chain of labels that just jump elsewhere."""
        seen = seen or set()
        while label in target_of and label not in seen:
            seen.add(label)
            j = target_of[label] + 1
            while j < len(items) and items[j][0] in ("label", "comment", "loc"):
                j += 1
            if j < len(items) and items[j][0] == "ins" and items[j][1] == "RJMP":
                label = items[j][2][0]
                continue
            break
        return label

    out = []
    i = 0
    while i < len(items):
        item = items[i]
        if item[0] == "ins" and item[1] in JUMPS:
            op, args = item[1], item[2]
            dest = final(args[-1])
            if dest != args[-1]:
                item = ("ins", op, tuple(args[:-1]) + (dest,))
                args = item[2]
            # jump to the next instruction
            if labels_before_next(items, i + 1, dest):
                i += 1
                continue
            # RJF x, A / RJMP B / A:  ->  RJNF x, B / A:
            if op in ("RJF", "RJNF") and len(args[0]) == 1:
                j = i + 1
                while j < len(items) and items[j][0] in ("comment", "loc"):
                    j += 1
                if j < len(items) and items[j][0] == "ins" and items[j][1] == "RJMP" and \
                        labels_before_next(items, j + 1, dest):
                    flipped = "RJNF" if op == "RJF" else "RJF"
                    out.append(("ins", flipped, (args[0], final(items[j][2][0]))))
                    i = j + 1
                    continue
        out.append(item)
        i += 1
    return out


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def referenced_labels(items):
    """Every name used anywhere: jump targets, DATA operands (return
    addresses, tables), raw lines (jump tables, asm)."""
    used = set()
    for item in items:
        if item[0] == "ins":
            for a in item[2]:
                used.update(_NAME.findall(str(a)))
        elif item[0] == "raw":
            used.update(_NAME.findall(item[1]))
    return used


def labels_before_next(items, i, label):
    """Is 'label' among the labels between position i and the next instruction?"""
    while i < len(items):
        item = items[i]
        if item[0] == "label":
            if item[1] == label:
                return True
        elif item[0] not in ("comment", "loc"):
            return False
        i += 1
    return False


def unreachable(items):
    """Drop instructions after RJMP/RET/JMRB/HALT until the next label.
    (HALT can be resumed, so code after it stays.)"""
    used = referenced_labels(items)
    out = []
    dead = False
    for item in items:
        kind = item[0]
        if kind == "label":
            if dead and item[1] not in used:
                continue                          # a label nothing jumps to, in dead code
            dead = False
            out.append(item)
            continue
        if kind == "raw":
            dead = False                           # jump tables, asm: keep
            out.append(item)
            continue
        if dead:
            continue
        out.append(item)
        if kind == "ins" and item[1] in ("RJMP", "RET", "JMRB"):
            dead = True
    return out
