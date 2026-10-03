"""ROM and RAM.

One 17-bit address bus: bit16 on selects RAM, off selects ROM.
Reads work on both banks; writes to ROM are ignored.
"""

import config as config


class Memory:
    def __init__(self):
        self.rom = [0] * config.BANK_WORDS
        self.ram = [0] * config.BANK_WORDS

    # ------------------------------------------------------------ access
    @staticmethod
    def is_ram(addr: int) -> bool:
        return bool(addr & config.RAM_BIT)

    def read(self, addr: int) -> int:
        addr &= config.ADDR_MASK
        bank = self.ram if self.is_ram(addr) else self.rom
        return bank[addr & 0xFFFF]

    def write(self, addr: int, value: int) -> bool:
        """Returns False when the write was dropped (ROM address)."""
        addr &= config.ADDR_MASK
        if not self.is_ram(addr):
            return False
        self.ram[addr & 0xFFFF] = value & config.WORD_MASK
        return True

    # -------------------------------------------------- stack helpers
    def stack_read(self, index: int) -> int:
        return self.ram[index & config.STACK_MASK]

    def stack_write(self, index: int, value: int) -> None:
        self.ram[index & config.STACK_MASK] = value & config.WORD_MASK

    # ------------------------------------------------------------ images
    def load_rom(self, words) -> int:
        return self._load(self.rom, words)

    def load_ram(self, words) -> int:
        return self._load(self.ram, words)

    @staticmethod
    def _load(bank, words) -> int:
        words = list(words)
        if len(words) > len(bank):
            raise ValueError(f"image is {len(words)} words, bank holds {len(bank)}")
        for i in range(len(bank)):
            bank[i] = words[i] & config.WORD_MASK if i < len(words) else 0
        return len(words)

    def clear_ram(self) -> None:
        self.ram = [0] * config.BANK_WORDS


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
