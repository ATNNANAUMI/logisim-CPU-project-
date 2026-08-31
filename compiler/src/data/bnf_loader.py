"""
bnf_loader.py

Reads a BNF grammar file and produces a GrammarTable the parser can query.

Supported notation (matches the C grammar file):
  <rule-name> ::= alt1 | alt2 | alt3
  Terminals   : bare words like  if  while  return  +  ==
  Non-terminals: <angle-bracket-names>
  Optional    : {<thing>}?   or   {<thing>}*   (zero-or-more)
  One-or-more : {<thing>}+
  Continuation: a rule that spans multiple lines — each extra line
                starts with whitespace and | or another token.

Output: GrammarTable — a dict mapping rule name → list of alternatives,
        where each alternative is a list of GrammarSymbol objects.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum, auto


class SymbolKind(Enum):
    TERMINAL     = auto()   # literal token value  e.g. "if"  "+"
    NONTERMINAL  = auto()   # <rule-name>
    GROUP        = auto()   # { ... }? / { ... }* / { ... }+


@dataclass
class GrammarSymbol:
    kind:       SymbolKind
    value:      str                        # terminal value OR rule name
    children:   list[GrammarSymbol] = field(default_factory=list)  # for GROUP
    quantifier: str = ""                   # "", "?", "*", "+"

    def __repr__(self):
        if self.kind == SymbolKind.GROUP:
            return f"GROUP{self.quantifier}({self.children})"
        return f"{self.kind.name}({self.value!r})"


# A single alternative is a sequence of symbols
Alternative = list[GrammarSymbol]

# The full grammar: rule_name -> list of alternatives
GrammarTable = dict[str, list[Alternative]]


# ── tokenise a single RHS line into raw string tokens ────────────────────────

_TOKEN_RE = re.compile(
    r'<[^>]+>'          # <non-terminal>
    r'|{[^}]+}[?*+]?'   # {group}?  {group}*  {group}+
    r'|\.\.\.'           # ellipsis
    r'|[^\s|]+'          # bare terminal word / operator
)


def _tokenise_rhs(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


# ── parse a sequence of raw string tokens into GrammarSymbol objects ──────────

def _parse_symbols(raw_tokens: list[str]) -> list[GrammarSymbol]:
    symbols: list[GrammarSymbol] = []
    for tok in raw_tokens:
        if tok.startswith("<") and tok.endswith(">"):
            # non-terminal: strip angle brackets
            symbols.append(GrammarSymbol(SymbolKind.NONTERMINAL, tok[1:-1]))

        elif tok.startswith("{") :
            # group  { ... }?  { ... }*  { ... }+
            # find quantifier suffix
            quantifier = ""
            inner = tok[1:]  # strip leading {
            if inner.endswith(("?", "*", "+")):
                quantifier = inner[-1]
                inner = inner[:-1]
            if inner.endswith("}"):
                inner = inner[:-1]  # strip trailing }

            inner_raw = _tokenise_rhs(inner)
            children  = _parse_symbols(inner_raw)
            symbols.append(GrammarSymbol(SymbolKind.GROUP, "", children, quantifier))

        else:
            # plain terminal
            symbols.append(GrammarSymbol(SymbolKind.TERMINAL, tok))

    return symbols


# ── split a full RHS string on  |  (ignoring | inside { }) ──────────────────

def _split_alternatives(rhs: str) -> list[str]:
    alts: list[str] = []
    depth  = 0
    current: list[str] = []
    for ch in rhs:
        if ch == "{":
            depth += 1
            current.append(ch)
        elif ch == "}":
            depth -= 1
            current.append(ch)
        elif ch == "|" and depth == 0:
            alts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        alts.append("".join(current).strip())
    return [a for a in alts if a]


# ── main loader ───────────────────────────────────────────────────────────────

def load_grammar(path: str) -> GrammarTable:
    """
    Read a BNF file and return a GrammarTable.
    Keys are rule names (without angle brackets).
    Values are lists of alternatives (each alternative = list[GrammarSymbol]).
    """
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    # ── Phase 1: stitch continuation lines ───────────────────────────────────
    # A rule starts with <name> ::=
    # Continuation lines start with whitespace (and don't contain ::=)
    raw_rules: list[tuple[str, str]] = []   # [(name, full_rhs_string)]
    current_name: str | None = None
    current_rhs:  list[str]  = []

    for line in lines:
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue

        if "::=" in line:
            # save previous rule
            if current_name is not None:
                raw_rules.append((current_name, " ".join(current_rhs)))

            lhs, _, rhs = line.partition("::=")
            current_name = lhs.strip().strip("<>")
            current_rhs  = [rhs.strip()]
        elif current_name is not None and line.startswith((" ", "\t")):
            # continuation — might start with | or just more symbols
            current_rhs.append(line.strip())

    if current_name is not None:
        raw_rules.append((current_name, " ".join(current_rhs)))

    # ── Phase 2: parse each rule's RHS ───────────────────────────────────────
    grammar: GrammarTable = {}
    for name, rhs in raw_rules:
        alt_strings = _split_alternatives(rhs)
        alternatives: list[Alternative] = []
        for alt_str in alt_strings:
            raw_toks = _tokenise_rhs(alt_str)
            symbols  = _parse_symbols(raw_toks)
            if symbols:
                alternatives.append(symbols)
        grammar[name] = alternatives

    return grammar


# ── helpers the parser will use ───────────────────────────────────────────────

def get_terminals(grammar: GrammarTable, rule: str) -> set[str]:
    """
    Return the set of terminal values that can START the given rule.
    Used by the parser to decide which alternative to try.
    Walks one level deep — enough for the LL(1) lookahead we need.
    """
    result: set[str] = set()
    for alt in grammar.get(rule, []):
        for sym in alt:
            if sym.kind == SymbolKind.TERMINAL:
                result.add(sym.value)
                break
            elif sym.kind == SymbolKind.NONTERMINAL:
                # recurse one level
                result |= get_terminals(grammar, sym.value)
                break
            elif sym.kind == SymbolKind.GROUP:
                for child in sym.children:
                    if child.kind == SymbolKind.TERMINAL:
                        result.add(child.value)
    return result


def rule_exists(grammar: GrammarTable, rule: str) -> bool:
    return rule in grammar


def print_grammar(grammar: GrammarTable) -> None:
    """Pretty-print the loaded grammar for debugging."""
    for name, alts in grammar.items():
        print(f"<{name}>")
        for alt in alts:
            print(f"    | {alt}")
        print()


if __name__ == "__main__":
    import sys
    import os
    sys.setrecursionlimit(100000)
    _HERE = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "grammar.bnf")
    g = load_grammar(path)
    print_grammar(g)
    print(f"\nLoaded {len(g)} rules.")
