"""Check the stack limit register and its comparator on the circuit (TECHNICAL 2.6 item 3).

    python logisim/microcode/check_limit.py [--circ logisim/CPU.circ] [--jar path] [--keep-rom]

For each (limit, ESP) pair it builds a four-instruction program (SLIM, SSP, HALT), runs the whole
CPU with LimitProbe.java until HALT and compares the RAM subcircuit's LIMIT_HIT pin (the 1-bit
output at (1110,540)) with ESP >= limit, and the limit register with the value SLIM was given.
Also prints the limit at cycle 40, which is the reset value (all ones: 0xffffff) before the
start-up code reaches SLIM. By default the circuit's microcode ROM is replaced by the current
microcode.rom, so a stale image in the circuit doesn't matter (--keep-rom uses the circuit's own).
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "logisim"))
from run_rom import default_jar, find_rom, raw_to_contents

CASES = [(0x5000, 0x4FFF), (0x5000, 0x5000), (0x5000, 0x5001), (0xFFFFFF, 0x123456), (0xFFFFFF, 0xFFFFFF),
         (0x800000, 0x7FFFFF), (0x800000, 0x800000), (0x0, 0x0), (0x1000, 0x0), (0x10000, 0xFFFF), (0x10000, 0x10000)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--circ", default=str(ROOT / "logisim" / "CPU.circ"))
    ap.add_argument("--jar", default=default_jar())
    ap.add_argument("--keep-rom", action="store_true")
    args = ap.parse_args()
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["javac", "-cp", args.jar, "-d", tmp, str(HERE / "LimitProbe.java")], check=True)
        for limit, esp in CASES:
            asm = Path(tmp) / "t.asm"
            asm.write_text(f".global start\n.rom\nstart:\n DATA R1, {limit}\n SLIM R1\n DATA R1, {esp}\n SSP R1\n HALT\n")
            rom = Path(tmp) / "t.rom"
            subprocess.run([sys.executable, str(ROOT / "compiler/src/asm"), "build", str(asm), "-o", str(rom)],
                           check=True, capture_output=True)
            tree = ET.parse(args.circ)
            attr, bits = find_rom(tree)                        # the program ROM in RAM
            attr.text = raw_to_contents(rom.read_text(), bits)
            if not args.keep_rom:
                cs = [c for c in tree.getroot().findall("circuit") if c.get("name") == "CONTROL_SECTION"][0]
                mrom = [k for k in cs.findall("comp") if k.get("name") == "ROM"][0]
                [a for a in mrom.findall("a") if a.get("name") == "contents"][0].text = raw_to_contents(
                    (HERE / "microcode.rom").read_text(), 16)
            circ = Path(tmp) / "p.circ"
            tree.write(circ, encoding="UTF-8", xml_declaration=True)
            r = subprocess.run(["java", "-Xss64m", "-Djava.awt.headless=true", "-cp", f"{args.jar}{os.pathsep}{tmp}",
                                "LimitProbe", str(circ)], capture_output=True, text=True)
            if r.returncode or "halted:" not in r.stdout:
                print(f"limit {limit:#x} esp {esp:#x}: NO RESULT\n{r.stdout[-300:]}{r.stderr[-300:]}")
                bad += 1
                continue
            first = re.search(r"cycle 40: (.*)", r.stdout).group(1)
            m = re.search(r"halted: limit=(\S+) ebp=(\S+) esp=(\S+) hit=(\S+) cycles=(\d+)", r.stdout)
            lim, ebp, e, hit, cyc = m.groups()
            want_hit = int(esp >= limit)
            ok = hit == str(want_hit) and lim == f"0x{limit:06x}" and e == f"0x{esp:06x}"
            bad += not ok
            print(f"{'ok  ' if ok else 'FAIL'} limit {limit:#08x} esp {esp:#08x}: hit {hit} (want {want_hit}), "
                  f"limit reg {lim}, esp reg {e}   [cycle 40: {first}]")
    print("OK: the limit register and comparator behave" if not bad else f"FAILED: {bad} cases")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
