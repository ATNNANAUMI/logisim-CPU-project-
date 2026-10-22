"""Quick checks that the core behaves as specified: python selftest.py"""

import config as config
from cpu import CPU

RAM = config.RAM_BIT


def run(words, steps=200, keys=""):
    cpu = CPU()
    cpu.mem.load_rom(words)
    if keys:
        cpu.bus.keyboard.type(keys)
    cpu.run(steps)
    return cpu


def test_immediate_and_flags():
    # DATA R1,10 ; ADD R1,#7 ; CPY R0,R2 ; CMP R1,R1
    cpu = run([0x0301, 10, 0x5010, 7, 0x0E02, 0x1F11, 0x0F00])
    assert cpu.regs[2] == 17, cpu.regs[2]
    assert cpu.regs[0] == 0                 # CMP writes 0 to R0
    assert cpu.flag("Z") and not cpu.flag("N")


def test_sub_negative_sets_n():
    # DATA R1,3 ; DATA R2,9 ; SUB R1,R2
    cpu = run([0x0301, 3, 0x0302, 9, 0x1112, 0x0F00])
    assert cpu.regs[0] == 0xFFFFFFFA
    assert cpu.flag("N") and not cpu.flag("A")


def test_carry_flag_matches_circuit():
    # Measured with diag12/diag13: SUB sets C on a borrow, CMP never sets it
    # DATA R1,3 ; DATA R2,5 ; SUB R1,R2   -> 3 < 5 unsigned: borrow, C on
    assert run([0x0301, 3, 0x0302, 5, 0x1112, 0x0F00]).flag("C")
    # DATA R1,5 ; DATA R2,3 ; SUB R1,R2   -> no borrow, C off
    assert not run([0x0301, 5, 0x0302, 3, 0x1112, 0x0F00]).flag("C")
    # DATA R1,3 ; DATA R2,5 ; CMP R1,R2   -> C off (A N Z still from 3 - 5)
    cpu = run([0x0301, 3, 0x0302, 5, 0x1F12, 0x0F00])
    assert not cpu.flag("C") and cpu.flag("N")
    # DATA R1,0xFFFFFFFF ; ++ R1          -> carry out, C on
    assert run([0x0301, 0xFFFFFFFF, 0x1B01, 0x0F00]).flag("C")


def test_div_and_mod_by_zero_match_circuit():
    # Measured with diag16/diag17: DIV by 0 gives the dividend, MOD by 0 gives 0
    # DATA R1,7 ; DATA R2,0 ; DIV R1,R2
    assert run([0x0301, 7, 0x0302, 0, 0x1312, 0x0F00]).regs[0] == 7
    # DATA R1,7 ; DATA R2,0 ; MOD R1,R2
    cpu = run([0x0301, 7, 0x0302, 0, 0x1A12, 0x0F00])
    assert cpu.regs[0] == 0 and cpu.flag("Z")


def test_ram_and_array():
    # DATA R1,RAM+0x100 ; DATA R2,0xBEEF ; ST R1,R2 ; DATA R3,2 ; AST R1,R3 ; ALD R1,R3
    addr = RAM | 0x100
    cpu = run([0x0301, addr, 0x0302, 0xBEEF, 0x0212,
               0x0303, 2, 0x0D13, 0x0C13, 0x0F00])
    assert cpu.mem.ram[0x100] == 0xBEEF
    assert cpu.mem.ram[0x102] == cpu.regs[0]


def test_rom_write_is_ignored():
    # DATA R1,0x100 (ROM) ; DATA R2,5 ; ST R1,R2
    cpu = run([0x0301, 0x100, 0x0302, 5, 0x0212, 0x0F00])
    assert cpu.mem.rom[0x100] == 0 and cpu.halted


def test_stack_push_pop_set_get():
    # DATA R0,0x11 ; PUSH ; DATA R0,0x22 ; PUSH ; POP ; GET R1(index 0)
    cpu = run([0x0300, 0x11, 0x0B00, 0x0300, 0x22, 0x0B00,
               0x0B10, 0x0301, 0, 0x0B51, 0x0F00])
    assert cpu.mem.ram[0] == 0x11 and cpu.mem.ram[1] == 0x22
    assert cpu.esp == 1
    assert cpu.regs[0] == 0x11          # GET index 0, counted from the bottom


def test_stk_set_get_wrap_across_ram():
    # Measured with diag11/diag16: EBP + RB wraps at 16 bits, across all of RAM
    # DATA R0,0xA1 ; DATA R1,-1 ; STK SET,R1       (EBP = 0: the last RAM word)
    # DATA R0,0xA2 ; DATA R1,0x8000 ; STK SET,R1   (RAM 0x18000, past the stack)
    # DATA R0,0 ; STK GET,R1
    cpu = run([0x0300, 0xA1, 0x0301, 0xFFFFFFFF, 0x0B41,
               0x0300, 0xA2, 0x0301, 0x8000, 0x0B41,
               0x0300, 0, 0x0B51, 0x0F00])
    assert cpu.mem.ram[0xFFFF] == 0xA1 and cpu.mem.ram[0x3FFF] == 0
    assert cpu.mem.ram[0x8000] == 0xA2 and cpu.mem.ram[0] == 0
    assert cpu.regs[0] == 0xA2


def test_call_frame_and_return():
    # CALL ; CALL ; RET ; RET
    cpu = run([0x0B20, 0x0B20, 0x0B30, 0x0B30, 0x0F00])
    assert (cpu.esp, cpu.ebp) == (0, 0)


def test_float_round_trip():
    # DATA R1,3 ; FLOAT R1 ; CPY R0,R2 ; FINT R2
    cpu = run([0x0301, 3, 0x3601, 0x0E02, 0x3702, 0x0F00])
    assert cpu.regs[0] == 3


def test_fcmp_flags_come_from_ra_minus_rb():
    # DATA R1,1.5 ; DATA R2,2.5 ; FCMP R1,R2   -> 1.5 - 2.5 < 0: N on, Z off
    cpu = run([0x0301, 0x3FC00000, 0x0302, 0x40200000, 0x3F12, 0x0F00])
    assert cpu.regs[0] == 0 and cpu.flag("N") and not cpu.flag("Z")
    # DATA R1,2.5 ; DATA R2,2.5 ; FCMP R1,R2   -> equal: Z on, N off
    cpu = run([0x0301, 0x40200000, 0x0302, 0x40200000, 0x3F12, 0x0F00])
    assert cpu.flag("Z") and not cpu.flag("N")


def test_float_div_by_zero_is_inf():
    # DATA R1,1.0 ; DATA R2,0.0 ; FDIV R1,R2
    cpu = run([0x0301, 0x3F800000, 0x0302, 0x00000000, 0x3312, 0x0F00])
    assert cpu.regs[0] == 0x7F800000


def test_float_special_cases_match_circuit():
    # Measured with diag14/diag15. FDIV R1,R2 with R1 = 0.0, R2 = 0.0 -> NaN
    cpu = run([0x0301, 0, 0x0302, 0, 0x3312, 0x0F00])
    assert cpu.regs[0] == 0x7FC00000
    # 1.0 / -0.0 -> -infinity
    cpu = run([0x0301, 0x3F800000, 0x0302, 0x80000000, 0x3312, 0x0F00])
    assert cpu.regs[0] == 0xFF800000
    # INT of +infinity -> FFFFFFFF, of -infinity -> 0, of 3e9 -> low 32 bits
    assert run([0x0301, 0x7F800000, 0x3701, 0x0F00]).regs[0] == 0xFFFFFFFF
    assert run([0x0301, 0xFF800000, 0x3701, 0x0F00]).regs[0] == 0
    assert run([0x0301, 0x4F32D05E, 0x3701, 0x0F00]).regs[0] == 0xB2D05E00


def test_float_shl_doubles():
    # Measured with diag16/diag17: float opcode 4 (SHL) writes RB x 2
    # DATA R2,5.0 ; float SHL R2
    assert run([0x0302, 0x40A00000, 0x3402, 0x0F00]).regs[0] == 0x41200000


def test_keyboard_input():
    # DATA R3,0x55 ; DATA R1,0xF0 ; COMM INADDR,R1 ; COMM INDATA,R2 ; COMM INDATA,R3
    cpu = run([0x0303, 0x55, 0x0301, 0xF0, 0x0811, 0x0802, 0x0803, 0x0F00], keys="A")
    assert cpu.regs[2] == ord("A")
    assert cpu.regs[3] == 0              # buffer empty: reads 0, like the circuit


def test_keyboard_backspace_is_a_key():
    # Backspace reaches the program as 0x08 (it is not an edit of the buffer)
    # DATA R1,0xF0 ; COMM INADDR,R1 ; COMM INDATA,R2 ; COMM INDATA,R3
    cpu = run([0x0301, 0xF0, 0x0811, 0x0802, 0x0803, 0x0F00], keys="7\b")
    assert (cpu.regs[2], cpu.regs[3]) == (ord("7"), 0x08)


def test_rgb_video():
    # DATA R1,0x6C ; COMM OUTADDR,R1 ; DATA R2,pixel ; COMM OUTDATA,R2 ; DATA R2,pixel ; COMM OUTDATA,R2
    # x = 3, y = 5, red; then x = 0x83 (only 7 bits wired: x = 3), y = 6, white
    cpu = run([0x0301, 0x6C, 0x0831, 0x0302, 0x0305F800, 0x0822,
               0x0302, 0x8306FFFF, 0x0822, 0x0F00])
    video = cpu.bus.video
    assert video.pixels[5 * video.width + 3] == 0xF800
    assert video.pixels[6 * video.width + 3] == 0xFFFF
    assert video.rgb(0xF800) == (255, 0, 0)
    # DATA R1,0x6D ; COMM OUTADDR,R1 ; COMM OUTDATA,R1  clears it
    cpu.halted = False
    cpu.mem.load_rom([0x0301, 0x6D, 0x0831, 0x0821, 0x0F00])
    cpu.iar = 0
    cpu.run(10)
    assert not any(video.pixels)


def test_addr_and_jmrb():
    # ADDR R1 ; JMRB R1 lands on the instruction after ADDR
    cpu = run([0x0901, 0x0A01, 0x0F00], steps=5)
    assert cpu.regs[1] == 1


def test_run_matches_step():
    # run() has its own copy of the instruction set (for speed); random code,
    # with plenty of edge-case words, must leave it exactly where step() does
    import random

    def state(cpu):
        return (cpu.regs, cpu.iar, cpu.flags, cpu.esp, cpu.ebp, cpu.halted,
                cpu.stopped, cpu.instructions, cpu.mem.ram, cpu.bus.display.text,
                cpu.bus.hex_value, cpu.bus.video.pixels, cpu.bus.out_addr,
                cpu.bus.in_addr, list(cpu.bus.keyboard.buffer))

    edges = [0, 1, 2, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0xFFFFFFFE,
             0x3F800000, 0x7F800000, RAM, RAM | 0x3FFF, 0x3FFF]
    rng = random.Random(1)
    saved = config.STOP_ON_STACK_WRAP
    try:
        for seed in range(120):
            config.STOP_ON_STACK_WRAP = seed % 2 == 1
            words = []
            for _ in range(400):
                pick = rng.random()
                if pick < 0.5:                  # an instruction, junk in the top bits
                    words.append(rng.randrange(0x8000) | rng.randrange(4) << 30)
                elif pick < 0.8:
                    words.append(rng.choice(edges))
                else:
                    words.append(rng.randrange(1 << 32))
            slow, fast, chunked = (run([], steps=0, keys="ab\b") for _ in range(3))
            for cpu in (slow, fast, chunked):
                cpu.mem.load_rom(words)
            for _ in range(2000):
                if slow.step() is None:
                    break
            fast.run(2000)
            while chunked.instructions < 2000 and chunked.run(min(7, 2000 - chunked.instructions)):
                pass
            assert state(fast) == state(slow), f"run() differs from step(), seed {seed}"
            assert state(chunked) == state(slow), f"run() in pieces differs, seed {seed}"
    finally:
        config.STOP_ON_STACK_WRAP = saved


def test_run_stops_at_breakpoints():
    # DATA R1,1 ; ADD R1,#1 ; RJMP back to the ADD
    cpu = run([0x0301, 1, 0x5010, 1, 0x0400, 0xFFFFFFFD], steps=0)
    assert cpu.run(100, stop_at={2}) == 1 and cpu.iar == 2     # stops before the ADD
    assert cpu.run(100, stop_at={2}) == 2 and cpu.iar == 2     # leaves it, comes back
    assert cpu.regs[0] == 2 and cpu.instructions == 3


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"\n{len(tests)} checks passed")


if __name__ == "__main__":
    main()