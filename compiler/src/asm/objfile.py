"""Object files: what the assembler writes and the linker reads.

They are JSON, so you can open one and read it when something goes wrong.
Words are stored as hex strings.

    rom       this file's ROM words, 8 per line; words the linker fills in hold 0
    ram_size  words of RAM this file reserves
    labels    every label: name -> [section, offset inside this file's part]
    globals   labels other files may use
    externs   labels this file uses from other files
    relocs    words the linker fills in (see Reloc)
"""

import json
from dataclasses import dataclass

from errors import AsmError

FORMAT = "cpu-asm object v1"


@dataclass
class Reloc:
    """A word the linker fills in once it knows where everything is."""
    at: int            # which word of this file's ROM part
    kind: str          # "abs" = an address, "rel" = a jump offset
    symbol: str | None     # another file's label, or None for this file's own
    section: str | None    # for this file's own labels: "rom" or "ram"
    addend: int        # added to the address (for own labels: the label's offset)
    line: int          # source line, for error messages

    def to_dict(self):
        d = {"at": self.at, "kind": self.kind}
        if self.symbol is not None:
            d["symbol"] = self.symbol
        else:
            d["section"] = self.section
        d["addend"] = self.addend
        d["line"] = self.line
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d["at"], d["kind"], d.get("symbol"), d.get("section"),
                   d["addend"], d.get("line", 0))


@dataclass
class ObjectFile:
    source: str        # the .asm file it came from
    rom: list          # ints
    ram_size: int
    labels: dict       # name -> (section, offset)
    globals: list
    externs: list
    relocs: list       # Reloc

    def to_json(self):
        # Written by hand so it stays readable: 8 words per line, and one
        # label or relocation per line.
        def block(open_, close, items):
            if not items:
                return open_ + close
            return open_ + "\n" + ",\n".join("  " + i for i in items) + "\n " + close

        rom_lines = [" ".join(f"{w:x}" for w in self.rom[i:i + 8])
                     for i in range(0, len(self.rom), 8)]
        fields = [
            f'"format": {json.dumps(FORMAT)}',
            f'"source": {json.dumps(self.source)}',
            '"rom": ' + block("[", "]", [json.dumps(line) for line in rom_lines]),
            f'"ram_size": {self.ram_size}',
            '"labels": ' + block("{", "}", [f"{json.dumps(name)}: {json.dumps([sec, off])}"
                                            for name, (sec, off) in self.labels.items()]),
            f'"globals": {json.dumps(self.globals)}',
            f'"externs": {json.dumps(self.externs)}',
            '"relocs": ' + block("[", "]", [json.dumps(r.to_dict()) for r in self.relocs]),
        ]
        return "{\n" + ",\n".join(" " + f for f in fields) + "\n}"

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json() + "\n")

    @classmethod
    def from_json(cls, text, path="<object>"):
        try:
            d = json.loads(text)
            if d.get("format") != FORMAT:
                raise ValueError
            return cls(
                source=d["source"],
                rom=[int(w, 16) for line in d["rom"] for w in line.split()],
                ram_size=int(d["ram_size"]),
                labels={name: (sec, int(off)) for name, (sec, off) in d["labels"].items()},
                globals=list(d["globals"]),
                externs=list(d["externs"]),
                relocs=[Reloc.from_dict(r) for r in d["relocs"]],
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            raise AsmError("not an object file from this assembler "
                           "(to use .asm files, run 'build' instead of 'link')",
                           path) from None

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8", errors="replace") as f:
            return cls.from_json(f.read(), path)
