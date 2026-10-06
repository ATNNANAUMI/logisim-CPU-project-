#!/usr/bin/env python3
"""
Run a ROM image on the REAL Logisim circuit, headless.

    python3 run_rom.py CPU.circ prog.rom [--seconds 120] [--jar path/to/logisim-evolution.jar]

Without --jar it uses $LOGISIM_JAR, then the jar installed by the Arch
package (/usr/share/java/logisim-evolution/logisim-evolution.jar).

It copies CPU.circ, replaces the contents of the ROM component inside the
`RAM` subcircuit with prog.rom, then runs Logisim-Evolution with no GUI and
prints whatever the TTY component displays.

prog.rom is the Logisim "v2.0 raw" image your linker already produces
(count*value runs are passed through untouched).

    --dump-rom out.rom    write the circuit's current ROM out as v2.0 raw
                          instead of running anything
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HEADER = "addr/data: 16 32"
SYSTEM_JAR = Path("/usr/share/java/logisim-evolution/logisim-evolution.jar")


def default_jar():
    if os.environ.get("LOGISIM_JAR"):
        return os.environ["LOGISIM_JAR"]
    if SYSTEM_JAR.is_file():
        return str(SYSTEM_JAR)
    return "logisim-evolution-4.1.0-all.jar"


def find_rom(tree):
    """The ROM component that holds the program: lib 5 'ROM' inside circuit 'RAM'."""
    for circuit in tree.getroot().findall("circuit"):
        if circuit.get("name") != "RAM":
            continue
        roms = [c for c in circuit.findall("comp")
                if c.get("lib") == "5" and c.get("name") == "ROM"]
        if len(roms) != 1:
            sys.exit(f"expected exactly 1 ROM in the RAM subcircuit, found {len(roms)}")
        for a in roms[0].findall("a"):
            if a.get("name") == "contents":
                return a
        sys.exit("ROM component has no contents attribute")
    sys.exit("no subcircuit named RAM")


def rom_to_raw(text):
    body = [ln for ln in (text or "").strip().splitlines()
            if not ln.strip().startswith("addr/data")]
    return "v2.0 raw\n" + "\n".join(body) + "\n"


def raw_to_contents(raw):
    lines = [ln.strip() for ln in raw.strip().splitlines()]
    if lines and lines[0].lower().startswith("v2.0"):
        lines = lines[1:]
    words = " ".join(lines).split()
    if not words:
        sys.exit("ROM image is empty")
    bad = [w for w in words if not re.fullmatch(r"(\d+\*)?[0-9a-fA-F]+", w)]
    if bad:
        sys.exit(f"not a v2.0 raw image, unexpected token: {bad[0]!r}")
    out = [HEADER]
    for i in range(0, len(words), 8):
        out.append(" ".join(words[i:i + 8]))
    return "\n".join(out) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("circ")
    p.add_argument("rom", nargs="?")
    p.add_argument("--jar", default=default_jar())
    p.add_argument("--seconds", type=int, default=120)
    p.add_argument("--circuit", default="PC")
    p.add_argument("--dump-rom")
    p.add_argument("--keep", help="where to write the patched .circ (default: temp)")
    args = p.parse_args()

    tree = ET.parse(args.circ)
    attr = find_rom(tree)

    if args.dump_rom:
        Path(args.dump_rom).write_text(rom_to_raw(attr.text))
        print(f"wrote {args.dump_rom}")
        return

    if not args.rom:
        p.error("need a .rom image (or --dump-rom)")

    attr.text = raw_to_contents(Path(args.rom).read_text())
    patched = Path(args.keep or (Path(args.circ).stem + "__patched.circ"))
    tree.write(patched, encoding="UTF-8", xml_declaration=True)

    cmd = ["java", "-Djava.awt.headless=true", "-jar", args.jar, str(patched),
           "--toplevel-circuit", args.circuit, "-t", "tty,halt"]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=args.seconds)
        out, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode() + (e.stderr or b"").decode()
        code = "timeout"

    noise = ("JAVA_TOOL_OPTIONS", "java.util.prefs", "INFO:")
    halted = False
    for line in out.splitlines():
        if "halted due to halt pin" in line:      # Logisim logs this as an ERROR
            halted = True
        elif not any(n in line for n in noise):
            print(line)
    status = "halted at HALT" if halted else f"exit: {code}"
    print(f"--- {status} ---", file=sys.stderr)


if __name__ == "__main__":
    main()
