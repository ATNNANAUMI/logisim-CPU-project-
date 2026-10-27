"""Entry point.  Run it from the project root:

    python cpu_sim/src/main.py                                  open the window
    python cpu_sim/src/main.py compiler/ROM/hello.rom           open it with a ROM loaded
    python cpu_sim/src/main.py compiler/ROM/hello.rom --headless   run in the terminal
        (--screen out.png saves the RGB screen at the end)
    python cpu_sim/src/main.py prog.rom --disk disk.img        with a disk (created if missing)
"""

import argparse

from cpu import CPU
from memory import load_image


def build_cpu(rom_path=None, ram_path=None, disk_path=None) -> CPU:
    cpu = CPU()
    if rom_path:
        cpu.mem.load_rom(load_image(rom_path))
    if ram_path:
        cpu.mem.load_ram(load_image(ram_path))
    if disk_path:
        cpu.bus.attach_disk(disk_path)
    return cpu


def run_headless(cpu: CPU, max_steps: int, trace: bool, keys: str = "",
                 screen: str = "") -> None:
    if keys:
        cpu.bus.keyboard.type(keys)
    steps = 0
    while trace and steps < max_steps:
        step = cpu.step()
        if step is None:
            break
        operand = "" if step.operand is None else f" 0x{step.operand:08X}"
        print(f"0x{step.address:07X}  {step.word:08X}{operand:11s} "
              f"{step.text:<20s} {step.note}")
        steps += 1
    if not trace:
        cpu.run(max_steps)

    state = "HALTED" if cpu.halted else ("STOPPED: " + cpu.error) if cpu.stopped \
        else "step limit reached"
    print(f"\n--- {state} after {cpu.instructions} instructions ---")
    print("IAR 0x%07X   flags %s   ESP 0x%04X   EBP 0x%04X"
          % (cpu.iar, cpu.flag_text, cpu.esp, cpu.ebp))
    for i in range(0, 16, 4):
        print("  " + "  ".join(f"R{j:<2d} 0x{cpu.regs[j]:08X}" for j in range(i, i + 4)))
    if cpu.bus.hex_value is not None:
        print(f"\nHEX DISPLAY: {cpu.bus.hex_value:08X}")
    print("\nDISPLAY:")
    print(cpu.bus.display.text)
    if screen:
        with open(screen, "wb") as f:
            f.write(cpu.bus.video.png(scale=2))
        print(f"\n(RGB screen saved to {screen})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Logic-gate CPU simulator")
    parser.add_argument("rom", nargs="?", help="Logisim v2.0 raw ROM image")
    parser.add_argument("--ram", help="optional RAM image")
    parser.add_argument("--headless", action="store_true", help="no window")
    parser.add_argument("--steps", type=int, default=100_000)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--keys", default="", help="preload the keyboard buffer")
    parser.add_argument("--screen", default="", metavar="FILE.png",
                        help="save the RGB screen (device 0x6C) as a PNG at the end")
    parser.add_argument("--disk", metavar="FILE",
                        help="disk image for devices 0x8C/0x8D (created, 64 MB sparse, if missing)")
    args = parser.parse_args()

    try:
        cpu = build_cpu(args.rom, args.ram, args.disk)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    try:
        if args.headless:
            run_headless(cpu, args.steps, args.trace, args.keys, args.screen)
            return

        from gui import SimulatorWindow
        SimulatorWindow(cpu, rom_path=args.rom).mainloop()
    finally:
        cpu.bus.attach_disk(None)


if __name__ == "__main__":
    main()
