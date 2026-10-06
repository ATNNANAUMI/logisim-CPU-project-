#!/usr/bin/env python3
"""Checks that the docs still match the repo: python check_docs.py

Only mechanical facts are checked (paths, the example list, the TWEAKS
table); whether a description is still true needs a human (or Claude).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ["README.md", "STRUCTURE.md", "TECHNICAL.md", "CLAUDE.md",
        "compiler/assembly_syntax.md", ".claude/skills/circuit-check/SKILL.md"]
EXAMPLES = ROOT / "compiler" / "examples"

# repo paths as the docs write them: compiler/..., cpu_sim/..., logisim/...
# ("logisim/cpu datas/" has a space), .claude/..., run.py, *.md at the root
PATH = re.compile(r"(?<![\w./-])((?:compiler|cpu_sim|logisim|\.claude)/"
                  r"(?:cpu datas/?)?[\w./*-]*|run\.py|[A-Z]+\.md)")


def generated_or_placeholder(path):
    return path.startswith("compiler/ROM/") or "NN" in path


def exists(path):
    return (ROOT / path).exists() or any(ROOT.glob(path))


def paragraphs(text):
    """(first line number, lines) for each blank-line separated paragraph."""
    start, lines = 1, []
    for n, line in enumerate(text.splitlines() + [""], 1):
        if line.strip():
            if not lines:
                start = n
            lines.append(line)
        elif lines:
            yield start, lines
            lines = []


def check_paths_exist():
    """Every repo path named in the docs exists (globs must match something).
    Build output, diagNN placeholders and paragraphs about removed files are
    skipped.  A `backticked` span that is an existing path counts as a whole,
    so names with spaces (`logisim/cpu datas/TO DO.txt`) work."""
    missing = []
    for doc in DOCS:
        for start, lines in paragraphs((ROOT / doc).read_text()):
            if any("removed" in line.lower() for line in lines):
                continue
            for n, line in enumerate(lines, start):
                line = re.sub(r"`([^`]+)`", lambda m: "" if exists(m.group(1)) else m.group(0), line)
                for m in PATH.finditer(line):
                    path = m.group(1).rstrip(".,")
                    if not generated_or_placeholder(path) and not exists(path):
                        missing.append(f"{doc}:{n}: {path}")
    assert not missing, "paths that do not exist:\n  " + "\n  ".join(missing)


def check_examples_listed():
    """Every .asm under compiler/examples/ is listed in TECHNICAL.md (5.2/5.3)."""
    text = (ROOT / "TECHNICAL.md").read_text()
    unlisted = [str(p.relative_to(EXAMPLES)) for p in sorted(EXAMPLES.rglob("*.asm"))
                if f"`{p.relative_to(EXAMPLES)}`" not in text
                and f"`{p.relative_to(ROOT)}`" not in text
                and f"{p.name}`" not in text]
    assert not unlisted, "examples missing from TECHNICAL.md 5.3: " + ", ".join(unlisted)


def check_tweaks_documented():
    """Every switch in the TWEAKS block of cpu_sim/src/config.py is in TECHNICAL.md 3.4."""
    config = (ROOT / "cpu_sim" / "src" / "config.py").read_text()
    block = config.split("# " + "-" * 10)[-1]          # the last ruled section: TWEAKS
    assert "TWEAKS" in block, "could not find the TWEAKS block in config.py"
    names = re.findall(r"^([A-Z_]+)\s*=", block, re.M)
    text = (ROOT / "TECHNICAL.md").read_text()
    undocumented = [n for n in names if f"`{n}`" not in text]
    assert not undocumented, "TWEAKS missing from TECHNICAL.md 3.4: " + ", ".join(undocumented)


CHECKS = [check_paths_exist, check_examples_listed, check_tweaks_documented]


def main():
    failed = 0
    for check in CHECKS:
        name = check.__name__[len("check_"):]
        try:
            check()
            print(f"ok    {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n      {e}")
    print(f"\n{len(CHECKS) - failed} of {len(CHECKS)} checks passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
