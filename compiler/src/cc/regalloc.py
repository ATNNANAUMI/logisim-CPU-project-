"""Which local variables live in registers, and which of them a call must keep.

A local (or parameter) can live in a register when it is a scalar whose
address is never taken. Each use counts 8 times more for every loop around
it. A register saves about 2 instructions per use, but costs about 4 at
every call where the variable must be kept (and 3 to load a parameter), so
a variable gets a register only when that adds up to a gain; the biggest
gains get the registers.

Every register may be changed by a call, so a register variable that is
still needed after a call is saved around it. "Still needed" is decided
conservatively from the shape of the code: the variable is used later in
the function (or in the same statement as the call), or it is used inside
a loop that contains the call. A function with labels (goto) keeps every
register variable at every call.
"""

from nodes import Node

MAX_DEPTH = 3


class Analysis:
    def __init__(self, fn):
        self.fn = fn
        self.weight = {}          # var -> weighted use count
        self.positions = {}       # var -> list of statement positions
        self.loops = []           # (first, last) statement positions
        self.calls = []           # (node, position): funcall nodes, asm statements
        self.call_weight = {}     # id(node) -> 8^loop depth of the call
        self.has_labels = False
        self.pos = 0
        self.stmt(fn.body, 0)

    # ------------------------------------------------------------ walking
    def stmt(self, s, depth):
        k = s.kind
        if k == "block":
            for c in s.body:
                self.stmt(c, depth)
        elif k in ("expr_stmt", "return"):
            self.pos += 1
            if s.lhs is not None:
                self.expr(s.lhs, depth)
        elif k == "if":
            self.pos += 1
            self.expr(s.cond, depth)
            self.stmt(s.then, depth)
            if s.els is not None:
                self.stmt(s.els, depth)
        elif k == "for":
            first = self.pos + 1
            if s.init is not None:
                self.stmt(s.init, depth)
            self.pos += 1
            if s.cond is not None:
                self.expr(s.cond, depth + 1)
            self.stmt(s.then, depth + 1)
            self.pos += 1
            if s.inc is not None:
                self.expr(s.inc, depth + 1)
            self.loops.append((first, self.pos))
        elif k == "do":
            first = self.pos + 1
            self.stmt(s.then, depth + 1)
            self.pos += 1
            self.expr(s.cond, depth + 1)
            self.loops.append((first, self.pos))
        elif k == "switch":
            self.pos += 1
            self.expr(s.cond, depth)
            self.stmt(s.then, depth)
        elif k == "case":
            self.stmt(s.lhs, depth)
        elif k == "label":
            self.has_labels = True
            self.stmt(s.lhs, depth)
        elif k == "asm":
            self.pos += 1
            self.calls.append((s, self.pos))
            self.call_weight[id(s)] = 8 ** min(depth, MAX_DEPTH)
        # goto (also break/continue): nothing to record

    def expr(self, e, depth):
        if e is None:
            return
        k = e.kind
        if k == "var" and e.var.is_local:
            v = e.var
            self.weight[v] = self.weight.get(v, 0) + 8 ** min(depth, MAX_DEPTH)
            self.positions.setdefault(v, []).append(self.pos)
        elif k == "funcall":
            self.calls.append((e, self.pos))
            self.call_weight[id(e)] = 8 ** min(depth, MAX_DEPTH)
        elif k == "memzero":
            v = e.var
            self.positions.setdefault(v, []).append(self.pos)
        for name in ("lhs", "rhs", "cond", "then", "els", "func"):
            child = getattr(e, name, None)
            if isinstance(child, Node):
                self.expr(child, depth)
        for a in getattr(e, "args", None) or ():
            if isinstance(a, Node):
                self.expr(a, depth)

    # ------------------------------------------------------------ results
    def live_at(self, var, pos):
        """Might var be needed after a call at statement position pos?"""
        if self.has_labels:
            return True
        uses = self.positions.get(var, ())
        if any(u >= pos for u in uses):
            return True
        for first, last in self.loops:
            if first <= pos <= last and any(first <= u <= last for u in uses):
                return True
        return False


USE_GAIN = 2           # instructions a register saves per use
CALL_COST = 4          # SAVE + RESTORE of one register around a call
PARAM_COST = 3         # loading a parameter into its register


def candidates(fn, analysis):
    """Locals that may live in a register, biggest gain first."""
    gains = {}
    for v in fn.locals:
        if v is fn.ret_ptr or v.addr_taken:
            continue
        ty = v.ty
        if not ty.is_scalar or ty.is_volatile or ty.size != 1:
            continue
        w = analysis.weight.get(v, 0)
        if w == 0:
            continue
        gain = USE_GAIN * w - (PARAM_COST if v.is_param else 0)
        for node, pos in analysis.calls:
            if analysis.live_at(v, pos):
                gain -= CALL_COST * analysis.call_weight[id(node)]
        if gain > 0:
            gains[v] = gain
    return sorted(gains, key=lambda v: -gains[v])


def assigned_vars(node, regvars):
    """Register variables that an expression assigns to (directly)."""
    found = set()

    def walk(e):
        if e is None:
            return
        if e.kind in ("assign", "assign_op", "preinc", "predec", "postinc", "postdec"):
            target = e.lhs
            if target.kind == "var" and target.var in regvars:
                found.add(target.var)
        for name in ("lhs", "rhs", "cond", "then", "els", "func"):
            child = getattr(e, name, None)
            if isinstance(child, Node):
                walk(child)
        for a in getattr(e, "args", None) or ():
            if isinstance(a, Node):
                walk(a)

    walk(node)
    return found
