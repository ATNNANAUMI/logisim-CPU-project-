#!/usr/bin/env python3
"""Self-check of logisim/claude: no network, no key (claude.FakeBackend).

    python logisim/claude/test.py

1. claude_term.c, built with the C compiler, runs in the simulator with its
   Claude device (0x9C) answering from a script: the typed line is echoed, the
   reply is printed wrapped at 64 columns with its words whole, /new is done by
   the program, and Ctrl-D halts the CPU.
2. bridge.py's serve() between a socket pair standing for the Telnet component:
   the CPU's bytes become a turn, the reply comes back char by char ending in 4,
   a / line is a command, and a 0x18 starts a new conversation.
3. port_test.c with port_test.py between them: a fake port device at 0x9C in the
   simulator (a loopback queue pair) behind a socket, as the Telnet component
   will be: sentence, every printable byte and a burst all come back right.
"""
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "cpu_sim" / "src"))
sys.path.insert(0, str(HERE))
import claude  # noqa: E402
import main as simulator  # noqa: E402
import bridge  # noqa: E402


def check_program():
    rom = ROOT / "compiler" / "ROM" / "claude_term.rom"
    subprocess.run([sys.executable, str(ROOT / "compiler/src/cc"), "build", str(HERE / "claude_term.c"),
                    "-o", str(rom)], check=True, capture_output=True)
    long_reply = " ".join(f"word{i:02d}" for i in range(30)) + "\n"
    cpu = simulator.build_cpu(str(rom))
    cpu.bus.claude.backend = claude.FakeBackend([claude.text_reply("Hello there. ", "Fine, thanks.\n"),
                                                 claude.text_reply(long_reply),
                                                 claude.text_reply("Bye now.")])
    cpu.bus.keyboard.type("hi\n/new\nlong\nbye\n\x04")
    cpu.run_sleeping(30_000_000)
    text = cpu.bus.display.text
    assert cpu.halted, text
    for want in ("you> hi", "Hello there. Fine, thanks.", "(a new conversation)", "you> long", "you> bye", "Bye now."):
        assert want in text, (want, text)
    lines = text.split("\n")
    assert all(len(l) <= 64 for l in lines), [l for l in lines if len(l) > 64]
    assert all(("word%02d" % i) in text for i in range(30)), text            # no word lost or cut
    assert len([l for l in lines if l.startswith("word")]) >= 3, text         # it did wrap
    h = cpu.bus.claude.history                    # /new forgot "hi": the history starts at "long"
    assert [m["role"] for m in h] == ["user", "assistant", "user", "assistant"] and h[0]["content"] == "long", h
    return "claude_term.c in the simulator"


def turn(sock, text, limit=5.0):
    sock.sendall(text.encode() + b"\0")
    got, start = [], time.time()
    while time.time() - start < limit:
        try:
            for byte in sock.recv(64):
                if byte == claude.EOT:
                    return bytes(got).decode()
                got.append(byte)
        except BlockingIOError:
            time.sleep(0.001)
    raise AssertionError("no EOT: " + bytes(got).decode())


def check_bridge():
    cpu_end, pc_end = socket.socketpair()
    cpu_end.setblocking(False)
    device = bridge.make_device(fake=True)
    stop = threading.Event()
    t = threading.Thread(target=bridge.serve, args=(pc_end, device, 0, stop.is_set), daemon=True)
    t.start()
    try:
        assert turn(cpu_end, "hi") == "Hello from the bridge. This is a canned answer.\n"
        assert [m["role"] for m in device.history] == ["user", "assistant"]
        assert "/model" in turn(cpu_end, "/help")
        assert device.settings["tools"] is False and device.settings["max_tokens"] == 400
        cpu_end.sendall(bytes([claude.CAN]))
        time.sleep(0.1)
        assert device.history == []
    finally:
        stop.set()
        t.join(2)
        cpu_end.close()
        pc_end.close()
    return "bridge.serve over a socket pair"


class FakePort:
    """What the Telnet component and its glue give the CPU: bytes in, bytes out, 0 for none."""

    def __init__(self):
        self.to_cpu, self.from_cpu = [], []
        self.lock = threading.Lock()

    def read(self):
        with self.lock:
            return self.to_cpu.pop(0) if self.to_cpu else 0

    def write(self, value):
        with self.lock:
            self.from_cpu.append(value & 0xFF)

    def reset(self):
        pass


def check_port_test():
    import io
    import contextlib
    import port_test
    rom = ROOT / "compiler" / "ROM" / "port_test.rom"
    subprocess.run([sys.executable, str(ROOT / "compiler/src/cc"), "build", str(HERE / "port_test.c"),
                    "-o", str(rom)], check=True, capture_output=True)
    cpu = simulator.build_cpu(str(rom))
    port = FakePort()
    cpu.bus.claude = port
    cpu.bus._wire()
    stop = threading.Event()
    cpu_end, pc_end = socket.socketpair()
    cpu_end.setblocking(False)

    def run_cpu():
        while not stop.is_set():
            cpu.run(20_000)

    def pump():                                      # the Telnet component: socket <-> port
        while not stop.is_set():
            try:
                for b in cpu_end.recv(64):
                    with port.lock:
                        port.to_cpu.append(b)
            except BlockingIOError:
                pass
            with port.lock:
                out, port.from_cpu = port.from_cpu, []
            if out:
                cpu_end.sendall(bytes(out))
            time.sleep(0.001)

    threads = [threading.Thread(target=f, daemon=True) for f in (run_cpu, pump)]
    for t in threads:
        t.start()
    try:
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            status = port_test.main(["--delay", "0", "--burst", "30", "--wait", "20"], sock=pc_end)
        assert status == 0, text.getvalue()
        assert "info a burst of 30 bytes then '#': the CPU has taken 140 of the 140 sent" in text.getvalue(), \
            text.getvalue()
        assert "Hello, World 123" in cpu.bus.display.text, cpu.bus.display.text
        assert cpu.bus.hex_value == 140
    finally:
        stop.set()
        for t in threads:
            t.join(2)
        cpu_end.close()
        pc_end.close()
    return "port_test.c and port_test.py over a fake port"


if __name__ == "__main__":
    for check in (check_program, check_bridge, check_port_test):
        print("ok   " + check())
