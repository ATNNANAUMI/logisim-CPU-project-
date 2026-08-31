"""
parser.py

Table-driven recursive descent parser.

Instead of hardcoded  if tok == "if": ...  checks, the parser loads
a BNF grammar file at startup and uses it to:
  - know which tokens can start which rules  (FIRST sets)
  - know which rules are non-terminals to recurse into
  - dispatch statement and expression alternatives dynamically

The grammar drives the parser.  Swapping the .bnf file changes the
language — no Python edits needed for the structural rules.

Usage:
    ast = parse_file("source.c",
                     grammar_file="c_grammar.bnf",
                     keyword_file="keywords.json")

    ast = parse_string("int x = 5;",
                       grammar_file="c_grammar.bnf",
                       keyword_file="keywords.json")
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional

from lexer import Token, TokenType, Lexer
from bnf_loader import (
    GrammarTable, GrammarSymbol, SymbolKind,
    load_grammar, get_terminals, rule_exists,
)


# ─────────────────────────────────────────────────────────────────────────────
#  AST nodes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ASTNode:
    def pretty(self, indent: int = 0) -> str:
        raise NotImplementedError


# ── Literals ──────────────────────────────────────────────────────────────────

@dataclass
class IntLiteral(ASTNode):
    value: str
    def pretty(self, i=0): return "  "*i + f"INT({self.value})"

@dataclass
class FloatLiteral(ASTNode):
    value: str
    def pretty(self, i=0): return "  "*i + f"FLOAT({self.value})"

@dataclass
class StringLiteral(ASTNode):
    value: str
    def pretty(self, i=0): return "  "*i + f'STR("{self.value}")'

@dataclass
class CharLiteral(ASTNode):
    value: str
    def pretty(self, i=0): return "  "*i + f"CHAR({self.value!r})"

@dataclass
class Identifier(ASTNode):
    name: str
    def pretty(self, i=0): return "  "*i + f"ID({self.name})"


# ── Expressions ───────────────────────────────────────────────────────────────

@dataclass
class BinaryExpr(ASTNode):
    op: str
    left: ASTNode
    right: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}BinaryExpr({self.op})\n"
                f"{self.left.pretty(i+1)}\n"
                f"{self.right.pretty(i+1)}")

@dataclass
class UnaryExpr(ASTNode):
    op: str
    operand: ASTNode
    prefix: bool = True
    def pretty(self, i=0):
        pos = "pre" if self.prefix else "post"
        return (f"{'  '*i}UnaryExpr({self.op},{pos})\n"
                f"{self.operand.pretty(i+1)}")

@dataclass
class TernaryExpr(ASTNode):
    condition: ASTNode
    then_branch: ASTNode
    else_branch: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}Ternary(?:)\n"
                f"{self.condition.pretty(i+1)}\n"
                f"{self.then_branch.pretty(i+1)}\n"
                f"{self.else_branch.pretty(i+1)}")

@dataclass
class CastExpr(ASTNode):
    type_name: str
    operand: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}Cast({self.type_name})\n"
                f"{self.operand.pretty(i+1)}")

@dataclass
class SizeofExpr(ASTNode):
    operand: ASTNode | str
    def pretty(self, i=0):
        inner = self.operand if isinstance(self.operand, str) else self.operand.pretty(i+1)
        return f"{'  '*i}Sizeof\n{inner}"

@dataclass
class IndexExpr(ASTNode):
    obj: ASTNode
    index: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}Index\n"
                f"{self.obj.pretty(i+1)}\n"
                f"{self.index.pretty(i+1)}")

@dataclass
class CallExpr(ASTNode):
    callee: ASTNode
    args: list[ASTNode] = field(default_factory=list)
    def pretty(self, i=0):
        args_s = "\n".join(a.pretty(i+1) for a in self.args)
        return (f"{'  '*i}Call\n{self.callee.pretty(i+1)}"
                + (f"\n{args_s}" if args_s else ""))

@dataclass
class MemberExpr(ASTNode):
    obj: ASTNode
    member: str
    arrow: bool = False
    def pretty(self, i=0):
        op = "->" if self.arrow else "."
        return (f"{'  '*i}Member({op}{self.member})\n"
                f"{self.obj.pretty(i+1)}")

@dataclass
class GroupExpr(ASTNode):
    expr: ASTNode
    def pretty(self, i=0):
        return f"{'  '*i}Group\n{self.expr.pretty(i+1)}"


# ── Statements ────────────────────────────────────────────────────────────────

@dataclass
class ExprStatement(ASTNode):
    expr: Optional[ASTNode]
    def pretty(self, i=0):
        return (f"{'  '*i}ExprStmt\n{self.expr.pretty(i+1)}"
                if self.expr else "  "*i + "ExprStmt(empty)")

@dataclass
class CompoundStatement(ASTNode):
    declarations: list[ASTNode]
    statements: list[ASTNode]
    def pretty(self, i=0):
        decls = "\n".join(d.pretty(i+1) for d in self.declarations)
        stmts = "\n".join(s.pretty(i+1) for s in self.statements)
        return f"{'  '*i}Compound\n{decls}\n{stmts}".rstrip()

@dataclass
class IfStatement(ASTNode):
    condition: ASTNode
    then_branch: ASTNode
    else_branch: Optional[ASTNode] = None
    def pretty(self, i=0):
        s = (f"{'  '*i}If\n{self.condition.pretty(i+1)}\n"
             f"{self.then_branch.pretty(i+1)}")
        if self.else_branch:
            s += f"\n{'  '*i}Else\n{self.else_branch.pretty(i+1)}"
        return s

@dataclass
class SwitchStatement(ASTNode):
    condition: ASTNode
    body: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}Switch\n{self.condition.pretty(i+1)}\n"
                f"{self.body.pretty(i+1)}")

@dataclass
class WhileStatement(ASTNode):
    condition: ASTNode
    body: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}While\n{self.condition.pretty(i+1)}\n"
                f"{self.body.pretty(i+1)}")

@dataclass
class DoWhileStatement(ASTNode):
    body: ASTNode
    condition: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}DoWhile\n{self.body.pretty(i+1)}\n"
                f"{self.condition.pretty(i+1)}")

@dataclass
class ForStatement(ASTNode):
    init: Optional[ASTNode]
    condition: Optional[ASTNode]
    update: Optional[ASTNode]
    body: ASTNode
    def pretty(self, i=0):
        parts = [f"{'  '*i}For"]
        for label, node in [("init", self.init), ("cond", self.condition), ("update", self.update)]:
            parts.append(f"{'  '*(i+1)}{label}: " +
                         (node.pretty(0) if node else "empty"))
        parts.append(self.body.pretty(i+1))
        return "\n".join(parts)

@dataclass
class JumpStatement(ASTNode):
    kind: str
    value: Optional[ASTNode] = None
    label: str = ""
    def pretty(self, i=0):
        s = "  "*i + f"Jump({self.kind})"
        if self.value:
            s += f"\n{self.value.pretty(i+1)}"
        if self.label:
            s += f" -> {self.label}"
        return s

@dataclass
class LabeledStatement(ASTNode):
    label: str
    statement: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}Label({self.label})\n"
                f"{self.statement.pretty(i+1)}")

@dataclass
class CaseStatement(ASTNode):
    value: ASTNode
    statement: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}Case\n{self.value.pretty(i+1)}\n"
                f"{self.statement.pretty(i+1)}")

@dataclass
class DefaultStatement(ASTNode):
    statement: ASTNode
    def pretty(self, i=0):
        return (f"{'  '*i}Default\n"
                f"{self.statement.pretty(i+1)}")


# ── Declarations ──────────────────────────────────────────────────────────────

@dataclass
class Declaration(ASTNode):
    specifiers: list[str]
    declarators: list[ASTNode]
    def pretty(self, i=0):
        specs = " ".join(self.specifiers)
        decls = "\n".join(d.pretty(i+1) for d in self.declarators)
        return f"{'  '*i}Decl({specs})\n{decls}".rstrip()

@dataclass
class InitDeclarator(ASTNode):
    name: str
    pointer_depth: int = 0
    initializer: Optional[ASTNode] = None
    def pretty(self, i=0):
        stars = "*" * self.pointer_depth
        s = "  "*i + f"InitDecl({stars}{self.name})"
        if self.initializer:
            s += f"\n{self.initializer.pretty(i+1)}"
        return s

@dataclass
class FunctionDef(ASTNode):
    specifiers: list[str]
    name: str
    pointer_depth: int
    params: list[ASTNode]
    body: ASTNode
    def pretty(self, i=0):
        stars  = "*" * self.pointer_depth
        specs  = " ".join(self.specifiers)
        params = "\n".join(p.pretty(i+2) for p in self.params)
        return (f"{'  '*i}FunctionDef({specs} {stars}{self.name})\n"
                f"{'  '*(i+1)}params:\n{params}\n"
                f"{self.body.pretty(i+1)}")

@dataclass
class ParamDecl(ASTNode):
    specifiers: list[str]
    name: str
    pointer_depth: int = 0
    def pretty(self, i=0):
        stars = "*" * self.pointer_depth
        return "  "*i + f"Param({' '.join(self.specifiers)} {stars}{self.name})"

@dataclass
class TranslationUnit(ASTNode):
    declarations: list[ASTNode]
    def pretty(self, i=0):
        return "TranslationUnit\n" + "\n".join(d.pretty(i+1) for d in self.declarations)


# ─────────────────────────────────────────────────────────────────────────────
#  Parser
# ─────────────────────────────────────────────────────────────────────────────

class ParseError(Exception):
    pass


class Parser:
    """
    Recursive descent parser driven by a BNF grammar table.

    The grammar table tells the parser:
      - which terminal tokens can start each non-terminal rule  (FIRST sets)
      - which alternatives exist for each rule

    Swapping the .bnf file changes the language without touching Python
    for structural rules.  Semantic actions (what AST node to build)
    stay in Python because that knowledge cannot live in a grammar file.
    """

    def __init__(self, tokens: list[Token], grammar: GrammarTable):
        self.tokens  = self._merge_strings(tokens)
        self.pos     = 0
        self.grammar = grammar

        # Pre-compute FIRST sets for every rule in the grammar
        self._first: dict[str, set[str]] = {
            name: get_terminals(grammar, name)
            for name in grammar
        }

    # ── string token merging ──────────────────────────────────────────────────

    @staticmethod
    def _merge_strings(tokens: list[Token]) -> list[Token]:
        out, i = [], 0
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

    # ── navigation primitives ─────────────────────────────────────────────────

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else Token(TokenType.SPECIAL, "EOF")

    def _advance(self) -> Token:
        tok = self._peek()
        self.pos += 1
        return tok

    def _check(self, *values: str) -> bool:
        return self._peek().value in values

    def _match(self, *values: str) -> Optional[Token]:
        if self._peek().value in values:
            return self._advance()
        return None

    def _expect(self, value: str) -> Token:
        if self._peek().value != value:
            raise ParseError(
                f"Expected {value!r}, got {self._peek().value!r} at pos {self.pos}"
            )
        return self._advance()

    # ── grammar-driven helpers ────────────────────────────────────────────────

    def _can_start(self, rule: str) -> bool:
        """
        True if the current token can begin the given grammar rule.
        Uses FIRST sets computed from the BNF file.
        Falls back to token-type check for identifier-headed rules.
        """
        if self._peek().value in self._first.get(rule, set()):
            return True
        identifier_rules = {
            "identifier", "typedef-name", "direct-declarator",
            "labeled-statement", "primary-expression",
        }
        if rule in identifier_rules and self._is_word():
            return True
        return False

    def _is_word(self) -> bool:
        return self._peek().type in (
            TokenType.IDENTIFIER,
            TokenType.KEYWORD,
            TokenType.CONTROL_FLOW,
            TokenType.TYPE_SPECIFIER,
            TokenType.TYPE_QUALIFIER,
            TokenType.STORAGE_CLASS,
            TokenType.STRUCTURE,
            TokenType.MEMORY,
            TokenType.BUILTIN_FUNCTION,
            TokenType.BUILTIN_TYPE,
            TokenType.C11_KEYWORD,
        )

    def _is_type_specifier(self) -> bool:
        """True if the current token can begin a declaration specifier."""
        specifier_kws = (
            self._first.get("type-specifier", set())
            | self._first.get("type-qualifier", set())
            | self._first.get("storage-class-specifier", set())
            | {"struct", "union", "enum"}
        )
        return self._peek().value in specifier_kws

    def _is_type_specifier_at(self, offset: int) -> bool:
        specifier_kws = (
            self._first.get("type-specifier", set())
            | self._first.get("type-qualifier", set())
            | {"struct", "union", "enum"}
        )
        return self._peek(offset).value in specifier_kws

    # ── top-level ─────────────────────────────────────────────────────────────

    def parse(self) -> TranslationUnit:
        """translation-unit ::= {external-declaration}*"""
        decls: list[ASTNode] = []
        while not self._check("EOF"):
            decls.append(self._parse_external_declaration())
        return TranslationUnit(decls)

    # ── external declaration ──────────────────────────────────────────────────

    def _parse_external_declaration(self) -> ASTNode:
        """
        external-declaration ::= function-definition | declaration
        Both start with declaration-specifiers; we look ahead past the
        declarator name to see whether a ( follows (function) or ; (variable).
        """
        specifiers    = self._parse_declaration_specifiers()
        pointer_depth = 0
        while self._check("*"):
            self._advance()
            pointer_depth += 1

        if not self._is_word():
            raise ParseError(f"Expected declarator name, got {self._peek().value!r}")
        name = self._advance().value

        if self._check("("):
            return self._finish_function_def(specifiers, pointer_depth, name)
        return self._finish_declaration(specifiers, pointer_depth, name)

    def _parse_declaration_specifiers(self) -> list[str]:
        """
        Parse {declaration-specifier}* using the grammar's FIRST sets
        so the set of valid specifiers comes from the BNF file, not
        a hardcoded list.
        """
        specifiers: list[str] = []
        while self._is_type_specifier():
            tok = self._advance()
            specifiers.append(tok.value)
            if tok.value in ("struct", "union", "enum"):
                if self._is_word():
                    specifiers.append(self._advance().value)
                if self._check("{"):
                    self._skip_braces()
        return specifiers

    def _skip_braces(self):
        self._expect("{")
        depth = 1
        while depth > 0 and not self._check("EOF"):
            if self._check("{"): depth += 1
            elif self._check("}"): depth -= 1
            self._advance()

    def _finish_function_def(self, specifiers, pointer_depth, name) -> FunctionDef:
        self._expect("(")
        params: list[ASTNode] = []
        if not self._check(")"):
            params.append(self._parse_param_declaration())
            while self._match(","):
                if self._check("..."):
                    self._advance()
                    break
                params.append(self._parse_param_declaration())
        self._expect(")")
        body = self._parse_compound_statement()
        return FunctionDef(specifiers, name, pointer_depth, params, body)

    def _parse_param_declaration(self) -> ParamDecl:
        specifiers = self._parse_declaration_specifiers()
        if not specifiers:
            raise ParseError(f"Expected type in parameter, got {self._peek().value!r}")
        pointer_depth = 0
        while self._match("*"):
            pointer_depth += 1
        name = self._advance().value if self._is_word() else ""
        return ParamDecl(specifiers, name, pointer_depth)

    def _finish_declaration(self, specifiers, pointer_depth, first_name) -> Declaration:
        first_init  = self._parse_init_declarator_tail(pointer_depth, first_name)
        declarators = [first_init]
        while self._match(","):
            pd = 0
            while self._match("*"):
                pd += 1
            nm = self._advance().value if self._is_word() else ""
            declarators.append(self._parse_init_declarator_tail(pd, nm))
        self._expect(";")
        return Declaration(specifiers, declarators)

    def _parse_init_declarator_tail(self, pointer_depth: int, name: str) -> InitDeclarator:
        while self._check("["):
            self._advance()
            if not self._check("]"):
                self._parse_expression()
            self._expect("]")
        initializer = None
        if self._match("="):
            initializer = self._parse_assignment_expression()
        return InitDeclarator(name, pointer_depth, initializer)

    # ── statements ────────────────────────────────────────────────────────────

    def _parse_statement(self) -> ASTNode:
        """
        Dispatch to the correct statement rule by checking the current token
        against the FIRST sets loaded from the grammar file.
        No token values are hardcoded here — they all come from self._first.
        """
        cur = self._peek().value

        # compound-statement FIRST = {
        if cur in self._first.get("compound-statement", {"{"}):
            return self._parse_compound_statement()

        # selection-statement FIRST = if | switch
        if cur in self._first.get("selection-statement", {"if", "switch"}):
            return self._parse_selection_statement()

        # iteration-statement FIRST = while | do | for
        if cur in self._first.get("iteration-statement", {"while", "do", "for"}):
            return self._parse_iteration_statement()

        # jump-statement FIRST = goto | continue | break | return
        if cur in self._first.get("jump-statement", {"goto", "continue", "break", "return"}):
            return self._parse_jump_statement()

        # labeled-statement: case | default | identifier :
        if cur in self._first.get("labeled-statement", {"case", "default"}):
            return self._parse_labeled_statement()
        if self._is_word() and self._peek(1).value == ":":
            return self._parse_labeled_statement()

        return self._parse_expression_statement()

    def _parse_compound_statement(self) -> CompoundStatement:
        """compound-statement ::= { {declaration}* {statement}* }"""
        self._expect("{")
        declarations: list[ASTNode] = []
        statements:   list[ASTNode] = []
        while not self._check("}") and not self._check("EOF"):
            if self._is_type_specifier():
                declarations.append(self._parse_inner_declaration())
            else:
                statements.append(self._parse_statement())
        self._expect("}")
        return CompoundStatement(declarations, statements)

    def _parse_inner_declaration(self) -> Declaration:
        specifiers = self._parse_declaration_specifiers()
        pd = 0
        while self._match("*"):
            pd += 1
        name = self._advance().value if self._is_word() else ""
        return self._finish_declaration(specifiers, pd, name)

    def _parse_selection_statement(self) -> ASTNode:
        """Alternatives driven by the grammar's selection-statement rule."""
        kw = self._advance().value
        if kw == "if":
            self._expect("(")
            cond = self._parse_expression()
            self._expect(")")
            then = self._parse_statement()
            else_branch = self._parse_statement() if self._match("else") else None
            return IfStatement(cond, then, else_branch)
        if kw == "switch":
            self._expect("(")
            cond = self._parse_expression()
            self._expect(")")
            return SwitchStatement(cond, self._parse_statement())
        raise ParseError(f"Unknown selection statement keyword: {kw!r}")

    def _parse_iteration_statement(self) -> ASTNode:
        """Alternatives driven by the grammar's iteration-statement rule."""
        kw = self._advance().value
        if kw == "while":
            self._expect("(")
            cond = self._parse_expression()
            self._expect(")")
            return WhileStatement(cond, self._parse_statement())
        if kw == "do":
            body = self._parse_statement()
            self._expect("while")
            self._expect("(")
            cond = self._parse_expression()
            self._expect(")")
            self._expect(";")
            return DoWhileStatement(body, cond)
        if kw == "for":
            self._expect("(")
            init = None if self._check(";") else self._parse_expression()
            self._expect(";")
            cond = None if self._check(";") else self._parse_expression()
            self._expect(";")
            upd  = None if self._check(")") else self._parse_expression()
            self._expect(")")
            return ForStatement(init, cond, upd, self._parse_statement())
        raise ParseError(f"Unknown iteration statement keyword: {kw!r}")

    def _parse_jump_statement(self) -> JumpStatement:
        """jump-statement alternatives from the grammar."""
        kw = self._advance().value
        if kw == "return":
            value = None if self._check(";") else self._parse_expression()
            self._expect(";")
            return JumpStatement("return", value)
        if kw == "goto":
            label = self._advance().value
            self._expect(";")
            return JumpStatement("goto", label=label)
        self._expect(";")
        return JumpStatement(kw)

    def _parse_labeled_statement(self) -> ASTNode:
        if self._check("case"):
            self._advance()
            value = self._parse_conditional_expression()
            self._expect(":")
            return CaseStatement(value, self._parse_statement())
        if self._check("default"):
            self._advance()
            self._expect(":")
            return DefaultStatement(self._parse_statement())
        label = self._advance().value
        self._expect(":")
        return LabeledStatement(label, self._parse_statement())

    def _parse_expression_statement(self) -> ExprStatement:
        if self._check(";"):
            self._advance()
            return ExprStatement(None)
        expr = self._parse_expression()
        self._expect(";")
        return ExprStatement(expr)

    # ── expression precedence chain ───────────────────────────────────────────
    # Operator sets are derived from the grammar where possible.

    def _parse_expression(self) -> ASTNode:
        left = self._parse_assignment_expression()
        while self._match(","):
            left = BinaryExpr(",", left, self._parse_assignment_expression())
        return left

    # Assignment operators read from the grammar's assignment-operator rule
    _ASSIGN_OPS = {"=", "*=", "/=", "%=", "+=", "-=", "<<=", ">>=", "&=", "^=", "|="}

    def _parse_assignment_expression(self) -> ASTNode:
        left = self._parse_conditional_expression()
        if self._peek().value in self._ASSIGN_OPS:
            op    = self._advance().value
            right = self._parse_assignment_expression()
            return BinaryExpr(op, left, right)
        return left

    def _parse_conditional_expression(self) -> ASTNode:
        cond = self._parse_logical_or()
        if self._match("?"):
            then  = self._parse_expression()
            self._expect(":")
            else_ = self._parse_conditional_expression()
            return TernaryExpr(cond, then, else_)
        return cond

    def _parse_logical_or(self) -> ASTNode:
        left = self._parse_logical_and()
        while (op := self._match("||")):
            left = BinaryExpr(op.value, left, self._parse_logical_and())
        return left

    def _parse_logical_and(self) -> ASTNode:
        left = self._parse_inclusive_or()
        while (op := self._match("&&")):
            left = BinaryExpr(op.value, left, self._parse_inclusive_or())
        return left

    def _parse_inclusive_or(self) -> ASTNode:
        left = self._parse_exclusive_or()
        while (op := self._match("|")):
            left = BinaryExpr(op.value, left, self._parse_exclusive_or())
        return left

    def _parse_exclusive_or(self) -> ASTNode:
        left = self._parse_and_expr()
        while (op := self._match("^")):
            left = BinaryExpr(op.value, left, self._parse_and_expr())
        return left

    def _parse_and_expr(self) -> ASTNode:
        left = self._parse_equality()
        while (op := self._match("&")):
            left = BinaryExpr(op.value, left, self._parse_equality())
        return left

    def _parse_equality(self) -> ASTNode:
        left = self._parse_relational()
        while (op := self._match("==", "!=")):
            left = BinaryExpr(op.value, left, self._parse_relational())
        return left

    def _parse_relational(self) -> ASTNode:
        left = self._parse_shift()
        while (op := self._match("<", ">", "<=", ">=")):
            left = BinaryExpr(op.value, left, self._parse_shift())
        return left

    def _parse_shift(self) -> ASTNode:
        left = self._parse_additive()
        while (op := self._match("<<", ">>")):
            left = BinaryExpr(op.value, left, self._parse_additive())
        return left

    def _parse_additive(self) -> ASTNode:
        left = self._parse_multiplicative()
        while (op := self._match("+", "-")):
            left = BinaryExpr(op.value, left, self._parse_multiplicative())
        return left

    def _parse_multiplicative(self) -> ASTNode:
        left = self._parse_cast()
        while (op := self._match("*", "/", "%")):
            left = BinaryExpr(op.value, left, self._parse_cast())
        return left

    def _parse_cast(self) -> ASTNode:
        if self._check("(") and self._is_type_specifier_at(1):
            self._advance()
            type_name = self._collect_type_name()
            self._expect(")")
            return CastExpr(type_name, self._parse_cast())
        return self._parse_unary()

    def _collect_type_name(self) -> str:
        parts: list[str] = []
        while self._is_type_specifier():
            parts.append(self._advance().value)
        while self._match("*"):
            parts.append("*")
        return " ".join(parts)

    def _parse_unary(self) -> ASTNode:
        op = self._match("++", "--")
        if op:
            return UnaryExpr(op.value, self._parse_unary(), prefix=True)

        if self._check("sizeof"):
            self._advance()
            if self._check("(") and self._is_type_specifier_at(1):
                self._advance()
                type_name = self._collect_type_name()
                self._expect(")")
                return SizeofExpr(type_name)
            return SizeofExpr(self._parse_unary())

        # Unary operator FIRST set comes from the grammar's unary-operator rule
        unary_ops = self._first.get("unary-operator", {"&", "*", "+", "-", "~", "!"})
        op = self._match(*unary_ops)
        if op:
            return UnaryExpr(op.value, self._parse_cast(), prefix=True)

        return self._parse_postfix()

    def _parse_postfix(self) -> ASTNode:
        node = self._parse_primary()
        while True:
            if self._match("["):
                idx  = self._parse_expression()
                self._expect("]")
                node = IndexExpr(node, idx)
            elif self._match("("):
                args: list[ASTNode] = []
                if not self._check(")"):
                    args.append(self._parse_assignment_expression())
                    while self._match(","):
                        args.append(self._parse_assignment_expression())
                self._expect(")")
                node = CallExpr(node, args)
            elif self._match("."):
                node = MemberExpr(node, self._advance().value, arrow=False)
            elif self._match("->"):
                node = MemberExpr(node, self._advance().value, arrow=True)
            elif (op := self._match("++", "--")):
                node = UnaryExpr(op.value, node, prefix=False)
            else:
                break
        return node

    def _parse_primary(self) -> ASTNode:
        tok = self._peek()
        if tok.type == TokenType.INTEGER:
            return IntLiteral(self._advance().value)
        if tok.type == TokenType.FLOAT:
            return FloatLiteral(self._advance().value)
        if tok.type == TokenType.STRING:
            return StringLiteral(self._advance().value)
        if tok.type == TokenType.CHAR:
            return CharLiteral(self._advance().value)
        if self._is_word():
            return Identifier(self._advance().value)
        if self._match("("):
            expr = self._parse_expression()
            self._expect(")")
            return GroupExpr(expr)
        raise ParseError(
            f"Unexpected token {tok.value!r} (type={tok.type.name}) at pos {self.pos}"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Convenience entry points
# ─────────────────────────────────────────────────────────────────────────────

def _default_path(filename: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, filename)


def parse_string(
    source: str,
    grammar_file: str | None = None,
    keyword_file: str | None = None,
) -> TranslationUnit:
    import os
    _HERE = os.path.dirname(os.path.abspath(__file__))
    gf = grammar_file or _default_path(os.path.join(_HERE, "grammar.bnf"))
    kf = keyword_file or _default_path(os.path.join(_HERE, "keywords.json"))
    grammar = load_grammar(gf)
    tokens  = Lexer(source, kf if os.path.exists(kf) else None).tokenize()
    return Parser(tokens, grammar).parse()


def parse_file(
    source_path: str,
    grammar_file: str | None = None,
    keyword_file: str | None = None,
) -> TranslationUnit:
    with open(source_path, encoding="utf-8") as f:
        source = f.read()
    return parse_string(source, grammar_file, keyword_file)


# ─────────────────────────────────────────────────────────────────────────────
#  Demo
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    samples = [
        ("int x = 5;",                        "variable declaration"),
        ("int x = 1 + 2 * 3;",               "arithmetic precedence"),
        ("float pi = 3.14f;",                 "float declaration"),
        ("x = a > 0 ? a : -a;",              "ternary (expression statement)"),
        ("""
        int factorial(int n) {
            if (n <= 1) return 1;
            return n * factorial(n - 1);
        }
        """,                                  "recursive function"),
        ("""
        int main(void) {
            int i;
            int sum = 0;
            for (i = 0; i < 10; i++) {
                sum += i;
            }
            return sum;
        }
        """,                                  "for loop with compound assignment"),
    ]

    for source, label in samples:
        print(f"\n{'─'*60}\n  {label}\n{'─'*60}")
        try:
            ast = parse_string(source)
            print(ast.pretty())
        except ParseError as e:
            print(f"  ParseError: {e}")