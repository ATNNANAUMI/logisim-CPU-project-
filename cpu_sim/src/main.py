"""Entry point.  Run it from the project root:

    python cpu_sim/src/main.py                                  open the window
    python cpu_sim/src/main.py compiler/ROM/hello.rom           open it with a ROM loaded
    python cpu_sim/src/main.py compiler/ROM/hello.rom --headless   run in the terminal
        (--screen out.png saves the RGB screen at the end)
    python cpu_sim/src/main.py prog.rom --disk disk.img        with a disk (created if missing)
    python cpu_sim/src/main.py prog.rom --claude-model sonnet  the model of the Claude device (0x9C)
    python cpu_sim/src/main.py prog.rom --headless --save-state run.state   the whole machine at the end
    python cpu_sim/src/main.py --load-state run.state [--disk d.img]        go on from there (snapshot.py)
"""

import argparse
import zipfile

from cpu import CPU
from memory import load_image


def build_cpu(rom_path=None, ram_path=None, disk_path=None, claude_model=None,
              claude_system=None) -> CPU:
    cpu = CPU()
    cpu.bus.claude.configure(claude_model, claude_system)
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
        cpu.run_sleeping(max_steps)
        if cpu.waiting:
            print("\n(WAIT with nothing that can wake the CPU: stopped)")

    state = "HALTED" if cpu.halted else ("STOPPED: " + cpu.error) if cpu.stopped \
        else "step limit reached"
    print(f"\n--- {state} after {cpu.instructions} instructions ---")
    print("IAR 0x%07X   flags %s   ESP 0x%06X   EBP 0x%06X"
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
    parser.add_argument("--screen-fps", type=int, default=30, metavar="N",
                        help="the window draws the RGB screen N times a second at most while a "
                             "program runs (default 30, 0 = at every tick)")
    parser.add_argument("--disk", metavar="FILE",
                        help="disk image for devices 0x8C/0x8D (created, 64 MB sparse, if missing)")
    parser.add_argument("--claude-model", metavar="NAME",
                        help="the Claude device's model (0x9C): haiku (default), sonnet, opus, "
                             "fable, or a model id; /model changes it later")
    parser.add_argument("--claude-system", metavar="FILE",
                        help="the Claude device's system prompt (default tynix/cpu_claude.md)")
    parser.add_argument("--load-state", metavar="FILE",
                        help="start from a snapshot (ROM, RAM, registers, devices) instead of a reset; "
                             "--disk attaches another disk than the one it names")
    parser.add_argument("--save-state", metavar="FILE",
                        help="headless: save a snapshot of the whole machine at the end")
    args = parser.parse_args()

    rom_path = args.rom
    try:
        cpu = build_cpu(args.rom, args.ram, None if args.load_state else args.disk,
                        args.claude_model, args.claude_system)
        if args.load_state:
            import snapshot
            saved_rom, warnings = snapshot.load(cpu, args.load_state, disk=args.disk)
            rom_path = rom_path or saved_rom
            for warning in warnings:
                print(f"warning: {warning}")
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    try:
        if args.headless:
            run_headless(cpu, args.steps, args.trace, args.keys, args.screen)
            if args.save_state:
                import snapshot
                snapshot.save(cpu, args.save_state, rom_path)
                print(f"(snapshot saved to {args.save_state})")
            return

        from gui import SimulatorWindow
        SimulatorWindow(cpu, rom_path=rom_path, screen_fps=args.screen_fps).mainloop()
    finally:
        cpu.bus.attach_disk(None)


if __name__ == "__main__":
    main()
