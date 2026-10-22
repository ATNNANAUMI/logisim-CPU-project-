"""Peripherals hanging off the COMM bus.

OUTADDR selects the output device, OUTDATA sends it a word.
INADDR selects the input device, INDATA consumes one word from it.
The CPU gets no feedback: talking to a device that is not there does nothing.
"""

import time
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
    """Buffer at 0xF0, like Logisim's Keyboard component.

    Every key goes into the buffer the moment it is typed: Enter as 0x0A,
    Backspace as 0x08 (the program decides what backspace means).  INDATA
    consumes one character; an empty buffer reads as 0, which is what the
    circuit's keyboard presents and what read_char / read_line poll on.
    """

    def __init__(self):
        self.buffer: deque[int] = deque()

    def type(self, text: str) -> None:
        self.buffer.extend(ord(c) for c in text)

    def read(self) -> int:
        return self.buffer.popleft() if self.buffer else 0

    def clear(self) -> None:
        self.buffer.clear()


class Timer:
    """Input device at 0x7C: milliseconds since the last reset, wrapping at
    32 bits (C's clock()). It follows the computer's own clock, so a program
    runs at the right speed however fast it is simulated; the window stops
    it while the simulation is paused. clock: a function giving seconds."""

    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.frozen = None          # the clock's reading when it was paused
        self.start = clock()

    def read(self) -> int:
        now = self.clock() if self.frozen is None else self.frozen
        return int((now - self.start) * 1000) & config.WORD_MASK

    def pause(self) -> None:
        if self.frozen is None:
            self.frozen = self.clock()

    def resume(self) -> None:
        if self.frozen is not None:
            self.start += self.clock() - self.frozen
            self.frozen = None

    def reset(self) -> None:
        """Back to 0; a paused timer stays paused."""
        self.start = self.clock()
        if self.frozen is not None:
            self.frozen = self.start


class Video:
    """RGB Video at 0x6C: one pixel per word (x bits 31-24, y bits 23-16,
    RGB565 colour bits 15-0). 0x6D clears it. Write-only, like the circuit."""

    def __init__(self, width=config.VIDEO_WIDTH, height=config.VIDEO_HEIGHT):
        self.width, self.height = width, height
        self.pixels = [0] * (width * height)     # RGB565, row by row
        self.dirty = set()                       # indices changed since the window drew
        self.used = False                        # has anything been drawn
        self.cleared = True                      # everything changed (window redraws all)

    def write(self, value: int) -> None:
        x = (value >> 24) & (self.width - 1)
        y = (value >> 16) & (self.height - 1)
        i = y * self.width + x
        self.pixels[i] = value & 0xFFFF
        self.dirty.add(i)
        self.used = True

    def clear(self) -> None:
        self.pixels = [0] * (self.width * self.height)
        self.dirty.clear()
        self.cleared = True

    @staticmethod
    def rgb(color: int) -> tuple:
        """RGB565 -> 8-bit (r, g, b), low bits filled like Logisim does."""
        r, g, b = (color >> 11) & 31, (color >> 5) & 63, color & 31
        return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)

    def png(self, scale: int = 1) -> bytes:
        """The screen as a PNG file (for headless runs)."""
        import struct
        import zlib
        rows = []
        for y in range(self.height):
            line = bytearray()
            for x in range(self.width):
                line += bytes(self.rgb(self.pixels[y * self.width + x])) * scale
            rows += [b"\0" + bytes(line)] * scale
        def chunk(kind, data):
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
        header = struct.pack(">IIBBBBB", self.width * scale, self.height * scale, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


class DeviceBus:
    def __init__(self):
        self.display = Display()
        self.keyboard = Keyboard()
        self.video = Video()
        self.timer = Timer()
        self.hex_value = None          # None = nothing sent yet (display blank)
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
        elif self.out_addr == config.HEX_DISPLAY_ADDR:
            self.hex_value = value & config.WORD_MASK
        elif self.out_addr == config.VIDEO_ADDR:
            self.video.write(value)
        elif self.out_addr == config.VIDEO_CLEAR_ADDR:
            self.video.clear()

    def in_data(self) -> int | None:
        """None means no input device is selected: nothing drives the bus,
        so the register keeps its value.  The keyboard gives 0 when empty."""
        if self.in_addr == config.KEYBOARD_ADDR:
            return self.keyboard.read()
        if self.in_addr == config.TIMER_ADDR:
            return self.timer.read()
        return None

    def reset(self) -> None:
        self.out_addr = self.in_addr = 0
        self.hex_value = None
        self.display.clear()
        self.keyboard.clear()
        self.video.clear()
        self.video.used = False
        self.timer.reset()
