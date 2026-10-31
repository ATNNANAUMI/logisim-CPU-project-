"""Check microcode.py's ROM against the gates of CONTROL_SECTION in CPU.circ.

    python logisim/microcode/verify.py [--circ logisim/CPU.circ] [--jar path] [--quick]

Makes a copy of the circuit in which CONTROL_SECTION's CLOCK and stepper are
replaced by pins (so the three clock phases, the step count and the stepper's
enable become inputs, and the stepper's two inputs outputs) and two probe pins
are added (the halt flip-flop's preset and the step decoder's step-0 output).
Logisim then runs it for every IR, step and flag value (ControlSweep.java,
16.7M points, under a minute each), with all phases on, then with clk_s off,
clk_e off and the stepper disabled (--quick: all on only). Each point is
compared with microcode.outputs() of the ROM word.

Steps after an instruction's STEP_RST never run; differences there are counted
but are not errors. halt_output, iar_reset, the CLOCK input and the stepper's
clock input are not compared: they stay gates outside the ROM.

Needs java and javac, and the Logisim jar ($LOGISIM_JAR or the Arch package path).
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import microcode as mc
from run_rom import default_jar

# CONTROL_SECTION's CLOCK at (320,30) and stepper at (630,30): their ports, and the two probes
CLOCK_AT, STEPPER_AT = "(320,30)", "(630,30)"
PINS = [((340, 20), 1, "input", "P_CLK0"),      # CLOCK outputs: clk_s,
        ((340, 30), 1, "input", "P_CLK1"),      # the stepper's clock,
        ((340, 40), 1, "input", "P_CLK2"),      # clk_e
        ((310, 30), 1, "output", "P_CLKIN"),    # CLOCK input
        ((690, 30), 1, "input", "P_STEPBIT"),   # stepper outputs: step decoder enable,
        ((690, 40), 4, "input", "P_STEP"),      # the count
        ((630, 30), 1, "output", "P_STEPIN0"),  # stepper inputs: clock,
        ((630, 40), 1, "output", "P_STEPIN1"),  # reset (STEP_RST)
        ((1020, 240), 1, "output", "P_HALTSET"),  # net to the halt flip-flop's preset
        ((840, 60), 1, "output", "P_STEP0")]    # step decoder output 0
NOT_COMPARED = {"halt_output", "iar_reset", "P_CLKIN", "P_STEPIN0"}
SWEEPS = [("all phases on", [], dict()),
          ("clk_s off", ["P_CLK0=0"], dict(clk_s=0)),
          ("clk_e off", ["P_CLK2=0"], dict(clk_e=0)),
          ("stepper disabled", ["P_STEPBIT=0"], dict(stepbit=0))]


def probe_circuit(src, dst):
    tree = ET.parse(src)
    cs = [c for c in tree.getroot().findall("circuit") if c.get("name") == "CONTROL_SECTION"][0]
    found = set()
    for comp in list(cs.findall("comp")):
        if (comp.get("name"), comp.get("loc")) in (("CLOCK", CLOCK_AT), ("stepper", STEPPER_AT)):
            cs.remove(comp)
            found.add(comp.get("name"))
    if found != {"CLOCK", "stepper"}:
        sys.exit(f"CLOCK at {CLOCK_AT} / stepper at {STEPPER_AT} not found in CONTROL_SECTION: "
                 "the circuit changed, update PINS in verify.py")
    for (x, y), width, kind, label in PINS:
        e = ET.SubElement(cs, "comp", {"lib": "0", "loc": f"({x},{y})", "name": "Pin"})
        for k, v in (("facing", "east" if kind == "input" else "west"), ("label", label),
                     ("type", kind), ("width", str(width))):
            ET.SubElement(e, "a", {"name": k, "val": v})
    tree.write(dst, xml_declaration=True, encoding="UTF-8")


def compare(path, words, gate):
    names = open(path + ".names").read().split()
    n1 = len(names) - 4
    wide = names[n1:]
    rec = struct.Struct(f">{2 + len(wide)}i")
    checked = [i for i, n in enumerate(names[:n1]) if n not in NOT_COMPARED]
    cmask = sum(1 << i for i in checked)
    reach = {}                    # (op7, ra3, jf, jnf) -> steps that run
    for op7 in range(128):
        for ra3 in range(8):
            for j in range(4):
                n = 16
                for step in range(16):
                    if words[mc.address(op7, ra3, step, j >> 1, j & 1)] >> mc.BIT["STEP_RST"] & 1:
                        n = step + 1
                        break
                reach[op7, ra3, j] = n
    # flag index f (pin bits top to bottom = C A N Z) -> C<<3 | A<<2 | N<<1 | Z
    fval = [sum((f >> (3 - i) & 1) << i for i in range(4)) for f in range(16)]
    errors, unreached, shown = 0, 0, 0
    with open(path, "rb") as fh:
        for ir in range(0x10000):
            block = fh.read(256 * rec.size)
            op7, ra3, mask = ir >> 8 & 0x7F, ir >> 4 & 7, ir & 0xF
            cache = {}
            for k, got in enumerate(rec.iter_unpack(block)):
                step, flags = k >> 4, fval[k & 15]
                jf, jnf = int(mask & flags != 0), int(mask & ~flags & 0xF != 0)
                w = words[mc.address(op7, ra3, step, jf, jnf)]
                exp = cache.get(w)
                if exp is None:
                    o = mc.outputs(w, ir, flags, **gate)
                    ones = sum(1 << i for i in checked if o[names[i]])
                    exp = cache[w] = (ones, tuple(o[n] for n in wide))
                if got[1] & cmask == 0 and got[0] & cmask == exp[0] and tuple(got[2:]) == exp[1]:
                    continue
                if step >= reach[op7, ra3, jf << 1 | jnf]:
                    unreached += 1
                    continue
                errors += 1
                if shown < 10:
                    shown += 1
                    bad = [names[i] for i in checked if (got[0] >> i ^ exp[0] >> i) & 1 or got[1] >> i & 1]
                    bad += [f"{n}={g} (ROM {e})" for n, g, e in zip(wide, got[2:], exp[1]) if g != e]
                    print(f"    IR={ir:04x} step {step} flags {flags:x}: {', '.join(bad)}")
    return errors, unreached


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--circ", default=os.path.join(HERE, "..", "CPU.circ"))
    ap.add_argument("--jar", default=default_jar())
    ap.add_argument("--quick", action="store_true", help="only the sweep with all phases on")
    args = ap.parse_args()
    words = mc.table()
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        probe = os.path.join(tmp, "probe.circ")
        probe_circuit(args.circ, probe)
        subprocess.run(["javac", "-cp", args.jar, "-d", tmp, os.path.join(HERE, "ControlSweep.java")],
                       check=True)
        for title, pins, gate in SWEEPS[:1] if args.quick else SWEEPS:
            out = os.path.join(tmp, "sweep.bin")
            r = subprocess.run(["java", "-Xss64m", "-cp", f"{args.jar}{os.pathsep}{tmp}", "ControlSweep",
                                probe, out] + pins, capture_output=True, text=True)
            if r.returncode:
                sys.exit(r.stderr[-3000:])
            osc = r.stdout.strip().splitlines()[-1]
            print(f"{title}: ({osc})")
            errors, unreached = compare(out, words, gate)
            print(f"  {errors} differences, {unreached} more at steps that never run")
            total += errors
    print("OK: the ROM matches CONTROL_SECTION" if total == 0 else f"FAILED: {total} differences")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
