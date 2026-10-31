"""ROM and RAM.

One address bus (config.ADDR_BITS wide): the top bit (config.RAM_BIT) on
selects RAM, off selects ROM. Each bank holds config.BANK_WORDS words.
Reads work on both banks; writes to ROM are ignored.
"""

import gc

import config as config


def _unseen(bank):
    """CPython's cycle collector walks every item of every list it tracks,
    and a bank's 16M items take it tens of milliseconds each time; a bank
    only ever holds ints, so the bank (and whatever else exists by then) is
    moved out of its sight with gc.freeze()."""
    if hasattr(gc, "freeze"):
        gc.freeze()
    return bank


class Memory:
    def __init__(self):
        self.rom = [0] * config.BANK_WORDS
        self.ram = _unseen([0] * config.BANK_WORDS)

    # ------------------------------------------------------------ access
    @staticmethod
    def is_ram(addr: int) -> bool:
        return bool(addr & config.RAM_BIT)

    def read(self, addr: int) -> int:
        addr &= config.ADDR_MASK
        bank = self.ram if self.is_ram(addr) else self.rom
        return bank[addr & config.BANK_MASK]

    def write(self, addr: int, value: int) -> bool:
        """Returns False when the write was dropped (ROM address)."""
        addr &= config.ADDR_MASK
        if not self.is_ram(addr):
            return False
        self.ram[addr & config.BANK_MASK] = value & config.WORD_MASK
        return True

    # -------------------------------------------------- stack helpers
    # Stack slot i is RAM word i. ESP and EBP only reach the 16K stack area,
    # but STK SET/GET's EBP + RB can land anywhere in RAM.
    def stack_read(self, index: int) -> int:
        return self.ram[index & config.STACK_INDEX_MASK]

    def stack_write(self, index: int, value: int) -> None:
        self.ram[index & config.STACK_INDEX_MASK] = value & config.WORD_MASK

    # ------------------------------------------------------------ images
    def load_rom(self, words) -> int:
        self.rom, count = self._load(words)
        return count

    def load_ram(self, words) -> int:
        self.ram, count = self._load(words)
        return count

    @staticmethod
    def _load(words):
        """A new bank holding words, then zeros (a bank is 16M words, so it
        is built in one go rather than word by word)."""
        bank = [w & config.WORD_MASK for w in words]
        if len(bank) > config.BANK_WORDS:
            raise ValueError(f"image is {len(bank)} words, bank holds {config.BANK_WORDS}")
        bank += [0] * (config.BANK_WORDS - len(bank))
        return _unseen(bank), len(words)

    def clear_ram(self) -> None:
        self.ram = _unseen([0] * config.BANK_WORDS)


# --------------------------------------------------------------- file format
def parse_logisim(text: str) -> list[int]:
    """Parse a Logisim 'v2.0 raw' image, including 'count*value' runs."""
    words: list[int] = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line or line.lower().startswith("v2.0"):
            continue
        for token in line.split():
            if "*" in token:
                count, _, value = token.partition("*")
                words.extend([int(value, 16)] * int(count))
            else:
                words.append(int(token, 16))
    return words


def load_image(path: str) -> list[int]:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return parse_logisim(handle.read())
