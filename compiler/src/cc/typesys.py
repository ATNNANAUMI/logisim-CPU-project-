"""C types for a word-addressed machine.

Every scalar (char, short, int, long, float, double, pointers) is one 32-bit
word, so sizeof(char) == sizeof(int) == 1 and CHAR_BIT is 32. Sizes are
counted in words. Nothing needs padding: every type has alignment 1.

double and long double are the same 32-bit float as float: the CPU has only
a float32 unit.
"""

from dataclasses import dataclass

INTEGER_KINDS = ("bool", "char", "short", "int", "long", "llong", "enum")
FLOAT_KINDS = ("float", "double", "ldouble")
RANK = {"bool": 0, "char": 1, "short": 2, "int": 3, "enum": 3, "long": 4, "llong": 5}
WORD_BITS = 32


@dataclass(eq=False)
class Member:
    name: str | None
    ty: "Type"
    offset: int = 0              # word offset inside the struct
    tok: object = None
    bit_width: int = -1          # -1: not a bit-field
    bit_offset: int = 0          # first bit inside its word (bit 0 = lowest)
    index: int = 0

    @property
    def is_bitfield(self):
        return self.bit_width >= 0


class Type:
    """One C type. Struct and union types are shared objects (they get their
    members later when the definition is seen); a qualified or typedef'd copy
    of one reads size and members from the original, so it is never stale."""

    _FIELDS = ("kind", "_size", "unsigned", "base", "array_len", "_members",
               "_is_flexible", "tag", "return_ty", "params", "param_names",
               "variadic", "has_proto", "is_const", "is_volatile", "origin",
               "enum_values")

    def __init__(self, kind, size=1, unsigned=False, base=None, array_len=-1):
        self.kind = kind
        self._size = size
        self.unsigned = unsigned
        self.base = base                # pointer target, array element
        self.array_len = array_len      # -1: [] with no size yet
        self._members = []
        self._is_flexible = False
        self.tag = None
        self.return_ty = None
        self.params = []                # parameter types
        self.param_names = []           # name tokens (or None)
        self.variadic = False
        self.has_proto = True           # False for 'int f()' (no parameter list)
        self.is_const = False
        self.is_volatile = False
        self.origin = None              # the type this is a copy of
        self.enum_values = {}

    def _shared(self):
        """The struct/union object that holds size and members."""
        t = self
        while t.origin is not None and t.kind in ("struct", "union"):
            t = t.origin
        return t

    @property
    def size(self):
        return self._shared()._size

    @size.setter
    def size(self, value):
        self._shared()._size = value

    @property
    def members(self):
        return self._shared()._members

    @members.setter
    def members(self, value):
        self._shared()._members = value

    @property
    def is_flexible(self):
        return self._shared()._is_flexible

    @is_flexible.setter
    def is_flexible(self, value):
        self._shared()._is_flexible = value

    # ------------------------------------------------------------ questions
    @property
    def is_integer(self):
        return self.kind in INTEGER_KINDS

    @property
    def is_float(self):
        return self.kind in FLOAT_KINDS

    @property
    def is_arith(self):
        return self.is_integer or self.is_float

    @property
    def is_ptr_like(self):
        """Pointers and arrays: things with a base type you can index."""
        return self.kind in ("ptr", "array")

    @property
    def is_scalar(self):
        return self.is_arith or self.kind == "ptr"

    @property
    def is_struct(self):
        return self.kind in ("struct", "union")

    @property
    def is_func(self):
        return self.kind == "func"

    @property
    def is_void(self):
        return self.kind == "void"

    def __repr__(self):
        return f"<{type_name(self)}>"


# ------------------------------------------------------------------ constructors

def _basic(kind, unsigned=False):
    return Type(kind, 1, unsigned)


def void_type():
    return Type("void", -1)


def bool_type():
    return _basic("bool", True)


def char_type(unsigned=False):
    return _basic("char", unsigned)


def short_type(unsigned=False):
    return _basic("short", unsigned)


def int_type(unsigned=False):
    return _basic("int", unsigned)


def long_type(unsigned=False):
    return _basic("long", unsigned)


def float_type():
    return _basic("float")


def double_type():
    return _basic("double")


def ldouble_type():
    return _basic("ldouble")


def enum_type():
    return Type("enum", 1)


def pointer_to(base):
    # Addresses fit in 25 bits, so pointers compare correctly as signed ints
    # (the cheaper compare on this CPU).
    return Type("ptr", 1, False, base=base)


def array_of(base, length):
    size = base.size * length if length >= 0 and base.size >= 0 else -1
    return Type("array", size, base=base, array_len=length)


def func_type(return_ty):
    t = Type("func", 1)
    t.return_ty = return_ty
    return t


def struct_type(kind="struct"):
    return Type(kind, -1)


def copy_type(ty):
    """A copy that remembers the original (for qualifiers and for a flexible
    struct whose last member got its length from an initializer)."""
    t = Type(ty.kind)
    for f in Type._FIELDS:
        setattr(t, f, getattr(ty, f))
    t.params = list(ty.params)
    t.param_names = list(ty.param_names)
    t.origin = ty
    return t


def qualified(ty, const=False, volatile=False):
    if not const and not volatile:
        return ty
    t = copy_type(ty)
    t.is_const = ty.is_const or const
    t.is_volatile = ty.is_volatile or volatile
    return t


def unqualified(ty):
    if not ty.is_const and not ty.is_volatile:
        return ty
    t = copy_type(ty)
    t.is_const = t.is_volatile = False
    return t


# ------------------------------------------------------------------ conversions

def promote(ty):
    """Integer promotion. With 32-bit chars and shorts, unsigned char and
    unsigned short promote to unsigned int (int can't hold all their values)."""
    if ty.kind in ("bool", "char", "short"):
        return int_type(ty.unsigned and ty.kind != "bool")
    if ty.kind == "enum":
        return int_type()
    return ty


def common_type(a, b):
    """The usual arithmetic conversions."""
    if a.is_float or b.is_float:
        order = {"float": 0, "double": 1, "ldouble": 2}
        fa = order.get(a.kind, -1)
        fb = order.get(b.kind, -1)
        return _basic(a.kind if fa >= fb else b.kind)
    a, b = promote(a), promote(b)
    kind = a.kind if RANK[a.kind] >= RANK[b.kind] else b.kind
    return _basic(kind, a.unsigned or b.unsigned)


def is_compatible(a, b):
    """Type compatibility (for redeclarations, pointer assignment and _Generic)."""
    if a is b:
        return True
    if a.origin is not None:
        return is_compatible(a.origin, b)
    if b.origin is not None:
        return is_compatible(a, b.origin)
    if a.kind != b.kind:
        return False
    if a.kind in ("bool", "char", "short", "int", "long", "llong"):
        return a.unsigned == b.unsigned
    if a.kind in FLOAT_KINDS or a.kind == "void":
        return True
    if a.kind == "ptr":
        return is_compatible(a.base, b.base)
    if a.kind == "func":
        if not is_compatible(a.return_ty, b.return_ty):
            return False
        if not a.has_proto or not b.has_proto:
            return True
        if a.variadic != b.variadic or len(a.params) != len(b.params):
            return False
        return all(is_compatible(x, y) for x, y in zip(a.params, b.params))
    if a.kind == "array":
        if not is_compatible(a.base, b.base):
            return False
        return a.array_len < 0 or b.array_len < 0 or a.array_len == b.array_len
    return False                       # distinct structs, unions and enums


# ------------------------------------------------------------------ names

def type_name(ty, inner=""):
    """C spelling of a type, for messages: 'int *', 'char [10]', 'int (*)(int)'."""
    quals = ("const " if ty.is_const else "") + ("volatile " if ty.is_volatile else "")
    k = ty.kind
    if k == "ptr":
        return type_name(ty.base, "*" + (" " + quals.strip() if quals else "") + inner
                         if ty.base.kind not in ("array", "func") or not inner
                         else "(*" + inner + ")")
    if k == "array":
        n = "" if ty.array_len < 0 else str(ty.array_len)
        inside = f"({inner})" if inner.startswith("*") else inner
        return type_name(ty.base, f"{inside}[{n}]")
    if k == "func":
        params = ", ".join(type_name(p) for p in ty.params)
        if ty.variadic:
            params += ", ..." if params else "..."
        if not ty.params and not ty.variadic and ty.has_proto:
            params = "void"
        inside = f"({inner})" if inner.startswith("*") else inner
        return type_name(ty.return_ty, f"{inside}({params})")
    names = {"void": "void", "bool": "_Bool", "char": "char", "short": "short",
             "int": "int", "long": "long", "llong": "long long", "float": "float",
             "double": "double", "ldouble": "long double"}
    if k in names:
        base = names[k]
        if ty.unsigned and k not in ("bool",):
            base = "unsigned " + base
    elif k in ("struct", "union", "enum"):
        base = f"{k} {ty.tag}" if ty.tag else f"{k} <anonymous>"
    else:
        base = k
    base = quals + base
    if inner:
        return base + (" " if not inner.startswith(("[", "(")) else " ") + inner
    return base
