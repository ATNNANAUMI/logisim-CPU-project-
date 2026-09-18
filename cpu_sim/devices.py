"""Peripherals hanging off the COMM bus.

OUTADDR selects the output device, OUTDATA sends it a word.
INADDR selects the input device, INDATA consumes one word from it.
The CPU gets no feedback: talking to a device that is not there does nothing.
"""

from collections import deque

import config as config


class Display:
    """Text console at 0x5C.  Takes ASCII values, 0x0A is a newline."""

    def __init__(self):
        self.lines = [""]

    def write(self, value: int) -> None:
        char = value & 0xFF
        if char == 0x0A:
            self.lines.append("")
        elif char == 0x0D:
            self.lines[-1] = ""
        elif char == 0x08:
            self.lines[-1] = self.lines[-1][:-1]
        else:
            self.lines[-1] += chr(char)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def clear(self) -> None:
        self.lines = [""]


class Keyboard:
    """Buffer at 0x0F.  Typing fills it; INDATA consumes one character."""

    def __init__(self):
        self.buffer: deque[int] = deque()

    def type(self, text: str) -> None:
        self.buffer.extend(ord(c) for c in text)

    def read(self) -> int | None:
        return self.buffer.popleft() if self.buffer else None

    def clear(self) -> None:
        self.buffer.clear()


class DeviceBus:
    def __init__(self):
        self.display = Display()
        self.keyboard = Keyboard()
        self.out_addr = 0
        self.in_addr = 0

    # ------------------------------------------------------------ COMM
    def out_address(self, value: int) -> None:
        self.out_addr = value & config.WORD_MASK

    def in_address(self, value: int) -> None:
        self.in_addr = value & config.WORD_MASK

    def out_data(self, value: int) -> None:
        if self.out_addr == config.DISPLAY_ADDR:
            self.display.write(value)

    def in_data(self) -> int | None:
        """None means 'nothing happened' - the register keeps its value."""
        if self.in_addr == config.KEYBOARD_ADDR:
            return self.keyboard.read()
        return None

    def reset(self) -> None:
        self.out_addr = self.in_addr = 0
        self.display.clear()
        self.keyboard.clear()
