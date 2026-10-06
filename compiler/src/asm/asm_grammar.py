"""Railroad diagrams of the assembly language (compiler/assembly_syntax.md).

Writes one HTML page with a diagram for every rule:

    python asm_grammar.py                 # -> asm_grammar.html next to this file
    python asm_grammar.py -o other.html

Needs the railroad-diagrams package (pip install railroad-diagrams).
Edit the rules below and re-run; don't edit the HTML by hand.
"""

from __future__ import annotations

import argparse
import html
import io
import re
from dataclasses import dataclass
from pathlib import Path

import railroad
from railroad import (Choice, Comment, Diagram, DiagramItem, NonTerminal,
                      OneOrMore, Optional, Sequence, Terminal, ZeroOrMore)

# Layout options of the library.
railroad.INTERNAL_ALIGNMENT = "left"    # branches line up on the left
railroad.STROKE_ODD_PIXEL_LENGTH = False  # the CSS below uses 2px lines


# ---------------------------------------------------------------- building blocks

def lit(text: str) -> Terminal:
    """Written exactly like this (white box, red text)."""
    return Terminal(text)


def ref(name: str) -> NonTerminal:
    """Another rule on this page (blue box, click to jump)."""
    return NonTerminal(name, href=f"#{name}")


def tok(name: str) -> Terminal:
    """A token with its own diagram in the Tokens section."""
    return Terminal(name, href=f"#{name}", cls="token")


def word(text: str) -> Terminal:
    """A token too simple to need a diagram (letter, digit, newline)."""
    return Terminal(text, cls="token")


def one_of(*texts: str) -> Choice:
    return Choice(0, *(lit(t) for t in texts))


def comma_list(item: DiagramItem) -> OneOrMore:
    return OneOrMore(item, lit(","))


def label(text: str, *items: DiagramItem) -> Sequence:
    """A branch with a short description in front of it."""
    return Sequence(Comment(text), *items)


@dataclass
class Rule:
    name: str
    diagram: Diagram
    note: str = ""          # `text` in backticks is shown as code


# ---------------------------------------------------------------- the grammar

SIGN = ("+", "-")

PROGRAM = [
    Rule("program", Diagram(
        OneOrMore(ref("line"), word("newline")),
        word("end of file"),
    ), "One statement per line."),

    Rule("line", Diagram(
        Optional(Sequence(tok("name"), lit(":"))),
        Optional(ref("statement")),
        Optional(Sequence(lit(";"), word("any text"))),
    ), "Every part is optional, so a line can be just a label, just a comment, "
       "or blank. A `;` inside quotes doesn't start a comment."),

    Rule("statement", Diagram(
        Choice(0, ref("instruction"), ref("pseudo_instruction"), ref("directive")),
    )),
]

INSTRUCTIONS = [
    Rule("instruction", Diagram(Choice(
        0,
        label("no operands", one_of("NOP", "CLF", "HALT")),
        label("memory, copy", one_of("LD", "ST", "ALD", "AST", "CPY"),
              ref("register"), lit(","), ref("register")),
        label("load a value", lit("DATA"), ref("register"), lit(","), ref("value")),
        label("jump", lit("RJMP"), ref("target")),
        label("jump if", one_of("RJF", "RJNF"), ref("flags"), lit(","), ref("target")),
        label("address, jump", one_of("ADDR", "JMRB"), ref("register")),
        label("input/output", lit("COMM"),
              one_of("INDATA", "INADDR", "OUTDATA", "OUTADDR"),
              Optional(lit(",")), ref("register")),
        label("stack", lit("STK"), Choice(
            0,
            one_of("PUSH", "POP", "CALL", "RET"),
            Sequence(one_of("SET", "GET"), Optional(lit(",")), ref("register")))),
        label("ALU", Choice(0, ref("two_operand_alu"), ref("one_operand_alu"))),
    )), "The comma after a `COMM` or `STK` sub-operation is optional."),

    Rule("two_operand_alu", Diagram(
        Choice(0,
               label("integer", one_of("ADD", "SUB", "MULT", "DIV", "AND", "OR",
                                       "XOR", "MOD", "CMP")),
               label("float", one_of("FADD", "FSUB", "FMULT", "FDIV", "FCMP"))),
        ref("register"), lit(","),
        Choice(0, ref("register"), label("immediate", lit("#"), ref("value"))),
    ), "`#` puts the value in the next word, so the instruction is 2 words "
       "instead of 1. The result always goes to R0."),

    Rule("one_operand_alu", Diagram(
        Choice(0,
               label("integer", one_of("SHL", "SHR", "NOT", "++", "INC", "--", "DEC",
                                       "NEG", "TEST")),
               label("float", one_of("FNEG", "FLOAT", "INT"))),
        ref("register"),
    ), "`INC` is the same as `++`, `DEC` the same as `--`. The result always "
       "goes to R0, not to the register named."),
]

PSEUDO = [
    Rule("pseudo_instruction", Diagram(Choice(
        0,
        label("call", lit("CALL"), ref("target"),
              Optional(Sequence(lit(","), ref("value"), Comment("args to drop")))),
        label("return", lit("RET")),
        label("save registers", one_of("SAVE", "RESTORE"), comma_list(ref("register"))),
    )), "The `CALL` count must be a number or a constant defined above it, not a "
        "label. `SAVE` and `RESTORE` take the same list in the same order, and a "
        "register can't be listed twice."),
]

DIRECTIVES = [
    Rule("directive", Diagram(Choice(
        0,
        label("section", one_of(".rom", ".ram")),
        label("visibility", one_of(".global", ".extern"), comma_list(tok("name"))),
        label("constant", lit(".equ"), tok("name"), lit(","), ref("value")),
        label("words", lit(".word"), comma_list(ref("value"))),
        label("text", lit(".string"), tok("string")),
        label("space", lit(".space"), ref("value")),
    )), "Inside `.ram` only labels and `.space` are allowed; `.word` and "
        "`.string` are ROM only. A constant used by `.equ` or `.space` must be "
        "defined above that line."),
]

OPERANDS = [
    Rule("register", Diagram(lit("R"), word("0 to 15")),
         "`R0` to `R15`, in either case."),

    Rule("flags", Diagram(
        OneOrMore(one_of("C", "A", "N", "Z")),
    ), "Letters written together, in any order: `NZ` jumps if N or Z is on."),

    Rule("target", Diagram(
        tok("name"),
        Optional(Sequence(one_of(*SIGN), ref("number"))),
    ), "A label, optionally plus or minus a number. The assembler works out "
       "the jump offset."),

    Rule("value", Diagram(
        OneOrMore(
            Sequence(ZeroOrMore(one_of(*SIGN)),
                     Choice(0, ref("number"), tok("float"), tok("name"))),
            one_of(*SIGN)),
    ), "At most one label, and it must be added. A float can't be combined "
       "with anything. The result must fit in 32 bits."),

    Rule("number", Diagram(
        Choice(0, tok("decimal"), tok("hex"), tok("binary"), tok("character")),
    )),
]

TOKENS = [
    Rule("name", Diagram(
        Choice(0, word("letter"), lit("_")),
        ZeroOrMore(Choice(0, word("letter"), word("digit"), lit("_"))),
    ), "Labels and `.equ` constants. Case-sensitive. Can't be a register name "
       "or a mnemonic in any case, and names starting with `__` are reserved."),

    Rule("decimal", Diagram(OneOrMore(word("digit"))),
         "A number can't run straight into letters, digits or a dot: `12ab` "
         "and `0x1G` are errors."),

    Rule("hex", Diagram(one_of("0x", "0X"), OneOrMore(word("hex digit")))),

    Rule("binary", Diagram(one_of("0b", "0B"), OneOrMore(one_of("0", "1")))),

    Rule("float", Diagram(
        OneOrMore(word("digit")),
        Choice(0,
               Sequence(lit("."), ZeroOrMore(word("digit")), Optional(tok("exponent"))),
               tok("exponent")),
        Optional(one_of("f", "F")),
    ), "Stored as the float32 bit pattern. Needs a digit before the dot "
       "(`0.5`, not `.5`); a minus sign comes from `value`."),

    Rule("exponent", Diagram(
        one_of("e", "E"), Optional(one_of(*SIGN)), OneOrMore(word("digit")),
    )),

    Rule("character", Diagram(
        lit("'"), Choice(0, word("any character but ' or \\"), tok("escape")), lit("'"),
    ), "Exactly one character; its ASCII code is the value."),

    Rule("string", Diagram(
        lit('"'),
        ZeroOrMore(Choice(0, word('any character but " or \\'), tok("escape"))),
        lit('"'),
    ), "`.string` stores one character per word, then a 0 word."),

    Rule("escape", Diagram(
        lit("\\"), one_of("n", "t", "r", "0", "\\", "'", '"'),
    ), "`\\n` newline (0x0A), `\\t` tab, `\\r` carriage return, `\\0` zero."),
]

SECTIONS = [                     # (heading, rules, look of the rule names)
    ("Program", PROGRAM, "rule"),
    ("Instructions", INSTRUCTIONS, "rule"),
    ("Pseudo-instructions", PSEUDO, "rule"),
    ("Directives", DIRECTIVES, "rule"),
    ("Operands", OPERANDS, "rule"),
    ("Tokens", TOKENS, "token"),
]


# ---------------------------------------------------------------- checking

def check_links() -> None:
    """Every blue box and token box must point at a rule on the page."""
    names = [rule.name for _, rules, _ in SECTIONS for rule in rules]
    defined = set(names)
    if len(defined) != len(names):
        raise SystemExit("a rule name is used twice")
    missing: set[str] = set()

    def visit(item: DiagramItem) -> None:
        href = getattr(item, "href", None)
        if isinstance(href, str) and href[1:] not in defined:
            missing.add(href[1:])

    for _, rules, _ in SECTIONS:
        for rule in rules:
            rule.diagram.walk(visit)
    if missing:
        raise SystemExit(f"links to rules that don't exist: {sorted(missing)}")


# ---------------------------------------------------------------- the page

DIAGRAM_CSS = """
svg.railroad-diagram { background: none; }
svg.railroad-diagram path { stroke: #3a3f47; stroke-width: 2; fill: none; }
svg.railroad-diagram text { font: bold 14px ui-monospace, monospace; text-anchor: middle; }
svg.railroad-diagram g.terminal rect { fill: #fff; stroke: #3a3f47; stroke-width: 2; }
svg.railroad-diagram g.terminal text { fill: #c8102e; }
svg.railroad-diagram g.terminal.token rect { fill: #fbf1d9; stroke: #b7862c; }
svg.railroad-diagram g.terminal.token text { fill: #6b4500; font: italic 600 13px system-ui, sans-serif; }
svg.railroad-diagram g.non-terminal rect { fill: #4a86c8; stroke: #2f6aa8; stroke-width: 2; }
svg.railroad-diagram g.non-terminal text { fill: #fff; font: 600 14px system-ui, sans-serif; }
svg.railroad-diagram g.non-terminal text.comment { fill: #5d6670; font: italic 12px system-ui, sans-serif; }
svg.railroad-diagram rect.group-box { stroke: #9aa3ad; stroke-width: 1.5; stroke-dasharray: 6 4; fill: none; }
svg.railroad-diagram a:hover rect { filter: brightness(1.12); }
"""

PAGE_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #fff; color: #1f2328;
       font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 28px 16px 64px; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
.sub { color: #5d6670; margin: 0 0 18px; }
h2 { font-size: 1.15rem; margin: 40px 0 6px; padding-bottom: 4px;
     border-bottom: 1px solid #e3e6ea; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 22px; align-items: center;
          padding: 12px 14px; background: #f6f8fa; border-radius: 8px; font-size: 14px; }
.key { display: inline-block; padding: 1px 10px; margin-right: 6px; font-weight: 600;
       border: 2px solid; border-radius: 6px; }
.key-rule { background: #4a86c8; border-color: #2f6aa8; color: #fff; border-radius: 3px; }
.key-lit { background: #fff; border-color: #3a3f47; color: #c8102e; border-radius: 10px;
           font-family: ui-monospace, monospace; }
.key-token { background: #fbf1d9; border-color: #b7862c; color: #6b4500; border-radius: 10px;
             font-style: italic; }
.case { width: 100%; color: #5d6670; }
.rule { margin: 22px 0 6px; scroll-margin-top: 12px; }
.rule-name { display: inline-block; background: #4a86c8; color: #fff; font-weight: 600;
             padding: 3px 12px; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,.2); }
.rule-name.token { background: #fbf1d9; color: #6b4500; border: 2px solid #b7862c;
                   padding: 1px 12px; border-radius: 12px; font-style: italic; box-shadow: none; }
.rule:target .rule-name { background: #e8a33d; color: #fff; }
.diagram { overflow-x: auto; }
.diagram svg { display: block; }
.note { margin: 0 0 0 4px; color: #3d444d; font-size: 14px; max-width: 760px; }
code { font-family: ui-monospace, monospace; font-size: 13px; background: #f1f3f5;
       padding: 0 4px; border-radius: 4px; }
footer { margin-top: 48px; color: #5d6670; font-size: 13px; }
"""


def note_html(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def rule_html(rule: Rule, look: str) -> str:
    svg = io.StringIO()
    rule.diagram.writeSvg(svg.write)
    note = f'\n<p class="note">{note_html(rule.note)}</p>' if rule.note else ""
    return (f'<section class="rule" id="{rule.name}">\n'
            f'<span class="rule-name {look}">{rule.name} =</span>\n'
            f'<div class="diagram">{svg.getvalue()}</div>{note}\n'
            f'</section>')


def page() -> str:
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Assembly Syntax</title>",
        f"<style>{PAGE_CSS}{DIAGRAM_CSS}</style>",
        "</head>",
        "<body>",
        "<main>",
        "<h1>Assembly language syntax</h1>",
        '<p class="sub">Railroad diagrams of what the assembler accepts. '
        "Follow a line from left to right; any path you can take is valid.</p>",
        '<div class="legend">'
        '<span><span class="key key-rule">rule</span>another diagram (click to jump)</span>'
        '<span><span class="key key-lit">ADD</span>written exactly as shown</span>'
        '<span><span class="key key-token">name</span>a token, defined at the bottom '
        "unless it's obvious</span>"
        '<span class="case">Mnemonics, register names, flag letters and directives '
        "can be written in any case. Names can't: <code>Loop</code> and "
        "<code>loop</code> differ.</span>"
        "</div>",
    ]
    for title, rules, look in SECTIONS:
        parts.append(f"<h2>{html.escape(title)}</h2>")
        parts.extend(rule_html(rule, look) for rule in rules)
    parts += [
        "<footer>Generated by <code>asm_grammar.py</code> from the rules in "
        "<code>compiler/assembly_syntax.md</code>. Edit the script and re-run it "
        "rather than editing this file.</footer>",
        "</main>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Railroad diagrams of the assembly language.")
    parser.add_argument("-o", "--output", type=Path, default=here / "asm_grammar.html",
                        help="where to write the page (default: next to this script)")
    args = parser.parse_args()
    check_links()
    args.output.write_text(page(), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
