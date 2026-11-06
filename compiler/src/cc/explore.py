"""The compiler explorer: one HTML page that shows what tiny C does to a C file.

    python compiler/src/cc explore prog.c [-o prog.html] [-I dir] [-D NAME]

Three columns, linked by the C line (hover any line to light up everything
it became):

  C source        every line that produced code is marked
  assembly        the code generator's output, with each line the peephole
                  passes removed struck through and named after the pass
                  (known values, stack reload, flags, jumps), and the lines
                  a pass wrote new marked; then the final assembly
  machine words   the linked program's words for this file's functions, with
                  their disassembly and addresses (from the .map's lines)

The passes are found by compiling again with peephole.optimize swapped for
the first pass, the first two, ... (the compiler itself is untouched), and
aligning each listing with the next (difflib). Not shown: the token list,
the syntax tree and per-line instruction counts (PLAN.md item 14).
"""

import difflib
import html
import re
import sys
import tempfile
from pathlib import Path

import driver
import peephole

PASSES = [("known values", peephole.known_values),
          ("stack reload", peephole.stack_reload),
          ("flags", peephole.flags),
          ("jumps", None)]                  # None: the real optimize(), whose last stage is jumps + unreachable

_LOC = re.compile(r'^\s*\.loc\s+"([^"]*)",\s*(\d+)')


def _compile_with(path, include, define, optimize):
    saved = peephole.optimize
    peephole.optimize = optimize
    try:
        return driver.compile_c(path, include, define)
    finally:
        peephole.optimize = saved


def _stage_functions(count):
    """optimize() replacements: the first `count` passes only (count 0: none)."""
    def upto(items):
        for name, fn in PASSES[:count]:
            if fn is None:
                return _real(items)
            items = fn(items)
        return items
    return upto


_real = peephole.optimize


def stages(path, include=(), define=()):
    """[(label, asm text)]: the code generator's output, then after each pass."""
    out = [("code generator", _compile_with(path, include, define, _stage_functions(0)))]
    for i, (name, _fn) in enumerate(PASSES, 1):
        out.append((name, _compile_with(path, include, define, _stage_functions(i))))
    return out


def annotate(texts):
    """The first listing's lines with the pass that removed each (or None), and
    the last listing's lines with the pass that wrote each new (or None):
    ([(line, removed_by)], [(line, added_by)]). Passes work on the previous
    pass's output, so each pair is aligned and the survivors are followed."""
    first = texts[0][1].splitlines()
    alive = list(range(len(first)))           # index into `first` of each line still in the listing
    removed = [None] * len(first)
    current = first
    added = {}
    for label, text in texts[1:]:
        new = text.splitlines()
        sm = difflib.SequenceMatcher(None, current, new, autojunk=False)
        keep = []
        for tag, a0, a1, b0, b1 in sm.get_opcodes():
            if tag == "equal":
                keep.extend(alive[a0:a1])
            else:
                for k in range(a0, a1):
                    if alive[k] >= 0:
                        removed[alive[k]] = label
                    else:
                        added.pop(alive[k])             # written by an earlier pass, removed by this one
                for k in range(b0, b1):
                    keep.append(-1 - len(added))        # a line the pass wrote: no source in the first listing
                    added[keep[-1]] = label
        alive, current = keep, new
    return ([(line, removed[i]) for i, line in enumerate(first)],
            [(line, added.get(alive[i])) for i, line in enumerate(current)])


def _c_lines_of(asm_lines, path):
    """The C line each asm line belongs to, from the .loc before it (None before the first)."""
    out, line = [], None
    for text in asm_lines:
        m = _LOC.match(text)
        if m and Path(m.group(1)).name == Path(path).name:
            line = int(m.group(2))
        out.append(line)
    return out


def machine_words(path, include=(), define=()):
    """[(address, word text, disassembly, C line or None)] for the functions of this file."""
    sys.path.insert(0, str(driver.SIM_DIR))
    try:
        from debuginfo import DebugInfo
        from isa import decode, disassemble
        program, _ = driver.build([str(path)], include, define)
    finally:
        sys.path.remove(str(driver.SIM_DIR))
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "x.map").write_text(driver.format_map(program, "x.rom"), encoding="utf-8")
        info = DebugInfo.load(Path(tmp) / "x.map")
    mine = [a for a, f, _n in info.lines if Path(f).name == Path(path).name]
    if not mine:
        return []
    first, last = min(mine), max(mine)
    after = [a for a in info.func_addrs if a > last]
    end = min(after) if after else len(program.rom)
    rows, a = [], first
    while a < end:
        ins = decode(program.rom[a])
        operand = program.rom[a + 1] if ins.takes_operand and a + 1 < len(program.rom) else None
        at = info.line_at(a)
        rows.append((a, program.rom[a], operand, disassemble(program.rom[a], operand), at[1] if at else None))
        a += 2 if ins.takes_operand else 1
    return rows


def render(path, include=(), define=()):
    """The page, as one HTML string."""
    source = Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    texts = stages(path, include, define)
    before, after = annotate(texts)
    before_lines = _c_lines_of([t for t, _ in before], path)
    after_lines = _c_lines_of([t for t, _ in after], path)
    words = machine_words(path, include, define)
    with_code = {n for n in before_lines if n} | {r[4] for r in words if r[4]}

    def span(text, line, cls=""):
        data = f' data-line="{line}"' if line else ""
        return f'<div class="l {cls}"{data}>{html.escape(text) or "&nbsp;"}</div>'

    c_col = "".join(span(f"{i:4d}  {t}", i, "code" if i in with_code else "")
                    for i, t in enumerate(source, 1))
    pass_names = ", ".join(n for n, _ in PASSES)
    removed = sum(1 for _, by in before if by)
    before_col = "".join(span(t, ln, "gone" if by else "") + (f'<span class="tag">{html.escape(by)}</span>' if by else "")
                         for (t, by), ln in zip(before, before_lines))
    after_col = "".join(span(t, ln, "new" if by else "") + (f'<span class="tag">{html.escape(by)}</span>' if by else "")
                        for (t, by), ln in zip(after, after_lines))
    word_col = "".join(span(f"{a:06X}  {w:08X}" + (f" {o:08X}" if o is not None else "          ") + f"  {d}", n)
                       for a, w, o, d, n in words)
    title = html.escape(Path(path).name)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Compiler explorer</title>
<style>
:root{{--bg:#fafafa;--fg:#1c1c1c;--dim:#8a8a8a;--hl:#ffe08a;--gone:#c0392b;--new:#1e7e34;--card:#fff;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#16181c;--fg:#e6e6e6;--dim:#8d96a0;--hl:#5a4a12;--gone:#ff7b72;--new:#56d364;--card:#1e2128;--line:#333}}}}
:root[data-theme="dark"]{{--bg:#16181c;--fg:#e6e6e6;--dim:#8d96a0;--hl:#5a4a12;--gone:#ff7b72;--new:#56d364;--card:#1e2128;--line:#333}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}}
header{{padding:12px 16px}} h1{{font-size:18px;margin:0}} p{{margin:4px 0;color:var(--dim)}}
main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px;padding:0 16px 16px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:6px;min-width:0}}
h2{{font-size:13px;margin:0;padding:8px 10px;border-bottom:1px solid var(--line)}}
.pane{{overflow:auto;max-height:78vh;padding:6px 0;font:12px/1.45 ui-monospace,Menlo,Consolas,monospace}}
.l{{white-space:pre;padding:0 10px}} .l.code{{border-left:3px solid var(--new)}} .l.hl{{background:var(--hl)}}
.gone{{color:var(--gone);text-decoration:line-through}} .new{{color:var(--new)}}
.tag{{font:11px system-ui;color:var(--dim);padding-left:10px}}
</style></head><body>
<header><h1>{title}</h1>
<p>Hover a line: everything it became lights up. Green bar: a C line that produced code. Passes: {html.escape(pass_names)} ({removed} lines removed from the code generator's output).</p></header>
<main>
<section><h2>C source</h2><div class="pane">{c_col}</div></section>
<section><h2>assembly: code generator (removed lines struck through, with the pass)</h2><div class="pane">{before_col}</div></section>
<section><h2>assembly: after the passes (new lines in green)</h2><div class="pane">{after_col}</div></section>
<section><h2>machine words (address, word, operand, disassembly)</h2><div class="pane">{word_col}</div></section>
</main>
<script>
const all = [...document.querySelectorAll('[data-line]')];
let lit = [];
document.addEventListener('mouseover', e => {{
  const t = e.target.closest('[data-line]');
  lit.forEach(x => x.classList.remove('hl'));
  lit = t ? all.filter(x => x.dataset.line === t.dataset.line) : [];
  lit.forEach(x => x.classList.add('hl'));
}});
</script></body></html>
"""
