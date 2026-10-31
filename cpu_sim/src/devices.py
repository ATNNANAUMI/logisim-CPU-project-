"""Peripherals hanging off the COMM bus.

OUTADDR selects the output device, OUTDATA sends it a word.
INADDR selects the input device, INDATA consumes one word from it.
The CPU gets no feedback: talking to a device that is not there does nothing.
"""

import mmap
import os
import struct
import time
from collections import deque

import config as config


class Display:
    """Text console at 0x5C.  Takes ASCII values, 0x0A is a newline, 0x0C
    (form feed) clears it, as Logisim's TTY does.

    0x0D is a carriage return: back to the start of the line, and what comes
    next overwrites it (Logisim's TTY starts a new line instead; kept apart
    from 0x0A on purpose, TECHNICAL §8).  0x08 deletes the last char at the
    end of a line, as the TTY does; after a carriage return it moves back one.
    """

    def __init__(self):
        self.lines = [""]
        self.col = 0                    # where the next char goes in the last line

    def write(self, value: int) -> None:
        char = value & 0xFF
        line = self.lines[-1]
        if char == 0x0A:
            self.lines.append("")
            self.col = 0
        elif char == 0x0C:
            self.clear()
        elif char == 0x0D:
            self.col = 0
        elif char == 0x08:
            if self.col == len(line):
                self.lines[-1] = line[:-1]
            self.col = max(self.col - 1, 0)
        else:
            self.lines[-1] = line[:self.col] + chr(char) + line[self.col + 1:]
            self.col += 1

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def clear(self) -> None:
        self.lines = [""]
        self.col = 0


KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT = 28, 29, 30, 31
ARROW_KEYS = {"Up": KEY_UP, "Down": KEY_DOWN, "Left": KEY_LEFT, "Right": KEY_RIGHT}
# Ctrl+C and Ctrl+V stay with Tk (copy, paste); Tab and Esc are not keys of the buffer
TK_CTRL_KEYS = (0x03, 0x16)


def key_code(keysym: str, char: str) -> int | None:
    """What the keyboard buffer gets for a key, or None to ignore it (Tk keeps it).

    Printable ASCII is itself; Enter 0x0A, Backspace 0x08; the arrows 28 (up),
    29 (down), 30 (left), 31 (right); Ctrl+letter its ASCII code (Ctrl-A 1 ...
    Ctrl-Z 26, so Ctrl-D is 4, Ctrl-H is Backspace and Ctrl-J, Ctrl-M are
    Enter), except Ctrl-C and Ctrl-V.  Tab, Esc, Delete, function keys and the
    rest give nothing.  Simulator only: whether the circuit's Keyboard
    component buffers control codes is not measured (TECHNICAL 8).
    """
    if keysym in ("Return", "KP_Enter"):
        return 0x0A
    if keysym == "BackSpace":
        return 0x08
    if keysym in ARROW_KEYS:
        return ARROW_KEYS[keysym]
    if keysym in ("Tab", "ISO_Left_Tab", "Escape", "Delete"):
        return None
    if len(char) == 1:
        code = ord(char)
        if 32 <= code < 127:
            return code
        if 1 <= code <= 26 and code not in TK_CTRL_KEYS:
            return 0x0A if code == 0x0D else code
    return None


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
    RGB565 colour bits 15-0). 0x6D clears it. Write-only, like the circuit.
    Translated code writes pixels itself (translate.py's pixel()): keep
    the two in step."""

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


class Disk:
    """Persistent disk at 0x8C (seek) and 0x8D (data), simulator only.

    A binary file, 4 bytes per word, little-endian, mapped into memory, so
    a big disk costs nothing until it is used and every write reaches the
    file. A missing file is created as a sparse file of `words` words."""

    WORD = struct.Struct("<I")

    def __init__(self, path, words=config.DISK_WORDS):
        self.path = str(path)
        if not os.path.exists(self.path):
            with open(self.path, "wb") as f:
                f.truncate(words * 4)
        self.file = open(self.path, "r+b")
        size = os.fstat(self.file.fileno()).st_size
        if size == 0 or size % 4 or size // 4 > config.DISK_MAX_WORDS:
            self.file.close()
            raise ValueError(f"{self.path}: a disk is 1 to {config.DISK_MAX_WORDS} "
                             f"words of 4 bytes, this file has {size} bytes")
        self.words = size // 4
        self.map = mmap.mmap(self.file.fileno(), size)
        self.position = 0

    def seek(self, value: int) -> None:
        self.position = value & config.WORD_MASK

    def read(self) -> int:
        i = self.position
        self.position = (i + 1) & config.WORD_MASK
        return self.WORD.unpack_from(self.map, i * 4)[0] if i < self.words else 0

    def write(self, value: int) -> None:
        i = self.position
        self.position = (i + 1) & config.WORD_MASK
        if i < self.words:
            self.WORD.pack_into(self.map, i * 4, value & config.WORD_MASK)

    def close(self) -> None:
        if not self.map.closed:
            self.map.flush()
            self.map.close()
            self.file.close()


def _nothing(value: int) -> None:
    """OUTDATA to an address where no device listens."""


class _Output:
    """An output device attribute of DeviceBus (display, video, disk):
    putting another device there rewires send."""

    def __set_name__(self, owner, name):
        self.slot = "_" + name

    def __get__(self, bus, owner=None):
        return self if bus is None else getattr(bus, self.slot)

    def __set__(self, bus, device):
        setattr(bus, self.slot, device)
        bus._wire()


class DeviceBus:
    """send is the selected output device's own function: out_address()
    looks the device up once (in _outputs), so a word sent to it is one
    call, and replacing an output device rewires it (_Output)."""

    display = _Output()
    video = _Output()
    disk = _Output()                # Disk or None, attached with attach_disk()

    def __init__(self):
        self.out_addr = self.in_addr = 0
        self._display = Display()
        self._video = Video()
        self._disk: Disk | None = None
        self.keyboard = Keyboard()
        self.timer = Timer()
        self.hex_value = None          # None = nothing sent yet (display blank)
        self._wire()

    def _wire(self) -> None:
        """Which function each output address calls."""
        self._outputs = {
            config.DISPLAY_ADDR: self._display.write,
            config.HEX_DISPLAY_ADDR: self._hex,
            config.VIDEO_ADDR: self._video.write,
            config.VIDEO_CLEAR_ADDR: self._video_clear,
        }
        if self._disk is not None:
            self._outputs[config.DISK_DATA_ADDR] = self._disk.write
            self._outputs[config.DISK_SEEK_ADDR] = self._disk.seek
        self.out_address(self.out_addr)

    def _hex(self, value: int) -> None:
        self.hex_value = value & config.WORD_MASK

    def _video_clear(self, _value: int) -> None:
        self._video.clear()

    # ------------------------------------------------------------ COMM
    def out_address(self, value: int) -> None:
        self.out_addr = value & config.WORD_MASK
        self.send = self._outputs.get(self.out_addr, _nothing)

    def in_address(self, value: int) -> None:
        self.in_addr = value & config.WORD_MASK

    def out_data(self, value: int) -> None:
        self.send(value)

    def in_data(self) -> int | None:
        """None means no input device is selected: nothing drives the bus,
        so the register keeps its value.  The keyboard gives 0 when empty."""
        if self.in_addr == config.KEYBOARD_ADDR:
            return self.keyboard.read()
        if self.in_addr == config.TIMER_ADDR:
            return self.timer.read()
        disk = self._disk
        if disk is not None:
            if self.in_addr == config.DISK_DATA_ADDR:
                return disk.read()
            if self.in_addr == config.DISK_SEEK_ADDR:
                return disk.words
        return None

    def attach_disk(self, path) -> None:
        """Use the disk file at path (created if missing); None takes it out."""
        disk = None if path is None else Disk(path)
        if self.disk is not None:
            self.disk.close()
        self.disk = disk

    def reset(self) -> None:
        self.out_address(0)
        self.in_addr = 0
        self.hex_value = None
        self.display.clear()
        self.keyboard.clear()
        self.video.clear()
        self.video.used = False
        self.timer.reset()
        if self.disk is not None:          # the disk keeps its contents
            self.disk.position = 0
