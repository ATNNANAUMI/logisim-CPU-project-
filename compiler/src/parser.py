from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from lexer import Token, TokenType


# ─────────────────────────────────────────────────────────────────────────────
#  AST Node definitions
#  Every node kind from the grammar diagram gets its own dataclass.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ASTNode:
    """Base class — all nodes inherit from this."""
    def pretty(self, indent: int = 0) -> str:
        raise NotImplementedError


# ── Literals / leaf nodes ─────────────────────────────────────────────────────

@dataclass
class IntLiteral(ASTNode):
    value: str
    def pretty(self, indent=0): return "  "*indent + f"INT({self.value})"

@dataclass
class StringLiteral(ASTNode):
    value: str
    def pretty(self, indent=0): return "  "*indent + f'STR("{self.value}")'

@dataclass
class Identifier(ASTNode):
    name: str
    def pretty(self, indent=0): return "  "*indent + f"ID({self.name})"


# ── Expressions ───────────────────────────────────────────────────────────────

@dataclass
class BinaryExpr(ASTNode):
    op:    str
    left:  ASTNode
    right: ASTNode
    def pretty(self, indent=0):
        pad = "  " * indent
        return (f"{pad}BinaryExpr({self.op})\n"
                f"{self.left.pretty(indent+1)}\n"
                f"{self.right.pretty(indent+1)}")

@dataclass
class UnaryExpr(ASTNode):
    op:      str
    operand: ASTNode
    prefix:  bool = True          # True = prefix  False = postfix
    def pretty(self, indent=0):
        pad = "  " * indent
        pos = "pre" if self.prefix else "post"
        return (f"{pad}UnaryExpr({self.op}, {pos})\n"
                f"{self.operand.pretty(indent+1)}")

@dataclass
class TernaryExpr(ASTNode):
    condition:   ASTNode
    then_branch: ASTNode
    else_branch: ASTNode
    def pretty(self, indent=0):
        pad = "  " * indent
        return (f"{pad}TernaryExpr(?:)\n"
                f"{self.condition.pretty(indent+1)}\n"
                f"{self.then_branch.pretty(indent+1)}\n"
                f"{self.else_branch.pretty(indent+1)}")

@dataclass
class IndexExpr(ASTNode):
    obj:   ASTNode
    index: ASTNode
    def pretty(self, indent=0):
        pad = "  " * indent
        return (f"{pad}IndexExpr\n"
                f"{self.obj.pretty(indent+1)}\n"
                f"{self.index.pretty(indent+1)}")

@dataclass
class CallExpr(ASTNode):
    callee: ASTNode
    args:   list[ASTNode] = field(default_factory=list)
    def pretty(self, indent=0):
        pad = "  " * indent
        args_str = "\n".join(a.pretty(indent+1) for a in self.args)
        return f"{pad}CallExpr\n{self.callee.pretty(indent+1)}" + (
            f"\n{args_str}" if args_str else "")

@dataclass
class GroupExpr(ASTNode):
    expr: ASTNode
    def pretty(self, indent=0):
        pad = "  " * indent
        return f"{pad}Group\n{self.expr.pretty(indent+1)}"


# ── Statements ────────────────────────────────────────────────────────────────

@dataclass
class ExprStatement(ASTNode):
    expr: ASTNode
    def pretty(self, indent=0):
        pad = "  " * indent
        return f"{pad}ExprStmt\n{self.expr.pretty(indent+1)}"

@dataclass
class ReturnStatement(ASTNode):
    value: ASTNode
    def pretty(self, indent=0):
        pad = "  " * indent
        return f"{pad}Return\n{self.value.pretty(indent+1)}"

@dataclass
class IfStatement(ASTNode):
    condition:   ASTNode
    then_branch: ASTNode
    else_branch: Optional[ASTNode] = None
    def pretty(self, indent=0):
        pad = "  " * indent
        s = (f"{pad}If\n"
             f"{self.condition.pretty(indent+1)}\n"
             f"{self.then_branch.pretty(indent+1)}")
        if self.else_branch:
            s += f"\n{pad}Else\n{self.else_branch.pretty(indent+1)}"
        return s

@dataclass
class WhileStatement(ASTNode):
    condition: ASTNode
    body:      ASTNode
    def pretty(self, indent=0):
        pad = "  " * indent
        return (f"{pad}While\n"
                f"{self.condition.pretty(indent+1)}\n"
                f"{self.body.pretty(indent+1)}")

@dataclass
class VarDef(ASTNode):
    """var x = expr  (one declarator; multiple handled by VarDefList)"""
    name:  str
    value: Optional[ASTNode] = None
    def pretty(self, indent=0):
        pad = "  " * indent
        s = f"{pad}VarDef({self.name})"
        if self.value:
            s += f"\n{self.value.pretty(indent+1)}"
        return s

@dataclass
class VarDefList(ASTNode):
    """var x = 1, y = 2, z;"""
    declarations: list[VarDef] = field(default_factory=list)
    def pretty(self, indent=0):
        pad = "  " * indent
        inner = "\n".join(d.pretty(indent+1) for d in self.declarations)
        return f"{pad}VarDefList\n{inner}"

@dataclass
class Block(ASTNode):
    statements: list[ASTNode] = field(default_factory=list)
    def pretty(self, indent=0):
        pad = "  " * indent
        inner = "\n".join(s.pretty(indent+1) for s in self.statements)
        return f"{pad}Block\n{inner}"

@dataclass
class NoOpStatement(ASTNode):
    def pretty(self, indent=0): return "  "*indent + "NoOp"


# ── Top-level ─────────────────────────────────────────────────────────────────

@dataclass
class FunctionDecl(ASTNode):
    name:   str
    params: list[str]
    body:   ASTNode
    def pretty(self, indent=0):
        pad = "  " * indent
        return (f"{pad}Function({self.name})"
                f"  params={self.params}\n"
                f"{self.body.pretty(indent+1)}")

@dataclass
class Library(ASTNode):
    functions: list[FunctionDecl] = field(default_factory=list)
    def pretty(self, indent=0):
        return "Library\n" + "\n".join(f.pretty(indent+1) for f in self.functions)


# ─────────────────────────────────────────────────────────────────────────────
#  Parser
# ─────────────────────────────────────────────────────────────────────────────

class ParseError(Exception):
    pass


class Parser:
    """
    Recursive-descent parser.

    Grammar (matches the railroad diagram in the image):

      library    → function* EOF
      function   → IDENTIFIER ":" statement
                   (with optional parameter list before ":")
      statement  → block
                 | "if" "(" expression ")" statement ("else" statement)?
                 | "while" "(" expression ")" statement
                 | "return" expression ";"
                 | "var" IDENTIFIER ("=" expression)?
                              ("," IDENTIFIER ("=" expression)?)* ";"
                 | expression ";"
                 | ";"                      ← no-op

      expression → assignment
      assignment → ternary ("=" assignment)?   ← right-associative
      ternary    → logical_or ("?" expression ":" ternary)?
      logical_or → logical_and ("||" logical_and)*
      logical_and→ equality   ("&&" equality)*
      equality   → relational (("==" | "!=") relational)*
      relational → additive   (("<"|">"|"<="|">=") additive)*
      additive   → multiplicative (("+" | "-") multiplicative)*
      multiplicative → unary  (("*" | "/" | "%") unary)*
      unary      → ("!" | "-" | "&" | "*" | "++" | "--") unary
                 | postfix
      postfix    → primary ("++" | "--" | "[" expression "]"
                             | "(" arglist ")" )*
      primary    → INTEGER_LITERAL
                 | STRING_LITERAL
                 | IDENTIFIER
                 | "(" expression ")"
    """

    def __init__(self, tokens: list[Token]):
        # strip EOF sentinel duplicates, keep exactly one at the end
        self.tokens = [t for t in tokens if t.type != TokenType.SPECIAL
                       or t.value == "EOF"]
        # collapse string quote triplets  " content " → one STRING token
        self.tokens = self._merge_string_tokens(self.tokens)
        self.pos = 0

    # ── token stream helpers ─────────────────────────────────────────────────

    @staticmethod
    def _merge_string_tokens(tokens: list[Token]) -> list[Token]:
        """
        The lexer produces  SEP(") STRING(content) SEP(")  for string literals.
        Collapse those triplets into a single STRING token so the parser never
        has to deal with them.
        """
        out: list[Token] = []
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if (t.type == TokenType.SEPARATOR and t.value == '"'
                    and i + 2 < len(tokens)
                    and tokens[i+2].type == TokenType.SEPARATOR
                    and tokens[i+2].value == '"'):
                out.append(Token(TokenType.STRING, tokens[i+1].value))
                i += 3
            else:
                out.append(t)
                i += 1
        return out

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return Token(TokenType.SPECIAL, "EOF")

    def _advance(self) -> Token:
        tok = self._peek()
        self.pos += 1
        return tok

    def _check(self, value: str) -> bool:
        return self._peek().value == value

    def _match(self, *values: str) -> Optional[Token]:
        """Consume and return the current token if its value is in `values`."""
        if self._peek().value in values:
            return self._advance()
        return None

    def _expect(self, value: str) -> Token:
        if self._peek().value != value:
            raise ParseError(
                f"Expected {value!r} but got {self._peek().value!r} "
                f"at token index {self.pos}"
            )
        return self._advance()

    def _is_identifier(self) -> bool:
        t = self._peek()
        return t.type in (TokenType.IDENTIFIER,
                          TokenType.CONTROL_FLOW,
                          TokenType.TYPE_SPECIFIER,
                          TokenType.TYPE_QUALIFIER,
                          TokenType.STORAGE_CLASS,
                          TokenType.STRUCTURE,
                          TokenType.MEMORY,
                          TokenType.BUILTIN_FUNCTION,
                          TokenType.BUILTIN_TYPE,
                          TokenType.C11_KEYWORD,
                          TokenType.KEYWORD)

    # ── top-level ────────────────────────────────────────────────────────────

    def parse(self) -> Library:
        functions: list[FunctionDecl] = []
        while self._peek().value != "EOF":
            functions.append(self._parse_function())
        return Library(functions)

    # ── function  ────────────────────────────────────────────────────────────
    #  IDENTIFIER  ("," IDENTIFIER)*  ":"  statement

    def _parse_function(self) -> FunctionDecl:
        name = self._peek().value
        if not self._is_identifier():
            raise ParseError(f"Expected function name, got {name!r}")
        self._advance()

        params: list[str] = []
        # optional parameter list  (identifiers separated by ",")
        while self._is_identifier() or self._check(","):
            if self._check(","):
                self._advance()
            if self._is_identifier():
                params.append(self._peek().value)
                self._advance()
            else:
                break

        self._expect(":")
        body = self._parse_statement()
        return FunctionDecl(name, params, body)

    # ── statement ────────────────────────────────────────────────────────────

    def _parse_statement(self) -> ASTNode:
        tok = self._peek()

        # compound / block
        if tok.value == "{":
            return self._parse_block()

        # if statement
        if tok.value == "if":
            return self._parse_if()

        # while statement
        if tok.value == "while":
            return self._parse_while()

        # return statement
        if tok.value == "return":
            self._advance()
            expr = self._parse_expression()
            self._expect(";")
            return ReturnStatement(expr)

        # var definition
        if tok.value == "var":
            return self._parse_var_def()

        # no-op  ";"
        if tok.value == ";":
            self._advance()
            return NoOpStatement()

        # expression statement
        expr = self._parse_expression()
        self._expect(";")
        return ExprStatement(expr)

    def _parse_block(self) -> Block:
        self._expect("{")
        stmts: list[ASTNode] = []
        while not self._check("}") and self._peek().value != "EOF":
            stmts.append(self._parse_statement())
        self._expect("}")
        return Block(stmts)

    def _parse_if(self) -> IfStatement:
        self._expect("if")
        self._expect("(")
        cond = self._parse_expression()
        self._expect(")")
        then = self._parse_statement()
        else_branch = None
        if self._check("else"):
            self._advance()
            else_branch = self._parse_statement()
        return IfStatement(cond, then, else_branch)

    def _parse_while(self) -> WhileStatement:
        self._expect("while")
        self._expect("(")
        cond = self._parse_expression()
        self._expect(")")
        body = self._parse_statement()
        return WhileStatement(cond, body)

    def _parse_var_def(self) -> VarDefList:
        self._expect("var")
        decls: list[VarDef] = []

        while True:
            if not self._is_identifier():
                raise ParseError(f"Expected variable name, got {self._peek().value!r}")
            name = self._advance().value
            value = None
            if self._match("="):
                value = self._parse_expression()
            decls.append(VarDef(name, value))
            if not self._match(","):
                break

        self._expect(";")
        return VarDefList(decls)

    # ── expression hierarchy ─────────────────────────────────────────────────
    #  Each level calls the next-higher-precedence level.

    def _parse_expression(self) -> ASTNode:
        return self._parse_assignment()

    def _parse_assignment(self) -> ASTNode:
        left = self._parse_ternary()
        if self._check("="):
            op = self._advance().value
            right = self._parse_assignment()   # right-associative
            return BinaryExpr(op, left, right)
        return left

    def _parse_ternary(self) -> ASTNode:
        cond = self._parse_logical_or()
        if self._match("?"):
            then = self._parse_expression()
            self._expect(":")
            else_ = self._parse_ternary()
            return TernaryExpr(cond, then, else_)
        return cond

    def _parse_logical_or(self) -> ASTNode:
        left = self._parse_logical_and()
        while (op := self._match("||")):
            left = BinaryExpr(op.value, left, self._parse_logical_and())
        return left

    def _parse_logical_and(self) -> ASTNode:
        left = self._parse_equality()
        while (op := self._match("&&")):
            left = BinaryExpr(op.value, left, self._parse_equality())
        return left

    def _parse_equality(self) -> ASTNode:
        left = self._parse_relational()
        while (op := self._match("==", "!=")):
            left = BinaryExpr(op.value, left, self._parse_relational())
        return left

    def _parse_relational(self) -> ASTNode:
        left = self._parse_additive()
        while (op := self._match("<", ">", "<=", ">=")):
            left = BinaryExpr(op.value, left, self._parse_additive())
        return left

    def _parse_additive(self) -> ASTNode:
        left = self._parse_multiplicative()
        while (op := self._match("+", "-")):
            left = BinaryExpr(op.value, left, self._parse_multiplicative())
        return left

    def _parse_multiplicative(self) -> ASTNode:
        left = self._parse_unary()
        while (op := self._match("*", "/", "%")):
            left = BinaryExpr(op.value, left, self._parse_unary())
        return left

    def _parse_unary(self) -> ASTNode:
        # prefix operators
        op = self._match("!", "-", "&", "*", "++", "--", "+")
        if op:
            operand = self._parse_unary()
            return UnaryExpr(op.value, operand, prefix=True)
        return self._parse_postfix()

    def _parse_postfix(self) -> ASTNode:
        node = self._parse_primary()

        while True:
            # post-increment / post-decrement
            op = self._match("++", "--")
            if op:
                node = UnaryExpr(op.value, node, prefix=False)
                continue

            # index  expression "[" expression "]"
            if self._match("["):
                idx = self._parse_expression()
                self._expect("]")
                node = IndexExpr(node, idx)
                continue

            # function call  expression "(" arglist ")"
            if self._match("("):
                args: list[ASTNode] = []
                if not self._check(")"):
                    args.append(self._parse_expression())
                    while self._match(","):
                        args.append(self._parse_expression())
                self._expect(")")
                node = CallExpr(node, args)
                continue

            break

        return node

    def _parse_primary(self) -> ASTNode:
        tok = self._peek()

        # integer literal
        if tok.type == TokenType.INTEGER:
            self._advance()
            return IntLiteral(tok.value)

        # float literal (treat as int-literal node for now, easily extendable)
        if tok.type == TokenType.FLOAT:
            self._advance()
            return IntLiteral(tok.value)   # reuse node; rename to NumLiteral if desired

        # string literal  (already merged by _merge_string_tokens)
        if tok.type == TokenType.STRING:
            self._advance()
            return StringLiteral(tok.value)

        # identifier (any word that isn't a statement-level keyword)
        if self._is_identifier():
            self._advance()
            return Identifier(tok.value)

        # grouped expression  "(" expression ")"
        if tok.value == "(":
            self._advance()
            expr = self._parse_expression()
            self._expect(")")
            return GroupExpr(expr)

        raise ParseError(
            f"Unexpected token {tok.value!r} (type={tok.type.name}) "
            f"at position {self.pos}"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Convenience helpers
# ─────────────────────────────────────────────────────────────────────────────

def parse_tokens(tokens: list[Token]) -> Library:
    return Parser(tokens).parse()


def parse_string(source: str, keyword_file: str | None = None) -> Library:
    """Lex + parse in one call.  keyword_file is optional."""
    import os
    from lexer import Lexer
    if keyword_file is None:
        here = os.path.dirname(os.path.abspath(__file__))
        kf = os.path.join(here, "keywords.json")
        keyword_file = kf if os.path.exists(kf) else None
    tokens = Lexer(source, keyword_file).tokenize()
    return Parser(tokens).parse()


# ─────────────────────────────────────────────────────────────────────────────
#  Demo
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    samples = [
        # simple assignment  →  =( a, 5 )
        ("a = 5 ;", "simple assignment"),

        # arithmetic
        ("x = a + b * c ;", "arithmetic precedence"),

        # function call
        ("result = add(1, 2) ;", "function call"),

        # ternary
        ("y = x > 0 ? x : -x ;", "ternary"),

        # full mini-program
        ("""
        factorial n :
        {
            if (n <= 1) return 1 ;
            return n * factorial(n - 1) ;
        }

        main :
        {
            var result = factorial(5) ;
            var msg = "done" ;
            result ;
        }
        """, "full program"),
    ]

    for source, label in samples:
        print(f"\n{'─'*60}")
        print(f"  {label}")
        print(f"  source: {source.strip()}")
        print("─"*60)
        try:
            ast = parse_string(source)
            print(ast.pretty())
        except ParseError as e:
            print(f"  ParseError: {e}")
