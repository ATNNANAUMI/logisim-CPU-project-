# Claude through the circuit

The CPU is a terminal; Claude runs on the PC. Nothing here needs the shell, the OS,
the timer or interrupts.

    CPU (claude_term.rom) <-- port device 0x9C --> Telnet component <-- TCP --> bridge.py --> Claude API

## Run it

1. On the PC: `pip install anthropic` and a key (`ANTHROPIC_API_KEY`, or `ant auth login`).
   Without them, `--fake` answers from a canned script.
2. `python compiler/src/cc build logisim/claude/claude_term.c` gives `compiler/ROM/claude_term.rom`.
   Load it into the program ROM (in the `RAM` subcircuit) of the circuit.
3. In Logisim, set the Telnet component's Port (2323 here), Buffer (a few hundred) and
   Telnet Mode off, and start the simulation.
4. `python logisim/claude/bridge.py --port 2323` (it waits until the component is there).
5. Type a line on the keyboard and press Enter. Ctrl-X stops a reply, `/new` starts a new
   conversation, `/help` lists the commands of the PC side (`/model sonnet`, `/cost`, ...),
   Ctrl-D ends.

`python logisim/claude/test.py` checks the program in the simulator and the bridge (no network).
The same ROM runs in the simulator, whose Claude device is at 0x9C too:
`python cpu_sim/src/main.py compiler/ROM/claude_term.rom --claude-system logisim/claude/system.md`.

## What the circuit needs: the port at 0x9C

The program uses `device_out(0x9C, c)` and `device_in(0x9C)` (COMM). The protocol is the
simulator's Claude device (`cpu_sim/src/claude.py`), as bytes:

| CPU to PC (`OUTDATA`) | |
| --- | --- |
| a char | added to the line |
| 0 | end of the line: a message to Claude, or a command if it starts with `/` |
| 0x18 | a new conversation |
| 0x03 | stop the reply |
| 0x16 | the program starts (drops what is left of an old turn) |

| PC to CPU (`INDATA`) | |
| --- | --- |
| 0 | nothing yet (the device gives 0 when no byte is waiting) |
| 4 | the reply is over |
| anything else | a char of the reply (printable ASCII and newline) |

The `Telnet` component (read from the Logisim jar; not tried on the circuit): pins `IN`, `OUT`
(8 bits), `CLK`, `WR`, `RD`, `AVAIL`. On a rising `CLK`: `WR` = 1 sends `IN` to the client,
`RD` = 1 drops the oldest received byte. `OUT` shows that byte while `RD` = 1, `AVAIL` = 1 when
there is one. So the device is the usual one: decoder for 0x9C and a select flip-flop;

* `OUTDATA`: `IN` = bus[7:0], `WR` = 1, a `CLK` pulse from the write strobe (as `display` does);
* `INDATA`: bus = `AVAIL ? OUT : 0` through a controlled buffer, `RD` = 1 while it reads and the
  read strobe as `KEYBOARD` makes it, so the byte is gone after the CPU has it.

The CPU polls: no interrupt is needed. An interrupt would only save the polling loop.

## Test the port first: `port_test`

Before trusting Claude to it, check the wiring with a program that only echoes:

1. `python compiler/src/cc build logisim/claude/port_test.c`, load `compiler/ROM/port_test.rom`,
   start the simulation.
2. `python logisim/claude/port_test.py --port 2323` (or `socat - TCP:localhost:2323` and type).
   The script sends `?` and the program answers `READY` (the component drops what the CPU
   sends while no client is connected, so the program cannot announce itself at the start).
   Every letter you send comes back with its case flipped, so you can tell the CPU answered and
   not the wire; `#` makes it send the number of bytes it has taken so far (`?` counts too).
   The text display shows what arrived and the hex display counts it.
3. `port_test.py` checks a sentence, every printable byte and a burst of 100 bytes followed by
   `#`. The first two must pass (one byte at a time, `--delay` apart). The burst only reports:
   bytes lost means the component's Buffer overflowed while the CPU was busy printing; raise
   Buffer, or keep `--cps` low in `bridge.py`.

`python logisim/claude/test.py` runs the same two programs against a fake port in the simulator.

## Notes

* The CPU is slow: measured on the circuit it runs a few hundred instructions a second (the echo
  program, 120 instructions a byte, managed 2 bytes a second). `claude_term` writes the reply
  straight to the display and spends about 21 instructions a char (140 with stdio), so expect
  roughly 10 chars a second at most. The bridge sends at `--cps` chars a second (5 by default,
  0 = unlimited) so the component's Buffer, which holds only what its attribute says, does not
  overflow while the CPU prints: raise `--cps` as far as nothing is lost.
* No tools: Claude only talks (`bridge.py` turns them off and `system.md` says so).
* `--model`, `--system` and `--max-tokens` (400: short answers, less waiting) are on `bridge.py`.
* The conversation lives in `bridge.py`: it survives a reset of the circuit and is lost when the
  bridge stops. Everything typed is sent to Anthropic's API.
