"""Check the wiring around the microcode ROM in a test circuit (control_section_microcode).

    python logisim/microcode/check_address.py [--circ logisim/CPU_microcode.circ] [--circuit NAME] [--jar path]

The circuit needs: input pins ROM_ADDR_INPUT (the 16-bit IR) and C_F, A_F, N_F, Z_F (the flags);
a 32-bit output pin ROM_ADDR on the ROM's data output; the ROM loaded with microcode.rom;
the CLOCK and stepper where CONTROL_SECTION has them (verify.py replaces them by pins, so the
step count is driven straight onto the wire that goes to the ROM's step address bits).
Every IR (65536), step (16) and flag value (16) goes through Logisim's simulator (about a minute)
and ROM_ADDR is compared with the microcode.py table word at microcode.rom_address(). A wrong
address bit shows as wrong words; the summary says where they cluster.
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import microcode as mc
import verify
from run_rom import default_jar


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--circ", default=os.path.join(HERE, "..", "CPU_microcode.circ"))
    ap.add_argument("--circuit", default="control_section_microcode")
    ap.add_argument("--jar", default=default_jar())
    args = ap.parse_args()
    words = mc.table()
    root = ET.parse(args.circ).getroot()
    circ = [c for c in root.findall("circuit") if c.get("name") == args.circuit]
    if not circ:
        sys.exit(f"no circuit named {args.circuit} in {args.circ}")
    labels = {a.get("val") for k in circ[0].findall("comp") for a in k.findall("a") if a.get("name") == "label"}
    missing = {"ROM_ADDR_INPUT", "ROM_ADDR", "C_F", "A_F", "N_F", "Z_F"} - labels
    if missing:
        sys.exit(f"pins missing in {args.circuit}: {', '.join(sorted(missing))}")
    n_wide = sum(1 for k in circ[0].findall("comp") if k.get("name") == "Pin"
                 and {a.get("name"): a.get("val") for a in k.findall("a")}.get("type") == "output"
                 and int({a.get("name"): a.get("val") for a in k.findall("a")}.get("width", 1)) > 1)
    n_wide += 0                                   # the probe pins verify.probe_circuit adds are all 1 bit
    with tempfile.TemporaryDirectory() as tmp:
        probe, out = os.path.join(tmp, "probe.circ"), os.path.join(tmp, "sweep.bin")
        verify.probe_circuit(args.circ, probe, args.circuit)
        subprocess.run(["javac", "-cp", args.jar, "-d", tmp, os.path.join(HERE, "ControlSweep.java")], check=True)
        r = subprocess.run(["java", "-Xss64m", f"-Dcircuit={args.circuit}", "-cp", f"{args.jar}{os.pathsep}{tmp}",
                            "ControlSweep", probe, out], capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr[-3000:])
        names = open(out + ".names").read().split()
        wide = names[len(names) - n_wide:]
        col = 2 + wide.index("ROM_ADDR")
        rec = struct.Struct(f">{2 + len(wide)}i")
        fval = [sum((f >> (3 - i) & 1) << i for i in range(4)) for f in range(16)]
        wrong, shown = 0, 0
        by_step, by_flags, by_ir = Counter(), Counter(), Counter()
        with open(out, "rb") as fh:
            for ir in range(0x10000):
                for k, got in enumerate(rec.iter_unpack(fh.read(256 * rec.size))):
                    step, flags = k >> 4, fval[k & 15]
                    exp = words[mc.rom_address(ir, step, flags)]
                    if got[col] & 0xFFFFFFFF == exp:
                        continue
                    wrong += 1
                    by_step[step] += 1
                    by_flags[flags] += 1
                    by_ir[ir >> 12] += 1
                    if shown < 6:
                        shown += 1
                        print(f"  IR={ir:04x} step {step} flags {flags:x}: ROM_ADDR={got[col] & 0xFFFFFFFF:08x}, expected {exp:08x}")
    if wrong:
        print("  wrong points by step:", dict(sorted(by_step.items())))
        print("  by flags (C A N Z = 8 4 2 1):", dict(sorted(by_flags.items())))
        print("  by IR[15:12]:", dict(sorted(by_ir.items())))
    print("OK: the ROM reads the right word at every IR, step and flags" if not wrong else f"FAILED: {wrong} wrong points")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
