#!/usr/bin/env python3
"""The PC side of the Claude port: Logisim's Telnet component <-> the Claude API.

    python logisim/claude/bridge.py [--host localhost] [--port 2323] [--model haiku]
                                    [--system FILE] [--cps 5] [--max-tokens 400] [--fake]

The Telnet component of the circuit is a TCP server (its Port attribute). This
program is the client: it connects, hands every byte the CPU sends to the
simulator's Claude device (cpu_sim/src/claude.py: the line ends with a 0, / lines
are commands, 0x18 starts a new conversation, 0x03 stops a reply, history and
costs are kept here) and sends the device's reply back to the CPU one char at a
time. No tools: Claude only talks. The key comes from the environment
(ANTHROPIC_API_KEY, or an `ant auth login` profile) and `pip install anthropic`
is needed; --fake answers from a canned script instead (no network, no cost).

The CPU can't be fast: the reply goes out at --cps chars a second (0 = as fast
as it comes) so the component's buffer, which only holds what you set in its
Buffer attribute, doesn't overflow while the program prints. Set the Telnet
component to raw mode (Telnet Mode off): the bytes are plain ASCII, 0 never
travels to the CPU, and 4 ends a reply.
"""
import argparse
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cpu_sim" / "src"))
import claude  # noqa: E402


def make_device(model=None, system=None, max_tokens=400, fake=False):
    device = claude.ClaudeDevice(system_file=system or ROOT / "logisim" / "claude" / "system.md",
                                 backend=claude.FakeBackend(FAKE_SCRIPT * 50) if fake else None)
    device.configure(model, None)
    device.settings["tools"] = False
    device.settings["max_tokens"] = max_tokens
    return device


FAKE_SCRIPT = [claude.text_reply("Hello from the bridge. ", "This is a canned answer.\n")]


def serve(sock, device, cps, stop=lambda: False):
    """Move bytes until the connection closes: the CPU's go to device.write, the
    device's replies to the CPU at cps chars a second."""
    sock.setblocking(False)
    gap = 1.0 / cps if cps else 0.0
    next_send = 0.0
    while not stop():
        try:
            data = sock.recv(256)
            if not data:
                return
            for byte in data:
                device.write(byte)
        except BlockingIOError:
            pass
        except OSError:
            return
        now = time.monotonic()
        if now >= next_send:
            c = device.read()
            if c:
                try:
                    sock.send(bytes([c]))
                except (BlockingIOError, OSError):
                    device.out.appendleft(c)      # try again next time round
                next_send = now + gap
                continue
        time.sleep(0.001)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=2323, help="the Telnet component's Port attribute")
    ap.add_argument("--model", help="haiku, sonnet, opus or fable (default haiku)")
    ap.add_argument("--system", help="the system prompt file (default logisim/claude/system.md)")
    ap.add_argument("--cps", type=float, default=5, help="reply chars a second sent to the CPU (0 = no limit)")
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--fake", action="store_true", help="canned answers, no API")
    args = ap.parse_args()
    try:
        device = make_device(args.model, args.system, args.max_tokens, args.fake)
    except ValueError as e:
        ap.error(str(e))
    print(f"waiting for the Telnet component at {args.host}:{args.port} (start the simulation)")
    while True:
        try:
            sock = socket.create_connection((args.host, args.port), timeout=2)
        except OSError:
            time.sleep(1)
            continue
        print("connected")
        device.reset()
        serve(sock, device, args.cps)
        sock.close()
        print("the circuit closed the connection; waiting again (the conversation is kept)")


if __name__ == "__main__":
    main()
