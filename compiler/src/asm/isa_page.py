"""The instruction set as one HTML page: python compiler/src/asm/isa_page.py [-o isa.html]

Writes a self-contained page (no network; open it in a browser) with every
instruction: its syntax, effect and size (parsed from the tables of section
4 of compiler/assembly_syntax.md, not copied), its encoding as a bit field
drawn from a word the assembler really writes, the flags it changes, and
its micro-steps, read from logisim/microcode/microcode.py (the control
section of the circuit). The group 0x2 instructions (interrupts, Phase 6)
are marked as not on the circuit yet, except GSP SSP GBP SBP SLIM: the microcode has no steps for the others.

Below the table, a decoder (a hex word -> the instruction, by the same rules
as cpu_sim/src/isa.py) and an encoder (an instruction and its registers ->
the words). The decoder's tables are built from encoding.py; the assembler's
self-check runs the same decoding in Python on all 65,536 words and compares
it with isa.py's decode().

Default output: compiler/ROM/isa.html (git-ignored).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import encoding as enc
from assembler import assemble
from errors import AsmErrors

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
DOC = ROOT / "compiler" / "assembly_syntax.md"
sys.path.insert(0, str(ROOT / "logisim" / "microcode"))
import microcode                        # noqa: E402  (logisim/microcode/)

OUTPUT = ROOT / "compiler" / "ROM" / "isa.html"

# measured on the circuit (CLAUDE.md, TECHNICAL 1.5 and 8)
FLAG_NOTES = {
    "SUB": "C is set on a borrow (RA < RB unsigned).",
    "CMP": "C is never set (measured on the circuit); R0 = 0.",
    "--": "C is never set (measured on the circuit).",
    "NEG": "C is never set (measured on the circuit).",
    "MULT": "C is never set (measured on the circuit).",
    "NOT": "A is always 0 (RA = RB).",
    "TEST": "Only N and Z can be set: R0 = RB.",
    "FCMP": "R0 = 0.",
}


# ------------------------------------------------------------------ the doc

def doc_rows(text=None):
    """The rows of the tables in section 4 of assembly_syntax.md, as dicts
    keyed by the lower-case column headers, plus 'group' (the ### title)."""
    text = DOC.read_text(encoding="utf-8") if text is None else text
    section = text.split("## 4. Instructions", 1)[1].split("\n## 5.", 1)[0]
    rows, group, header = [], "", None
    for line in section.splitlines():
        if line.startswith("### "):
            group, header = line[4:].strip(), None
            continue
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if header is None:
            header = [h.lower() for h in cells]
        elif not set("".join(cells)) <= set("- "):
            row = dict(zip(header, cells))
            row["group"] = group
            rows.append(row)
    return rows


def code(cell):
    """`text` -> text."""
    return cell.strip().strip("`").strip()


def key(syntax):
    """The mnemonic a syntax starts with: 'ADD', or 'STK SET' for STK and COMM."""
    words = syntax.replace(",", " ").split()
    return " ".join(words[:2]) if words[0] in ("STK", "COMM") else words[0]


def documented(rows=None):
    """Every mnemonic (and COMM/STK sub-operation, and alias) section 4 has a row for."""
    names = set()
    for row in rows if rows is not None else doc_rows():
        names.add(key(code(row["syntax"])))
        if row.get("alias"):
            names.add(key(code(row["alias"])))
    return names


def encoded():
    """Every mnemonic encoding.py knows (COMM and STK by sub-operation)."""
    names = set()
    for name in enc.SYSTEM_OPS:
        if name == "COMM":
            names |= {f"COMM {s}" for s in enc.COMM_OPS}
        elif name == "STK":
            names |= {f"STK {s}" for s in enc.STK_OPS}
        else:
            names.add(name)
    return names | set(enc.ALU_OPS)


# ----------------------------------------------------------- the words

def example(syntax, ra="R1", rb="R2", value="5", flags="Z"):
    """The syntax with registers and a value filled in."""
    s = re.sub(r"\bRA\b", ra, syntax)
    s = re.sub(r"\bRB\b", rb, s)
    s = s.replace("#v", f"#{value}").replace("flags", flags).replace("target", "x")
    return re.sub(r"(?<=, )v$|(?<= )v$", value, s)


def words_of(text):
    """What the assembler writes for one instruction (x is a label on it)."""
    obj, _ = assemble(f".global start\nstart:\nx:\n{text}\n", "<isa>")
    return obj.rom


def form(syntax):
    """One way of writing an instruction: its base word and where RA, RB,
    the flags and the value go (worked out by assembling it)."""
    plain = example(syntax, "R0", "R0", "0", "Z")
    base = words_of(plain)
    word = base[0]
    flags = "flags" in syntax
    if flags:
        word -= enc.FLAGS["Z"]          # the Z written above
    ra = words_of(example(syntax, "R1", "R0", "0", "Z"))[0] ^ base[0] if "RA" in syntax else 0
    rb = words_of(example(syntax, "R0", "R1", "0", "Z"))[0] ^ base[0] if "RB" in syntax else 0
    second = None
    if len(base) == 2:
        second = "offset" if "target" in syntax else "value"
    return {"syntax": syntax, "base": word, "ra": ra, "rb": rb, "flags": flags,
            "second": second, "example": example(syntax),
            "example_words": words_of(example(syntax))}


def steps(word):
    """The microcode's steps for this word: [(condition, text)], or None
    (group 0x2 but GSP SSP GBP SBP SLIM: not on the circuit)."""
    if word >> 12 & 7 == 2 and (word >> 8 & 0xF) not in microcode.GROUP2_BUILT:
        return None
    op7, ra3 = word >> 8 & 0x7F, word >> 4 & 7
    out = []
    for step in range(16):
        variants = {}
        for jf, jnf in ((1, 0), (0, 1), (0, 0)):
            variants.setdefault(microcode.word(op7, ra3, step, jf, jnf), []).append((jf, jnf))
        if len(variants) == 1:
            w = next(iter(variants))
            out.append(["", f"{step:2}  {microcode.decode(w)}"])
        else:
            for w, conds in variants.items():
                jumps = any((jf if word >> 8 & 0xF == 5 else jnf) for jf, jnf in conds)
                out.append(["taken" if jumps else "not taken", f"{step:2}  {microcode.decode(w)}"])
        if microcode.word(op7, ra3, step, 0, 0) >> microcode.BIT["STEP_RST"] & 1:
            break
    return out


def flags_changed(name, row):
    if row["group"].startswith(("Integer ALU", "Float ALU")):
        note = FLAG_NOTES.get(name)
        return f"C A N Z rewritten. {note}" if note else "C A N Z rewritten"
    if name == "CLF":
        return "all cleared"
    if name == "RTI":
        return "restored from the saved word"
    return "unchanged"


def instructions():
    """Every row of section 4, with its forms, steps and flags."""
    out = []
    for row in doc_rows():
        syntax = code(row["syntax"])
        name = key(syntax)
        forms = [form(syntax)]
        if row.get("immediate form"):
            forms.append(form(code(row["immediate form"])))
        word = forms[0]["example_words"][0]
        out.append({
            "name": name, "group": row["group"], "effect": code(row["effect"]),
            "alias": code(row.get("alias", "")),
            "encoding": (row.get("encoding") or row.get("encoding (reg / imm)", "")).replace("`", ""),
            "forms": forms, "flags": flags_changed(name, row),
            "steps": steps(word), "imm_steps": steps(forms[1]["example_words"][0]) if len(forms) > 1 else None,
            "circuit": word >> 12 & 7 != 2 or (word >> 8 & 0xF) in microcode.GROUP2_BUILT,
        })
    return out


# ---------------------------------------------------------- the decoder

def decoder_tables():
    """encoding.py's names by opcode, for the page's decoder."""
    sys_ops = {code: name for name, (code, _) in enc.SYSTEM_OPS.items() if code < 0x20}
    group2 = {code & 0xF: name for name, (code, _) in enc.SYSTEM_OPS.items() if code >= 0x20}
    alu = {"int": {}, "float": {}}
    for name, (prefix, op, _) in enc.ALU_OPS.items():
        alu["int" if prefix == enc.INT_ALU else "float"].setdefault(op, name)
    shapes = {name: shape for name, (_, shape) in enc.SYSTEM_OPS.items()}
    shapes.update({name: shape for name, (_, _, shape) in enc.ALU_OPS.items()})
    return {"sys": sys_ops, "group2": group2, "int": alu["int"], "float": alu["float"], "shapes": shapes,
            "comm": {v: k for k, v in enc.COMM_OPS.items()},
            "stk": {code: name for name, (code, _) in enc.STK_OPS.items()},
            "flags": enc.FLAGS}


def page_decode(t, w):
    """The page's decoder in Python (the JS below does the same steps):
    (name or None, alu, float, imm, ra, rb). None: a word no mnemonic writes."""
    w &= 0x7FFF
    op, ra, rb = w >> 8 & 0xF, w >> 4 & 0xF, w & 0xF
    alu, flt, imm = bool(w & 0x1000), bool(w & 0x2000), bool(w & 0x4000)
    if alu:
        name = (t["float"] if flt else t["int"]).get(op)
    elif flt and op in t["group2"]:
        name, imm = t["group2"][op], False
    else:
        name, flt, imm = t["sys"][op], False, False
    return name, alu, flt, imm, ra, rb


# -------------------------------------------------------------- the page

STYLE = """
:root { --bg:#fbfaf7; --fg:#1d1d1b; --muted:#6b6a64; --line:#dddad2; --card:#ffffff;
  --accent:#2f6fb3; --warn:#a2541b; --ra:#2f8f5b; --rb:#8a4fbf; --op:#2f6fb3; --bits:#a2541b; }
@media (prefers-color-scheme: dark) { :root { --bg:#17181a; --fg:#e8e6e1; --muted:#9a988f;
  --line:#33342f; --card:#1f2022; --accent:#7fb0e6; --warn:#e3a06b; --ra:#73c897; --rb:#c39be6;
  --op:#7fb0e6; --bits:#e3a06b; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 19px; margin: 32px 0 8px; }
p.lead { color: var(--muted); margin: 0 0 20px; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13.5px; }
table { width: 100%; border-collapse: collapse; background: var(--card); }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
tr.ins { cursor: pointer; } tr.ins:hover, tr.ins.sel { background: color-mix(in srgb, var(--accent) 10%, transparent); }
.badge { font-size: 11px; padding: 1px 6px; border-radius: 8px; border: 1px solid var(--warn); color: var(--warn); white-space: nowrap; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; margin: 12px 0; }
.bits { display: grid; grid-template-columns: repeat(16, minmax(0, 1fr)); gap: 2px; margin: 8px 0; }
.bit { text-align: center; border: 1px solid var(--line); border-radius: 4px; padding: 2px 0; font-family: ui-monospace, monospace; }
.bit small { display: block; font-size: 10px; color: var(--muted); }
.f-op { border-color: var(--op); } .f-ra { border-color: var(--ra); } .f-rb { border-color: var(--rb); } .f-mode { border-color: var(--bits); }
.legend span { margin-right: 12px; font-size: 12px; } .legend i { display:inline-block; width:10px; height:10px; border:2px solid; border-radius:2px; margin-right:4px; vertical-align:-1px; }
pre { margin: 6px 0 0; white-space: pre-wrap; } .taken { color: var(--ra); } .nottaken { color: var(--muted); }
input, select, button { font: inherit; padding: 4px 6px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--fg); }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.out { margin-top: 8px; }
.wrap { overflow-x: auto; }
"""

SCRIPT = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const T = D.tables, $ = s => document.querySelector(s);
const hex = (w, n = 4) => '0x' + (w >>> 0).toString(16).toUpperCase().padStart(n, '0');
function bitsHtml(word, imm) {
  const field = i => i == 15 ? ['-', ''] : i == 14 ? ['IMM', 'f-mode'] : i == 13 ? ['FLT', 'f-mode']
    : i == 12 ? ['ALU', 'f-mode'] : i >= 8 ? ['op', 'f-op'] : i >= 4 ? ['RA', 'f-ra'] : ['RB', 'f-rb'];
  let s = '<div class="bits">';
  for (let i = 15; i >= 0; i--) { const [n, c] = field(i); s += `<div class="bit ${c}">${word >> i & 1}<small>${n}</small></div>`; }
  return s + '</div>';
}
function show(k) {
  const ins = D.ins[k];
  document.querySelectorAll('tr.ins').forEach(r => r.classList.toggle('sel', r.dataset.k == k));
  let s = `<h2>${esc(ins.name)}${ins.alias ? ' <span class="mono">(' + esc(ins.alias) + ')</span>' : ''}</h2>`;
  s += `<p>${esc(ins.effect)}</p>`;
  for (const f of ins.forms) {
    s += `<div class="mono">${esc(f.example)} &nbsp;→&nbsp; ${f.example_words.map(w => hex(w, 4)).join(', ')}</div>`;
    s += bitsHtml(f.example_words[0]);
  }
  s += '<div class="legend"><span><i style="border-color:var(--bits)"></i>mode bits</span><span><i style="border-color:var(--op)"></i>opcode</span><span><i style="border-color:var(--ra)"></i>RA</span><span><i style="border-color:var(--rb)"></i>RB</span></div>';
  s += `<p><b>Flags:</b> ${esc(ins.flags)}</p>`;
  if (!ins.circuit) s += '<p><span class="badge">not on the circuit yet</span> The microcode has no steps for group 0x2 (TECHNICAL 1.8, 2.6); the simulator runs it.</p>';
  const stepList = (st, title) => !st ? '' : `<p><b>${title}</b> (logisim/microcode/microcode.py; steps 0 and 1 are the fetch)</p><pre class="mono">` +
    st.map(([c, t]) => c ? `<span class="${c == 'taken' ? 'taken' : 'nottaken'}">${esc(t)}   (${c})</span>` : esc(t)).join('\n') + '</pre>';
  s += stepList(ins.steps, 'Micro-steps');
  s += stepList(ins.imm_steps, 'Micro-steps, immediate form');
  $('#detail').innerHTML = s;
}
function esc(t) { return String(t).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
// the decoder: the same steps as page_decode() in isa_page.py
function decode(w) {
  w &= 0x7FFF;
  const op = w >> 8 & 15, ra = w >> 4 & 15, rb = w & 15;
  let alu = !!(w & 0x1000), flt = !!(w & 0x2000), imm = !!(w & 0x4000), name;
  if (alu) name = (flt ? T.float : T.int)[op];
  else if (flt && T.group2[op] !== undefined) { name = T.group2[op]; imm = false; }
  else { name = T.sys[op]; flt = imm = false; }
  return { name, alu, flt, imm, op, ra, rb };
}
function text(d, second) {
  if (d.name === undefined) return `(no mnemonic writes this word: ${d.flt ? 'float' : 'integer'} ALU opcode ${d.op})`;
  const shape = T.shapes[d.name], v = second === '' ? 'v' : second;
  const flags = Object.entries(T.flags).filter(([k, b]) => d.rb & b).map(([k]) => k).join('') || '?';
  switch (shape) {
    case 'none': return d.name;
    case 'ra_rb': return `${d.name} R${d.ra}, R${d.rb}`;
    case 'rb': return `${d.name} R${d.rb}`;
    case 'rb_value': return `${d.name} R${d.rb}, ${v}`;
    case 'jump': return `${d.name} (offset ${v})`;
    case 'flagjump': return `${d.name} ${flags}, (offset ${v})`;
    case 'comm': return `COMM ${T.comm[d.ra & 3]}, R${d.rb}`;
    case 'stk': { const s = T.stk[d.ra & 7]; return s === undefined ? `STK (sub-operation ${d.ra & 7})` : (s == 'SET' || s == 'GET') ? `STK ${s}, R${d.rb}` : `STK ${s}`; }
    case 'alu1': return d.imm ? `${d.name} #${v}` : `${d.name} R${d.rb}`;
    case 'alu2': return d.imm ? `${d.name} R${d.ra}, #${v}` : `${d.name} R${d.ra}, R${d.rb}`;
  }
  return d.name;
}
function runDecoder() {
  const parts = $('#dec').value.trim().split(/[\s,]+/).filter(Boolean);
  const w = parseInt(parts[0], 16);
  if (isNaN(w)) { $('#decout').textContent = 'type a word in hex, e.g. 1012 or 0x5010 5'; return; }
  const d = decode(w);
  $('#decout').innerHTML = `<div class="mono">${esc(text(d, parts[1] ? parts[1] : ''))}</div>` + bitsHtml(w);
}
function runEncoder() {
  const f = D.forms[$('#encform').value], ra = +$('#encra').value, rb = +$('#encrb').value;
  let w = f.base;
  if (f.ra) w |= spread(f.ra, ra);
  if (f.rb) w |= spread(f.rb, rb);
  if (f.flags) w |= [...$('#encflags').value.toUpperCase()].reduce((a, c) => a | (T.flags[c] || 0), 0);
  const words = [w];
  if (f.second) words.push(f.second == 'value' ? ($('#encval').value || '0') : 'offset');
  $('#encout').innerHTML = `<div class="mono">${words.map((x, i) => i == 0 ? hex(x) : esc(x)).join(', ')}</div>` + bitsHtml(w);
}
// a register number into each field its 1-bit mask marks (NOT: RA and RB)
function spread(mask, r) { let w = 0; for (let i = 0; i < 16; i += 4) if (mask >> i & 1) w |= r << i; return w; }
function init() {
  let rows = '', group = '';
  D.ins.forEach((ins, k) => {
    if (ins.group != group) { group = ins.group; rows += `<tr><th colspan="5">${esc(group)}</th></tr>`; }
    rows += `<tr class="ins" data-k="${k}"><td class="mono">${esc(ins.forms.map(f => f.syntax).join('  |  '))}</td><td>${esc(ins.effect)}</td><td class="mono">${esc(ins.encoding)}</td><td>${ins.forms[0].example_words.length}${ins.forms[1] ? '/' + ins.forms[1].example_words.length : ''}</td><td>${ins.circuit ? '' : '<span class="badge">simulator only</span>'}</td></tr>`;
  });
  $('#table').innerHTML = rows;
  document.querySelectorAll('tr.ins').forEach(r => r.onclick = () => show(+r.dataset.k));
  $('#encform').innerHTML = D.forms.map((f, i) => `<option value="${i}">${esc(f.syntax)}</option>`).join('');
  ['#dec'].forEach(s => $(s).oninput = runDecoder);
  ['#encform', '#encra', '#encrb', '#encflags', '#encval'].forEach(s => $(s).oninput = runEncoder);
  show(0); runDecoder(); runEncoder();
}
init();
"""


def page():
    ins = instructions()
    forms = [f for i in ins for f in i["forms"]]
    data = {"ins": ins, "forms": forms, "tables": decoder_tables()}
    regs = "".join(f'<option value="{i}">R{i}</option>' for i in range(16))
    blob = json.dumps(data).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ISA Reference</title>
<style>{STYLE}</style></head>
<body><main>
<h1>The instruction set</h1>
<p class="lead">The logic-gate CPU's instructions, from <code>compiler/assembly_syntax.md</code> §4, the assembler
(<code>encoding.py</code>) and the circuit's microcode (<code>logisim/microcode/microcode.py</code>).
A word: bit 14 immediate, 13 float, 12 ALU, 11–8 opcode, 7–4 RA, 3–0 RB (bit 15 unused).
Click a row for its bits and micro-steps.</p>
<div class="wrap"><table><thead><tr><th>syntax</th><th>effect</th><th>encoding</th><th>words</th><th></th></tr></thead>
<tbody id="table"></tbody></table></div>
<div class="card" id="detail"></div>
<h2>Decoder</h2>
<div class="card"><div class="row"><label for="dec">word (hex), then its second word if any</label>
<input id="dec" class="mono" value="0x5010 5" size="16"></div><div class="out" id="decout"></div>
<p class="lead">Decoded as the simulator does (<code>cpu_sim/src/isa.py</code>): a word no mnemonic writes still runs as something.</p></div>
<h2>Encoder</h2>
<div class="card"><div class="row">
<select id="encform" class="mono"></select>
<label>RA <select id="encra">{regs}</select></label>
<label>RB <select id="encrb">{regs}</select></label>
<label>flags <input id="encflags" class="mono" value="Z" size="4"></label>
<label>value <input id="encval" class="mono" value="5" size="10"></label></div>
<div class="out" id="encout"></div></div>
<script type="application/json" id="data">{blob}</script>
<script>{SCRIPT}</script>
</main></body></html>
"""


def main(argv=None):
    p = argparse.ArgumentParser(description="Write the instruction set as one HTML page.")
    p.add_argument("-o", "--output", default=str(OUTPUT), help=f"default: {OUTPUT.relative_to(ROOT)}")
    args = p.parse_args(argv)
    try:
        text = page()
    except AsmErrors as e:
        print(f"an example in assembly_syntax.md section 4 doesn't assemble: {e.errors[0]}", file=sys.stderr)
        return 1
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"{out}: {len(instructions())} instructions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
