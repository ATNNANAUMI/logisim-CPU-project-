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


def test_div_by_zero_returns_dividend():
    # DATA R1,7 ; DATA R2,0 ; DIV R1,R2 ; MOD R1,R2
    cpu = run([0x0301, 7, 0x0302, 0, 0x1312, 0x1A12, 0x0F00])
    assert cpu.regs[0] == 7


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


def test_call_frame_and_return():
    # CALL ; CALL ; RET ; RET
    cpu = run([0x0B20, 0x0B20, 0x0B30, 0x0B30, 0x0F00])
    assert (cpu.esp, cpu.ebp) == (0, 0)


def test_float_round_trip():
    # DATA R1,3 ; FLOAT R1 ; CPY R0,R2 ; FINT R2
    cpu = run([0x0301, 3, 0x3601, 0x0E02, 0x3702, 0x0F00])
    assert cpu.regs[0] == 3


def test_float_div_by_zero_is_inf():
    # DATA R1,1.0 ; DATA R2,0.0 ; FDIV R1,R2
    cpu = run([0x0301, 0x3F800000, 0x0302, 0x00000000, 0x3312, 0x0F00])
    assert cpu.regs[0] == 0x7F800000


def test_keyboard_input():
    # DATA R1,0x0F ; COMM INADDR,R1 ; COMM INDATA,R2 ; COMM INDATA,R3
    cpu = run([0x0301, 0x0F, 0x0811, 0x0802, 0x0803, 0x0F00], keys="A")
    assert cpu.regs[2] == ord("A")
    assert cpu.regs[3] == 0              # buffer empty: register untouched


def test_addr_and_jmrb():
    # ADDR R1 ; JMRB R1 lands on the instruction after ADDR
    cpu = run([0x0901, 0x0A01, 0x0F00], steps=5)
    assert cpu.regs[1] == 1


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"\n{len(tests)} checks passed")


if __name__ == "__main__":
    main()
