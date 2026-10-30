"""The syntax tree the parser builds and the code generator reads.

A Node is one expression or statement. Its fields depend on its kind:

expressions (every one has .ty once the parser is done with it)
    num         .val (int, or float for float types)
    var         .var (an Obj)
    neg not bitnot addr deref        .lhs
    add sub mul div mod bitand bitor bitxor shl shr eq ne lt le
    logand logor comma               .lhs .rhs
    assign                           .lhs .rhs
    assign_op                        .op (one of the binary kinds) .lhs .rhs
    preinc predec postinc postdec    .lhs .step (int, or 1.0 for floats)
    cond                             .cond .then .els
    member                           .lhs .member
    cast                             .lhs (converted to .ty)
    funcall                          .func (the callee expression) .args .func_ty
                                     .ret_buf (an Obj, for a struct result)
    memzero                          .var: zero a local variable
    builtin                          .name .args (va_start, va_arg, ...)

statements
    block       .body (list)
    expr_stmt   .lhs
    if          .cond .then .els
    for         .init .cond .inc .then .brk .cont  (while loops too)
    do          .then .cond .brk .cont
    switch      .cond .then .cases (list of case nodes) .default .brk
    case        .lo .hi .label .lhs (the statement after the label)
    return      .lhs (or None)
    goto        .label (unique label name)
    label       .label .lhs
    asm         .text
"""

from dataclasses import dataclass, field


class Node:
    def __init__(self, kind, tok, **fields):
        self.kind = kind
        self.tok = tok
        self.ty = None
        self.__dict__.update(fields)

    def __repr__(self):
        extra = ""
        if self.kind == "num":
            extra = f" {self.val}"
        elif self.kind == "var":
            extra = f" {self.var.name}"
        return f"<Node {self.kind}{extra} {self.ty}>"


@dataclass(eq=False)
class Obj:
    """A variable or a function."""
    name: str
    ty: object
    tok: object = None
    is_local: bool = False

    # locals
    is_param: bool = False
    offset: int = 0              # frame index relative to EBP (set by the code generator)
    addr_taken: bool = False

    # globals and functions
    asm_name: str = ""           # the assembly label
    is_static: bool = False
    is_definition: bool = False
    is_tentative: bool = False
    is_function: bool = False
    init_data: list | None = None    # words: int, or (label, addend)
    in_rom: bool = False         # const data placed in ROM
    is_string: bool = False      # a string literal
    asm_text: str | None = None  # a file-scope asm("...") block

    # functions
    params: list = field(default_factory=list)
    locals: list = field(default_factory=list)
    body: object = None
    ret_ptr: object = None       # hidden parameter for struct results
    is_referenced: bool = False
    labels: dict = field(default_factory=dict)
