"""The datapath as one HTML page: pick an instruction and watch its micro-steps.

    python logisim/microcode/datapath_page.py [-o datapath.html]     (default: compiler/ROM/datapath.html)

The page draws the CPU's parts around the bus (IAR, MAR, IR, memory, the
register file, TMP, ALU/ACC, flags, the stack unit, the I/O block) and, for
the chosen instruction, steps through the microcode table of microcode.py
(read off CPU.circ and checked against its gates by verify.py): the part that
drives the bus lights orange, the parts that latch from it blue, and a
sentence says what the step does. The two fetch steps come first.

It shows the control lines, not the values on the bus (that needs the
micro-step executor of PLAN.md item 15: not written). Group 0x2 (interrupts)
is not in the microcode; the circuit has no such instructions yet.
"""
import argparse
import html
import json
from pathlib import Path

import microcode

ROOT = Path(__file__).resolve().parents[2]

# token -> (part, what it does): drivers put a value on the bus, latches take it
DRIVES = {"IAR_E": ("IAR", "IAR drives the bus"), "RAM": ("RAM", "memory drives the bus (the word at MAR)"),
          "ACC": ("ACC", "ACC drives the bus"), "ARR_E": ("STACK", "the array address EBP + RB drives the bus"),
          "STACK_E": ("STACK", "the stack unit drives the bus"), "IO_E": ("IO", "the I/O device drives the bus"),
          "BUS_1": ("BUS", "the constant 1 drives the bus"),
          "R=RA": ("REG", "register RA drives the bus"), "R=RB": ("REG", "register RB drives the bus"),
          "R=R0": ("REG", "R0 drives the bus")}
LATCHES = {"MAR": ("MAR", "MAR latches the bus"), "IAR": ("IAR", "IAR loads from the bus"),
           "IAR_INC": ("IAR", "IAR counts up by one"), "IR": ("IR", "IR latches the bus"),
           "TMP": ("TMP", "TMP latches the bus"), "ACC_S": ("ACC", "the ALU result is latched into ACC"),
           "FLAG": ("FLAG", "the flags latch from the ALU (or are cleared)"), "RAM_S": ("RAM", "memory writes the bus at MAR"),
           "STACK_S": ("STACK", "the stack unit is clocked"), "IO_S": ("IO", "the I/O device latches the bus"),
           "W=RA": ("REG", "register RA latches the bus"), "W=RB": ("REG", "register RB latches the bus"),
           "W=R0": ("REG", "R0 latches the bus")}


def steps_of(op7, ra3):
    """[(label, text of the step)] for one instruction, fetch first; a conditional
    step is written 'text if the flag test holds, else STEP_RST'."""
    name, steps = microcode.program(op7, ra3)
    out = []
    for text in microcode.FETCH + steps:
        if isinstance(text, dict):
            taken = [t for k, t in text.items() if k][0]
            text = taken + "   (only if the flag test holds; otherwise STEP_RST)"
        out.append(text)
    return name, out


def instructions():
    seen, out = set(), []
    for op7 in range(128):
        for ra3 in range(8):
            name, steps = steps_of(op7, ra3)
            if name in seen or (op7 >> 6 & 1 and op7 & 0x30):      # IMM ignores IR[12]: one entry
                continue
            seen.add(name)
            out.append({"name": name, "steps": steps})
    return out


def page():
    data = json.dumps({"instructions": instructions(), "drives": DRIVES, "latches": LATCHES})
    return PAGE.replace("__DATA__", data)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CPU datapath</title>
<style>
:root{--bg:#fafafa;--fg:#1c1c1c;--dim:#6b7280;--card:#fff;--line:#c9ced6;--src:#f59e0b;--dst:#3b82f6;--part:#eef1f5}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#16181c;--fg:#e6e6e6;--dim:#9aa3ad;--card:#1e2128;--line:#454c57;--part:#2a2f38}}
:root[data-theme="dark"]{--bg:#16181c;--fg:#e6e6e6;--dim:#9aa3ad;--card:#1e2128;--line:#454c57;--part:#2a2f38}
body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:12px 16px}
h1{font-size:18px;margin:0 0 6px} .bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
select,button{font:inherit;padding:4px 10px;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px}
svg{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
.part rect{fill:var(--part);stroke:var(--line);stroke-width:1.5} .part text{fill:var(--fg);font:13px system-ui;text-anchor:middle}
.part.src rect{fill:var(--src);stroke:var(--src)} .part.dst rect{fill:var(--dst);stroke:var(--dst)}
.part.src text,.part.dst text{fill:#fff;font-weight:600}
.bus{stroke:var(--line);stroke-width:10;stroke-linecap:round} .bus.on{stroke:var(--src)}
.wire{stroke:var(--line);stroke-width:2}
#say{min-height:3.2em;margin:8px 0;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card)}
code{font:12px ui-monospace,Menlo,monospace;color:var(--dim)} .steps{display:flex;gap:4px;flex-wrap:wrap}
.steps button.cur{background:var(--dst);color:#fff;border-color:var(--dst)}
</style></head><body><main>
<h1>CPU datapath, micro-step by micro-step</h1>
<p>Orange: drives the bus. Blue: latches from it. The control lines come from the microcode table
(<code>logisim/microcode/microcode.py</code>); the values on the bus are not shown.</p>
<div class="bar"><label>instruction <select id="ins"></select></label>
<button id="prev">&larr;</button><button id="play">play</button><button id="next">&rarr;</button>
<span class="steps" id="steps"></span></div>
<svg viewBox="0 0 900 400" role="img" aria-label="CPU datapath">
<line class="bus" id="bus" x1="40" y1="200" x2="860" y2="200"/>
<g id="parts"></g></svg>
<div id="say"></div><div><code id="lines"></code></div>
</main>
<script>
const D = __DATA__;
const PARTS = {IAR:[40,40,"IAR"],MAR:[180,40,"MAR"],IR:[320,40,"IR"],RAM:[460,40,"RAM / ROM"],REG:[600,40,"R0 - R15"],TMP:[740,40,"TMP"],
  ACC:[40,290,"ACC (ALU)"],FLAG:[190,290,"FLAGS"],STACK:[340,290,"stack: ESP EBP"],IO:[520,290,"I/O"],BUS:[680,290,"constant 1"]};
const svg = document.getElementById('parts'), $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
for (const [id,[x,y,label]] of Object.entries(PARTS)) {
  const top = y < 200, g = document.createElementNS(NS,'g'); g.setAttribute('class','part'); g.id = 'p_'+id;
  g.innerHTML = `<line class="wire" x1="${x+60}" y1="${top?y+60:y}" x2="${x+60}" y2="200"/><rect x="${x}" y="${y}" width="120" height="60" rx="8"/><text x="${x+60}" y="${y+36}">${label}</text>`;
  svg.appendChild(g);
}
D.instructions.forEach((ins,i) => { const o = document.createElement('option'); o.value = i; o.textContent = ins.name; $('ins').appendChild(o); });
let cur = 0, step = 0, timer = null;
function show() {
  const ins = D.instructions[cur], text = ins.steps[step] || '';
  const toks = text.split(/\\s+/).filter(t => t && !t.startsWith('(') && t !== 'only' && t !== 'if' && t !== 'the' && t !== 'flag' && t !== 'test' && t !== 'holds;' && t !== 'otherwise' && t !== 'STEP_RST)');
  document.querySelectorAll('.part').forEach(p => p.setAttribute('class','part'));
  const said = []; let drives = false;
  for (const t of text.split(/\\s+/)) {
    if (D.drives[t]) { const [p,s] = D.drives[t]; $('p_'+p).classList.add('src'); said.push(s); drives = true; }
    else if (D.latches[t]) { const [p,s] = D.latches[t]; if (!$('p_'+p).classList.contains('src')) $('p_'+p).classList.add('dst'); said.push(s); }
  }
  if (/STEP_RST/.test(text) && !/otherwise STEP_RST/.test(text)) said.push('this was the last step: back to the fetch');
  $('bus').classList.toggle('on', drives);
  $('say').textContent = `${ins.name}, step ${step}` + (step < 2 ? ' (fetch)' : '') + ': ' + (said.join('; ') || 'nothing moves');
  $('lines').textContent = text;
  document.querySelectorAll('#steps button').forEach((b,i) => b.classList.toggle('cur', i === step));
}
function pick(i) {
  cur = +i; step = 0; $('steps').innerHTML = '';
  D.instructions[cur].steps.forEach((_,k) => { const b = document.createElement('button'); b.textContent = k; b.onclick = () => { step = k; show(); }; $('steps').appendChild(b); });
  show();
}
const move = d => { const n = D.instructions[cur].steps.length; step = (step + d + n) % n; show(); };
$('ins').onchange = e => pick(e.target.value);
$('prev').onclick = () => move(-1); $('next').onclick = () => move(1);
$('play').onclick = () => { if (timer) { clearInterval(timer); timer = null; $('play').textContent = 'play'; } else { timer = setInterval(() => move(1), 900); $('play').textContent = 'pause'; } };
pick(0);
</script></body></html>
"""


def main():
    p = argparse.ArgumentParser(description="the datapath, one instruction at a time, as an HTML page")
    p.add_argument("-o", "--output", default=str(ROOT / "compiler" / "ROM" / "datapath.html"))
    args = p.parse_args()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(), encoding="utf-8")
    print(f"{out}: {len(instructions())} instructions")


if __name__ == "__main__":
    main()
