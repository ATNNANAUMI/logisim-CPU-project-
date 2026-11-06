#!/usr/bin/env python3
"""Talk to port_test.rom through the circuit's Telnet component.

    python logisim/claude/port_test.py [--host localhost] [--port 2323] [--delay 0.3] [--burst 100]

Connects to the component (start the simulation first), sends ? and waits for
READY from the program (the component drops what the CPU sends while nobody is
connected, so the program answers only when asked), then checks:
  1. a sentence, one byte at a time (--delay seconds apart): each letter must
     come back with its case flipped, the rest unchanged;
  2. every printable ASCII byte except # and ?, one at a time, the same way;
  3. a burst of --burst bytes sent as fast as the socket takes them, then '#':
     the CPU says how many bytes it has taken; if fewer than were sent, the
     component's buffer (its Buffer attribute) overflowed while the CPU was busy.
Exit status 0 when 1 and 2 pass (3 only reports).
"""
import argparse
import re
import socket
import sys
import time


def flip(text):
    return "".join(chr(ord(c) ^ 0x20) if c.isascii() and c.isalpha() else c for c in text)


def read_until(sock, ending, limit):
    got, end = b"", time.time() + limit
    while not got.endswith(ending) and time.time() < end:
        try:
            got += sock.recv(256)
        except socket.timeout:
            pass
    return got


def one_by_one(sock, text, delay, limit):
    """Send text a byte at a time, waiting for the byte that comes back each time."""
    got = b""
    for c in text:
        sock.sendall(c.encode())
        end = time.time() + limit
        want = len(got) + 1
        while len(got) < want and time.time() < end:
            try:
                got += sock.recv(1)
            except socket.timeout:
                pass
        time.sleep(delay)
    return got.decode("latin-1")


def main(argv=None, sock=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=2323)
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between bytes in tests 1 and 2")
    ap.add_argument("--burst", type=int, default=100)
    ap.add_argument("--wait", type=float, default=60, help="seconds to wait for each answer")
    args = ap.parse_args(argv)
    if sock is None:
        print(f"connecting to {args.host}:{args.port} (the simulation must be running)")
        sock = socket.create_connection((args.host, args.port), timeout=10)
    sock.settimeout(0.05)
    print("sending ? and waiting for READY from the program")
    sock.sendall(b"?")
    if not read_until(sock, b"READY\n", args.wait).endswith(b"READY\n"):
        print("FAIL: no READY. Look at the circuit: does the text display say 'port test: waiting for bytes'?\n"
              "  no: the program is not running (ROM, clock, reset).\n"
              "  yes: does the hex display count the '?' (1)? no: the read path (INDATA) is not wired;\n"
              "       yes: the write path (OUTDATA to the component: WR, CLK, input) is not.")
        return 1
    failed = 0
    sentence = "Hello, World 123"
    got = one_by_one(sock, sentence, args.delay, args.wait)
    ok = got == flip(sentence)
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} a sentence: sent {sentence!r}, got {got!r}")
    printable = "".join(chr(c) for c in range(0x21, 0x7F) if chr(c) not in "#?")
    got = one_by_one(sock, printable, args.delay, args.wait)
    ok = got == flip(printable)
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} every printable byte but # and ? (92): "
          + ("all came back right" if ok else f"wrong, got {got!r}"))
    sent = 1 + len(sentence) + len(printable)       # the ? counts too
    sock.sendall(b"x" * args.burst + b"#")
    sent += args.burst + 1
    reply = read_until(sock, b"\n", args.wait)
    # the CPU also echoed each x: the count is the last line
    match = re.search(r"(\d+)\n$", reply.decode("latin-1"))
    try:
        counted = int(match.group(1))
        print(f"info a burst of {args.burst} bytes then '#': the CPU has taken {counted} of the {sent} sent so far"
              + ("" if counted == sent else f" ({sent - counted} lost: raise the component's Buffer or send slower)"))
    except AttributeError:
        print(f"info the burst got no count back (got {reply!r}): the CPU was probably still printing, try --wait 120")
    print("passed" if not failed else f"{failed} test(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
