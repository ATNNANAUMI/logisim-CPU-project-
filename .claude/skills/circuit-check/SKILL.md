---
name: circuit-check
description: Measure how the real Logisim circuit behaves for some instruction or edge case, compare it with the Python simulator, and record the result. Use when asked to check, confirm, verify or measure a behaviour "on the circuit", when the simulator and circuit may disagree, or to settle a TWEAKS guess in cpu_sim/src/config.py.
argument-hint: "<behaviour to check, e.g. 'does SUB set C when there is no borrow'>"
---

# Check a behaviour on the real circuit

The circuit (`logisim/CPU.circ`) is the ground truth; the simulator was written from the ISA. This workflow writes a diagnostic program, runs it on both, and records what the circuit does.

## 1. Write a diagnostic program

Create `compiler/examples/tests/diagNN.asm` with the next free number (look at the existing `diag*.asm`). Follow `diag11.asm`:

- A header listing every result line: its RAM address, what it measures, and the value expected under each competing hypothesis (e.g. "truncates" vs "rounds"), so the output can be read off directly.
- Store each result in a `.ram` `.space` area and also print it with `print_hex` + `print_newline` from the stdlib. Link the diag file **first** so its RAM data starts at `0x14000`.
- Put a fixed marker value in front of each test so a missing or shifted line is obvious.
- End with `HALT`.
- **No keyboard input.** The headless circuit run has no keyboard (stdin is closed), so anything that waits for a key hangs.
- Keep it short: the circuit simulates slowly (a few seconds for `hello.asm`), and each stdlib call costs many instructions.

## 2. Build and run on the simulator

```
python compiler/src/asm build compiler/examples/tests/diagNN.asm compiler/examples/stdlib/stdlib.asm
python cpu_sim/src/main.py compiler/ROM/diagNN.rom --headless --steps 2000000
```

Assembler errors print `file:line: message`. Fix them before going further.

## 3. Run on the real circuit

```
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diagNN.rom --seconds 300 --keep <scratchpad>/diagNN.circ
```

- `run_rom.py` finds the jar by itself (`$LOGISIM_JAR`, else `/usr/share/java/logisim-evolution/logisim-evolution.jar`).
- Pass `--keep` with a path in the scratchpad so the patched copy of the circuit isn't written into the repo.
- A finished run ends with `--- halted at HALT ---` (the `halt` output pin in `PC`). `--- exit: timeout ---` means the program didn't reach `HALT` in time: raise `--seconds` and run again, using `run_in_background` for long runs. Rough speed: `stdlib_demo` takes about 40 s on the circuit.
- Never edit `CPU.circ` itself; circuit changes are made by the user in Logisim.

## 4. Compare and record

Put the simulator and circuit results side by side for the user, line by line.

- **They agree:** the behaviour is now confirmed.
- **They differ:** the circuit wins. Change the simulator to match: flip the TWEAKS switch in `cpu_sim/src/config.py` if one exists, otherwise fix `alu.py` / `cpu.py`. Add a check to `cpu_sim/src/selftest.py` for the new behaviour. If the assembler or stdlib relied on the old behaviour, fix those too.
- **The circuit result makes no sense** (a likely circuit bug): report it and don't change the simulator; let the user decide.

Then update the docs that track this:

- the TWEAKS comment in `config.py` ("Confirmed on the circuit (YYYY-MM-DD): …");
- `TECHNICAL.md` §3.4 (TWEAKS table) and §8 (simulator vs. circuit), and §1 if the ISA description changes;
- the "Open questions / gotchas" list in `STRUCTURE.md`;
- the diag file's header: add the measured result, as `diag11.asm` does.

Finish with `python run.py test`, which must still pass.
