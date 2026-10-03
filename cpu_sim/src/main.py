"""Entry point.  Every file lives in the same folder; run it from there.

    python main.py                          open the window
    python main.py print_a-z_fixed          open it with a ROM loaded
    python main.py abs_value --headless     run in the terminal
"""

import argparse

from cpu import CPU
from memory import load_image


def build_cpu(rom_path=None, ram_path=None) -> CPU:
    cpu = CPU()
    if rom_path:
        cpu.mem.load_rom(load_image(rom_path))
    if ram_path:
        cpu.mem.load_ram(load_image(ram_path))
    return cpu


def run_headless(cpu: CPU, max_steps: int, trace: bool, keys: str = "") -> None:
    if keys:
        cpu.bus.keyboard.type(keys)
    steps = 0
    while steps < max_steps:
        step = cpu.step()
        if step is None:
            break
        if trace:
            operand = "" if step.operand is None else f" 0x{step.operand:08X}"
            print(f"0x{step.address:05X}  {step.word:08X}{operand:11s} "
                  f"{step.text:<20s} {step.note}")
        steps += 1

    state = "HALTED" if cpu.halted else ("STOPPED: " + cpu.error) if cpu.stopped \
        else "step limit reached"
    print(f"\n--- {state} after {cpu.instructions} instructions ---")
    print("IAR 0x%05X   flags %s   ESP 0x%04X   EBP 0x%04X"
          % (cpu.iar, cpu.flag_text, cpu.esp, cpu.ebp))
    for i in range(0, 16, 4):
        print("  " + "  ".join(f"R{j:<2d} 0x{cpu.regs[j]:08X}" for j in range(i, i + 4)))
    print("\nDISPLAY:")
    print(cpu.bus.display.text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Logic-gate CPU simulator")
    parser.add_argument("rom", nargs="?", help="Logisim v2.0 raw ROM image")
    parser.add_argument("--ram", help="optional RAM image")
    parser.add_argument("--headless", action="store_true", help="no window")
    parser.add_argument("--steps", type=int, default=100_000)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--keys", default="", help="preload the keyboard buffer")
    args = parser.parse_args()

    cpu = build_cpu(args.rom, args.ram)
    if args.headless:
        run_headless(cpu, args.steps, args.trace, args.keys)
        return

    from gui import SimulatorWindow
    SimulatorWindow(cpu, rom_path=args.rom).mainloop()


if __name__ == "__main__":
    main()
