"""A CHIP-8 reference interpreter in Python: the same machine as tynix/bin/chip8.c
(see its header for the choices where interpreters differ), used by the disk
self-check to compare the two on tynix/chip8/*.ch8.

    python tynix/chip8_ref.py FILE.ch8 FRAMES [CYCLES]   -> the state and screen as `chip8 -t` prints them
"""
import sys

FONT = [0xF0, 0x90, 0x90, 0x90, 0xF0, 0x20, 0x60, 0x20, 0x20, 0x70,
        0xF0, 0x10, 0xF0, 0x80, 0xF0, 0xF0, 0x10, 0xF0, 0x10, 0xF0,
        0x90, 0x90, 0xF0, 0x10, 0x10, 0xF0, 0x80, 0xF0, 0x10, 0xF0,
        0xF0, 0x80, 0xF0, 0x90, 0xF0, 0xF0, 0x10, 0x20, 0x40, 0x40,
        0xF0, 0x90, 0xF0, 0x90, 0xF0, 0xF0, 0x90, 0xF0, 0x10, 0xF0,
        0xF0, 0x90, 0xF0, 0x90, 0x90, 0xE0, 0x90, 0xE0, 0x90, 0xE0,
        0xF0, 0x80, 0x80, 0x80, 0xF0, 0xE0, 0x90, 0x90, 0x90, 0xE0,
        0xF0, 0x80, 0xF0, 0x80, 0xF0, 0xF0, 0x80, 0xF0, 0x80, 0x80]
W, H = 64, 32


def parse_hex(text):
    """The program's bytes: hex digit pairs, anything else separates, # comments."""
    out = []
    for line in text.splitlines():
        line = line.split("#")[0]
        digits = []
        for c in line + " ":
            if c in "0123456789abcdefABCDEF":
                digits.append(int(c, 16))
                continue
            for a, b in zip(digits[0::2], digits[1::2]):    # a lone digit at the end is dropped
                out.append(a * 16 + b)
            digits = []
    return out


class Chip8:
    def __init__(self, program):
        self.mem = [0] * 4096
        self.mem[:80] = FONT
        for i, b in enumerate(program[:4096 - 0x200]):
            self.mem[0x200 + i] = b
        self.v = [0] * 16
        self.stack = []
        self.pc, self.i, self.dt, self.st = 0x200, 0, 0, 0
        self.screen = [[0] * W for _ in range(H)]
        self.keys = [0] * 16
        self.rnd = 1
        self.waiting = -1

    def step(self):
        m, v = self.mem, self.v
        op = m[self.pc & 0xFFF] << 8 | m[(self.pc + 1) & 0xFFF]
        x, y, n, nn, nnn = (op >> 8) & 15, (op >> 4) & 15, op & 15, op & 0xFF, op & 0xFFF
        if self.waiting >= 0:
            for k in range(16):
                if self.keys[k] > 0:
                    v[self.waiting] = k
                    self.waiting = -1
                    self.pc += 2
                    return
            return
        self.pc += 2
        top = op >> 12
        if top == 0:
            if op == 0x00E0:
                self.screen = [[0] * W for _ in range(H)]
            elif op == 0x00EE and self.stack:
                self.pc = self.stack.pop()
        elif top == 1:
            self.pc = nnn
        elif top == 2:
            if len(self.stack) < 16:
                self.stack.append(self.pc)
            self.pc = nnn
        elif top == 3:
            self.pc += 2 if v[x] == nn else 0
        elif top == 4:
            self.pc += 2 if v[x] != nn else 0
        elif top == 5:
            self.pc += 2 if n == 0 and v[x] == v[y] else 0
        elif top == 6:
            v[x] = nn
        elif top == 7:
            v[x] = (v[x] + nn) & 255
        elif top == 8:
            if n == 0:
                v[x] = v[y]
            elif n == 1:
                v[x] |= v[y]
            elif n == 2:
                v[x] &= v[y]
            elif n == 3:
                v[x] ^= v[y]
            elif n == 4:
                r = v[x] + v[y]
                v[x], v[15] = r & 255, int(r > 255)
            elif n == 5:
                r = int(v[x] >= v[y])
                v[x], v[15] = (v[x] - v[y]) & 255, r
            elif n == 6:
                r = v[x] & 1
                v[x], v[15] = v[x] >> 1, r
            elif n == 7:
                r = int(v[y] >= v[x])
                v[x], v[15] = (v[y] - v[x]) & 255, r
            elif n == 14:
                r = v[x] >> 7
                v[x], v[15] = (v[x] << 1) & 255, r
        elif top == 9:
            self.pc += 2 if n == 0 and v[x] != v[y] else 0
        elif top == 10:
            self.i = nnn
        elif top == 11:
            self.pc = (nnn + v[0]) & 0xFFF
        elif top == 12:
            self.rnd = (self.rnd * 1103515245 + 12345) & 0xFFFFFFFF
            v[x] = ((self.rnd >> 16) & 0xFF) & nn
        elif top == 13:
            px, py = v[x] % W, v[y] % H
            v[15] = 0
            for row in range(n):
                if py + row >= H:
                    break
                bits = m[(self.i + row) & 0xFFF]
                for bit in range(8):
                    if px + bit >= W:
                        break
                    if bits & (0x80 >> bit):
                        if self.screen[py + row][px + bit]:
                            v[15] = 1
                        self.screen[py + row][px + bit] ^= 1
        elif top == 14:
            if nn == 0x9E and self.keys[v[x] & 15] > 0:
                self.pc += 2
            elif nn == 0xA1 and self.keys[v[x] & 15] <= 0:
                self.pc += 2
        elif top == 15:
            if nn == 0x07:
                v[x] = self.dt
            elif nn == 0x0A:
                self.waiting = x
                self.pc -= 2
            elif nn == 0x15:
                self.dt = v[x]
            elif nn == 0x18:
                self.st = v[x]
            elif nn == 0x1E:
                self.i = (self.i + v[x]) & 0xFFF
            elif nn == 0x29:
                self.i = (v[x] & 15) * 5
            elif nn == 0x33:
                m[self.i & 0xFFF], m[(self.i + 1) & 0xFFF], m[(self.i + 2) & 0xFFF] = v[x] // 100, v[x] // 10 % 10, v[x] % 10
            elif nn == 0x55:
                for k in range(x + 1):
                    m[(self.i + k) & 0xFFF] = v[k]
            elif nn == 0x65:
                for k in range(x + 1):
                    v[k] = m[(self.i + k) & 0xFFF]

    def frame(self, cycles):
        for _ in range(cycles):
            self.step()
        self.dt = max(0, self.dt - 1)
        self.st = max(0, self.st - 1)
        self.keys = [max(0, k - 1) for k in self.keys]

    def dump(self):
        lines = [f"PC={self.pc:04X} I={self.i:04X} SP={len(self.stack)} DT={self.dt:02X} ST={self.st:02X}",
                 " ".join(f"{b:02X}" for b in self.v)]
        for row in self.screen:
            lines.append("".join(f"{row[x] << 3 | row[x + 1] << 2 | row[x + 2] << 1 | row[x + 3]:X}" for x in range(0, W, 4)))
        return "\n".join(lines) + "\n"


def run(text, frames, cycles=10):
    machine = Chip8(parse_hex(text))
    for _ in range(frames):
        machine.frame(cycles)
    return machine.dump()


if __name__ == "__main__":
    print(run(open(sys.argv[1]).read(), int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 10), end="")
