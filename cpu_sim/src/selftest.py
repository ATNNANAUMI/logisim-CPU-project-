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


def test_ld_note_names_the_address_read():
    # DATA R1,RAM+0x100 ; DATA R2,0x1234 ; ST R1,R2 ; LD R1,R1 (ra == rb: R1 is overwritten)
    cpu = CPU()
    cpu.mem.load_rom([0x0301, RAM | 0x100, 0x0302, 0x1234, 0x0212, 0x0111, 0x0F00])
    notes = [cpu.step().note for _ in range(4)]
    assert cpu.regs[1] == 0x1234
    assert f"{RAM | 0x100:0{config.ADDR_DIGITS}X}" in notes[3], notes[3]


def test_step_line_stops_at_lines_breakpoints_and_halt():
    from debuginfo import DebugInfo, step_line
    # 0: DATA R1,0 (line 1)   2: ++ R1 (line 2)   3: ++ R1   4: ++ R1 (line 3)   5: HALT
    info = DebugInfo(lines=[(0, "f.c", 1), (2, "f.c", 2), (4, "f.c", 3)])

    def fresh():
        cpu = CPU()
        cpu.mem.load_rom([0x0301, 0, 0x1B01, 0x1B01, 0x1B01, 0x0F00])
        return cpu

    cpu = fresh()
    assert step_line(cpu, info) == "line" and cpu.iar == 2
    assert step_line(cpu, info) == "line" and cpu.iar == 4 and cpu.instructions == 3
    assert step_line(cpu, info) == "halted" and cpu.halted
    cpu = fresh()
    cpu.iar = 2
    cpu.breakpoints.add(3)
    assert step_line(cpu, info) == "breakpoint" and cpu.iar == 3
    cpu = fresh()
    cpu.iar = 2
    assert step_line(cpu, info, limit=1) == "limit" and cpu.iar == 3
    assert step_line(cpu, info, limit=1) == "line" and cpu.iar == 4


def test_isa_agrees_with_the_assemblers_tables():
    """encoding.py (assembler) and isa.py (this decoder) are written apart; they must still agree."""
    import sys
    from pathlib import Path
    import isa
    asm_dir = str(Path(__file__).resolve().parents[2] / "compiler" / "src" / "asm")
    sys.path.insert(0, asm_dir)
    try:
        import encoding as enc
    finally:
        sys.path.remove(asm_dir)
    alias = {"++": "INC", "--": "DEC"}
    for name, (opcode, shape) in enc.SYSTEM_OPS.items():
        ins = isa.decode(enc.word(enc.SYSTEM, opcode, 3, 5))
        assert ins.name == name and not ins.is_alu, name
        assert (shape in enc.TWO_WORD_SHAPES) == ins.takes_operand, name
    for name, (prefix, opcode, shape) in enc.ALU_OPS.items():
        for imm in (0, enc.IMMEDIATE):
            ins = isa.decode(enc.word(prefix | imm, opcode, 3, 5))
            want = alias.get(name, name)
            if name in ("FADD", "FSUB", "FMULT", "FDIV", "FNEG", "FCMP"):
                want = name[1:]                                # FADD is ADD in the float group
            assert ins.name == want and ins.is_alu and ins.is_float == (prefix == enc.FLOAT_ALU), name
            assert ins.is_imm == bool(imm) and ins.takes_operand == bool(imm), name
            assert (ins.name in isa.ONE_OPERAND) == (shape == "alu1"), name
    assert {v: k for k, (v, _) in enc.STK_OPS.items()} == isa.STK_OPS
    assert {v: k for k, v in enc.COMM_OPS.items()} == isa.COMM_OPS
    assert enc.FLAGS == isa.FLAG_BITS


def test_window_pacing():
    """gui.py's settle() and screen_due(): the window shows the RGB screen
    between bursts of drawing, and not more often than asked."""
    try:
        import gui
    except ImportError:                 # no tkinter: the window cannot run here either
        return

    class Screen:
        dirty, cleared, writes = set(), False, 0

    def program(draws):                 # draws(k): does chunk number k add pixels?
        video, calls, now = Screen(), [], [0.0]
        video.dirty = set()

        def execute(count):
            calls.append(count)
            if draws(len(calls)):
                video.dirty |= {(len(calls), i) for i in range(3)}
                video.writes += 3
            now[0] += 0.001
        return video, execute, calls, lambda: now[0]

    video, execute, calls, clock = program(lambda k: k <= 5)       # draws for 5 chunks, then stops
    assert gui.settle(execute, video, clock, until=1.0) is True and len(calls) == 6
    video, execute, calls, clock = program(lambda k: False)        # quiet already: one look
    assert gui.settle(execute, video, clock, until=1.0) is True and len(calls) == 1
    video, execute, calls, clock = program(lambda k: True)         # never quiet: gives up at the limit
    assert gui.settle(execute, video, clock, until=0.0105) is False and len(calls) == 11
    assert gui.settle(execute, video, clock, until=9.0, running=lambda: False) is False
    assert len(calls) == 11                                        # a stopped program is not run on
    assert gui.hold_screen(True, False, 1.0, 0.9, 0.25) is True    # still drawing: keep the last picture
    assert gui.hold_screen(True, True, 1.0, 0.9, 0.25) is False    # quiet: show it
    assert gui.hold_screen(True, False, 1.0, 0.5, 0.25) is False   # held long enough: show it anyway
    assert gui.hold_screen(False, False, 1.0, 0.9, 0.25) is False  # a stopped program: what is there is shown
    video, execute, calls, clock = program(lambda k: False)        # a clear in the middle counts as drawing
    inner = execute
    video.cleared = False

    def clearing(count):
        inner(count)
        video.cleared = len(calls) <= 2
    assert gui.settle(clearing, video, clock, until=1.0) is True and len(calls) == 2

    assert gui.screen_due(False, 0.0, 0.0, 1 / 30)                 # paused: always
    assert not gui.screen_due(True, 0.020, 0.0, 1 / 30) and gui.screen_due(True, 0.034, 0.0, 1 / 30)
    assert gui.screen_due(True, 0.0, 0.0, 0.0)                     # no limit: every time


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
    # Measured with diag11/diag16: EBP + RB wraps at the RAM's address width,
    # across all of RAM (16 bits on the circuit then, 24 now)
    # DATA R0,0xA1 ; DATA R1,-1 ; STK SET,R1       (EBP = 0: the last RAM word)
    # DATA R0,0xA2 ; DATA R1,0x8000 ; STK SET,R1   (RAM word 0x8000, past the stack)
    # DATA R0,0 ; STK GET,R1
    cpu = run([0x0300, 0xA1, 0x0301, 0xFFFFFFFF, 0x0B41,
               0x0300, 0xA2, 0x0301, 0x8000, 0x0B41,
               0x0300, 0, 0x0B51, 0x0F00])
    assert cpu.mem.ram[config.BANK_MASK] == 0xA1 and cpu.mem.ram[0x3FFF] == 0
    assert cpu.mem.ram[0x8000] == 0xA2 and cpu.mem.ram[0] == 0
    assert cpu.regs[0] == 0xA2


def test_whole_address_range():
    # The last words of RAM and ROM: ST/LD there, a jump far up into ROM and
    # back, and an address with a bit above the IAR's top dropped.
    top_ram = RAM | config.BANK_MASK
    far = config.BANK_WORDS - 4                     # the last few ROM words
    words = [0x0301, top_ram, 0x0302, 0x1234, 0x0212,   # ST [top of RAM], R2
             0x0113,                                     # LD R3, [top of RAM]
             0x0400, far - 7,                            # RJMP far (offset from word 7)
             0x0F00]                                     # 8: HALT, where far jumps back to
    for fast in (False, True):
        cpu = CPU()
        cpu.mem.load_rom(words)
        cpu.mem.rom[far:] = [0x0304, 0xABCD, 0x0400, 8 - (far + 3)]   # DATA R4 ; RJMP 8
        if fast:
            cpu.run(100)
        else:
            while cpu.step() is not None:
                pass
        assert cpu.mem.ram[config.BANK_MASK] == 0x1234 and cpu.regs[3] == 0x1234
        assert cpu.regs[4] == 0xABCD and cpu.halted and cpu.iar == 9
    assert cpu.mem.read(top_ram | 1 << 31) == 0x1234     # bits above the bus are ignored


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


def test_key_codes():
    from devices import key_code
    assert key_code("a", "a") == ord("a") and key_code("space", " ") == 32 and key_code("asciitilde", "~") == 126
    assert key_code("Return", "\r") == 10 and key_code("KP_Enter", "\r") == 10 and key_code("BackSpace", "\x08") == 8
    assert [key_code(k, "") for k in ("Up", "Down", "Left", "Right")] == [28, 29, 30, 31]
    assert key_code("d", "\x04") == 4 and key_code("s", "\x13") == 19 and key_code("z", "\x1a") == 26
    assert key_code("h", "\x08") == 8 and key_code("j", "\n") == 10 and key_code("m", "\r") == 10
    assert key_code("Tab", "\t") == 9 and key_code("i", "\t") == 9
    for keysym, char in (("c", "\x03"), ("v", "\x16"), ("ISO_Left_Tab", ""), ("Escape", "\x1b"),
                         ("Delete", "\x7f"), ("F1", ""), ("Home", ""), ("e", "\xe9")):
        assert key_code(keysym, char) is None, (keysym, char)
    # a program sees the arrow as 30, then 0 (empty buffer)
    cpu = run([0x0301, 0xF0, 0x0811, 0x0802, 0x0803, 0x0F00], keys=chr(30))
    assert (cpu.regs[2], cpu.regs[3]) == (30, 0)


def test_display_controls():
    # "ab", backspace, "c", newline, "x", form feed (clears it, like Logisim's TTY), "d"
    # DATA R1,0x5C ; COMM OUTADDR,R1 ; then DATA R2,char ; COMM OUTDATA,R2 for each
    chars = "ab\bc\nx"
    words = [0x0301, 0x5C, 0x0831]
    for c in chars:
        words += [0x0302, ord(c), 0x0822]
    cpu = run(words + [0x0F00])
    assert cpu.bus.display.text == "ac\nx"
    cpu.halted = False
    cpu.mem.load_rom([0x0301, 0x5C, 0x0831, 0x0302, 0x0C, 0x0822, 0x0302, ord("d"), 0x0822, 0x0F00])
    cpu.iar = 0
    cpu.run(20)
    assert cpu.bus.display.text == "d"
    # carriage return: back to the start of the line, then overwrite (not the TTY's new line)
    display = cpu.bus.display
    for c in "\n 50%\r100%\nhello\rJ\nab\r\b":
        display.write(ord(c))
    assert display.text == "d\n100%\nJello\nab"


def test_rgb_video():
    # DATA R1,0x6C ; COMM OUTADDR,R1 ; DATA R2,pixel ; COMM OUTDATA,R2 ; ... (three pixels)
    # x = 3, y = 5, red; x = 0x83, y = 6, white; x = 255, y = 255 (the last pixel), blue
    cpu = run([0x0301, 0x6C, 0x0831, 0x0302, 0x0305F800, 0x0822,
               0x0302, 0x8306FFFF, 0x0822, 0x0302, 0xFFFF001F, 0x0822, 0x0F00])
    video = cpu.bus.video
    assert (video.width, video.height) == (256, 256) and len(video.pixels) == 256 * 256
    assert video.pixels[5 * 256 + 3] == 0xF800
    assert video.pixels[6 * 256 + 0x83] == 0xFFFF and video.pixels[6 * 256 + 3] == 0
    assert video.pixels[256 * 256 - 1] == 0x001F
    assert sum(1 for p in video.pixels if p) == 3
    assert video.rgb(0xF800) == (255, 0, 0)
    # a smaller screen wires fewer bits: 128 x 128 keeps the low 7 bits of x and y
    from devices import Video
    small = Video(128, 128)
    small.write(0x8306FFFF)
    assert small.pixels[6 * 128 + 3] == 0xFFFF
    # DATA R1,0x6D ; COMM OUTADDR,R1 ; COMM OUTDATA,R1  clears it
    cpu.halted = False
    cpu.mem.load_rom([0x0301, 0x6D, 0x0831, 0x0821, 0x0F00])
    cpu.iar = 0
    cpu.run(10)
    assert not any(video.pixels)


def test_timer():
    # DATA R1,0x7C ; COMM INADDR,R1 ; COMM INDATA,R2 ; COMM INDATA,R3 ; HALT
    # with a clock (in seconds) that the test moves on by hand
    from devices import Timer
    now = [0.0]
    words = [0x0301, 0x7C, 0x0811, 0x0802, 0x0803, 0x0F00]
    for fast in (False, True):
        now[0] = 100.0
        cpu = CPU()
        cpu.mem.load_rom(words)
        cpu.bus.timer = Timer(clock=lambda: now[0])
        now[0] = 100.25                         # 250 ms after the start
        if fast:
            cpu.run(3)
        else:
            for _ in range(3):
                cpu.step()
        now[0] = 100.2505 + (1 << 32) / 1000    # wraps at 32 bits
        cpu.run(10) if fast else [cpu.step() for _ in range(10)]
        assert (cpu.regs[2], cpu.regs[3]) == (250, 250), (cpu.regs[2], cpu.regs[3])
    timer = Timer(clock=lambda: now[0])
    now[0] = 5.0
    timer.reset()
    now[0] = 5.125
    timer.pause()                               # stopped at 125 ms ...
    now[0] = 9.0
    assert timer.read() == 125
    timer.reset()                               # ... a reset while paused stays paused
    assert timer.read() == 0
    timer.resume()
    now[0] = 9.0625
    assert timer.read() == 62


def test_disk():
    import os
    import tempfile
    from devices import Disk
    # seek to 5, write two words; seek to 6, read two words; read the size
    words = [0x0301, 0x8C, 0x0831, 0x0302, 5, 0x0822,             # OUTADDR 0x8C, OUTDATA 5
             0x0301, 0x8D, 0x0831, 0x0302, 0xDEADBEEF, 0x0822,    # OUTADDR 0x8D, 2 words
             0x0302, 0x12345678, 0x0822,
             0x0301, 0x8C, 0x0831, 0x0302, 6, 0x0822,             # seek to 6
             0x0301, 0x8D, 0x0811, 0x0803, 0x0804,                # INADDR 0x8D, INDATA R3, R4
             0x0301, 0x8C, 0x0811, 0x0805, 0x0F00]                # INADDR 0x8C, INDATA R5
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "disk.img")
        for fast in (False, True):
            cpu = CPU()
            cpu.mem.load_rom(words)
            cpu.bus.disk = Disk(path, words=64)                  # created on the first pass
            if fast:
                cpu.run(100)
            else:
                while cpu.step() is not None:
                    pass
            assert (cpu.regs[3], cpu.regs[4], cpu.regs[5]) == (0x12345678, 0, 64)
            assert cpu.bus.disk.position == 8
            cpu.reset()                                         # rewinds, keeps the disk
            assert cpu.bus.disk.position == 0
            cpu.bus.attach_disk(None)
        assert os.path.getsize(path) == 256
        disk = Disk(path)                                       # an existing file keeps its size
        disk.seek(5)
        assert (disk.words, disk.read()) == (64, 0xDEADBEEF)
        disk.seek(63)
        disk.write(7)
        disk.write(8)                                           # past the end: dropped
        assert disk.read() == 0 and disk.position == 66
        disk.close()
        with open(path, "rb") as f:
            data = f.read()
        assert data[20:24] == bytes.fromhex("efbeadde") and data[252:] == bytes([7, 0, 0, 0])
        with open(path, "ab") as f:
            f.write(b"x")
        try:
            Disk(path)
        except ValueError:
            pass
        else:
            raise AssertionError("a file that isn't whole words was accepted")
    # with no disk the ports are not driven: INDATA leaves the register alone
    # DATA R6,7 ; DATA R1,0x8D ; COMM INADDR,R1 ; COMM INDATA,R6
    assert run([0x0306, 7, 0x0301, 0x8D, 0x0811, 0x0806, 0x0F00]).regs[6] == 7


def test_addr_and_jmrb():
    # ADDR R1 ; JMRB R1 lands on the instruction after ADDR
    cpu = run([0x0901, 0x0A01, 0x0F00], steps=5)
    assert cpu.regs[1] == 1


def test_run_matches_step():
    # run() has its own copies of the instruction set (for speed: the
    # _interpret() loop, and translate.py's blocks once code gets hot); random
    # code, with plenty of edge-case words, must leave it exactly where step() does
    import random

    def state(cpu):
        return (cpu.regs, cpu.iar, cpu.flags, cpu.esp, cpu.ebp, cpu.halted,
                cpu.stopped, cpu.instructions, cpu.mem.ram, cpu.bus.display.text,
                cpu.bus.hex_value, cpu.bus.video.pixels, cpu.bus.out_addr,
                cpu.bus.in_addr, list(cpu.bus.keyboard.buffer),
                cpu.slimit, cpu.ie, cpu.in_nmi, cpu.inhibit, cpu.waiting, cpu.fault_pending)

    edges = [0, 1, 2, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0xFFFFFFFE,
             0x3F800000, 0x7F800000, RAM, RAM | 0x3FFF, 0x3FFF,
             RAM | config.BANK_MASK, config.BANK_MASK]
    rng = random.Random(1)
    # Banks are 16M words, so three machines are made once and share one ROM
    # (a CPU never writes ROM). RAM is not cleared between programs: the
    # three end every program equal, so they start the next one equal too.
    slow, fast, chunked = CPU(), CPU(), CPU()
    rom = slow.mem.rom
    from devices import Timer
    for cpu in (slow, fast, chunked):           # the same time for all three
        cpu.bus.timer = Timer(clock=lambda: 0.0)
    if True:
        for seed in range(80):
            words = []
            for _ in range(400):
                pick = rng.random()
                if pick < 0.5:                  # an instruction, junk in the top bits
                    words.append(rng.randrange(0x8000) | rng.randrange(4) << 30)
                elif pick < 0.8:
                    words.append(rng.choice(edges))
                else:
                    words.append(rng.randrange(1 << 32))
            rom[:len(words)] = words
            for cpu in (slow, fast, chunked):
                cpu.reset(clear_ram=False)
                cpu.mem.rom = rom
                cpu.bus.keyboard.type("ab\b")
            for _ in range(2000):
                if slow.step() is None:
                    break
            fast.run(2000)
            while chunked.instructions < 2000 and chunked.run(min(7, 2000 - chunked.instructions)):
                pass
            assert state(fast) == state(slow), f"run() differs from step(), seed {seed}"
            assert state(chunked) == state(slow), f"run() in pieces differs, seed {seed}"


def test_translated_code_matches_step():
    # run() translates code into Python (translate.py), here as soon as it
    # is reached: random code shaped like a program (loops and branches,
    # calls, the stack, memory, devices, edge-case values, each TWEAKS
    # setting; in ROM, or in RAM where it gets written over) must leave it
    # exactly where step() does, also in pieces
    import random
    import translate
    from devices import Timer

    def state(cpu):
        return (cpu.regs, cpu.iar, cpu.flags, cpu.esp, cpu.ebp, cpu.halted, cpu.stopped,
                cpu.instructions, cpu.mem.ram, cpu.bus.display.text, cpu.bus.hex_value,
                cpu.bus.video.pixels, cpu.bus.video.dirty, cpu.bus.video.used,
                cpu.bus.out_addr, cpu.bus.in_addr, list(cpu.bus.keyboard.buffer),
                cpu.slimit, cpu.ie, cpu.in_nmi, cpu.inhibit, cpu.waiting, cpu.fault_pending)

    rng = random.Random(3)
    values = [0, 1, 2, 3, 7, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0xFFFFFFFE, 0x3F800000,
              0xBF800000, 0x7F800000, 0x7FC00000, 0x00800000, 0x3FFF, 0x4000, RAM, RAM | 0x3FFF,
              RAM | 0x5000, RAM | 0x5003, RAM | config.BANK_MASK, config.BANK_MASK, 0x5C, 0x3C,
              0x6C, 0xF0, 0x7C, 0x0305F800] + [RAM | 0x5000 + i for i in (1, 5, 8, 13, 21, 34, 55)]

    def program():
        """[(words of one instruction)]; jump offsets are filled in later."""
        code = []
        for _ in range(rng.randrange(20, 120)):
            pick, ra, rb = rng.random(), rng.randrange(6), rng.randrange(6)
            if pick < 0.30:                                     # ALU, sometimes an immediate
                word = 0x1000 | rng.randrange(16) << 8 | ra << 4 | rb
                word |= 0x2000 if rng.random() < 0.15 else 0
                code.append([word | 0x4000, rng.choice(values)] if rng.random() < 0.3 else [word])
            elif pick < 0.42:                                   # DATA (often a word of the RAM copy)
                code.append([0x0300 | rb, rng.choice(values) if rng.random() < 0.6
                             else RAM | 0x5000 + rng.randrange(60)])
            elif pick < 0.52:                                   # CPY LD ST ALD AST ADDR
                code.append([rng.choice((0x0E, 0x0E, 0x01, 0x02, 0x0C, 0x0D, 0x09)) << 8 | ra << 4 | rb])
            elif pick < 0.60:                                   # STK
                code.append([0x0B00 | rng.choice((0, 0, 1, 1, 2, 3, 4, 5, 6)) << 4 | rb])
            elif pick < 0.64:                                   # RTI EI DI TRAP WAIT GSP SSP GBP SBP SLIM
                op = rng.choice((0, 1, 1, 2, 2, 3, 4, 5, 5, 6, 7, 7, 8, 9, 9, 9))
                code.append([0x2000 | op << 8 | (rb if op >= 5 else 0)])
            elif pick < 0.82:                                   # RJMP RJF RJNF (target later)
                code.append([rng.choice((0x04, 0x05, 0x06, 0x06)) << 8 | rng.randrange(16), None])
            elif pick < 0.87:                                   # CALL-like DATA R0, x ; JMRB R0
                code.append([0x0300, None])
                code.append([0x0A00])
            elif pick < 0.95:                                   # COMM
                if rng.random() < 0.3:      # a pixel: DATA RB, device ; OUTADDR RB ; OUTDATA RA
                    code.append([0x0300 | rb, rng.choice((0x6C, 0x6C, 0x6D, 0x5C))])
                    code.append([0x0830 | rb])
                    code.append([0x0820 | ra])
                else:
                    code.append([0x0800 | rng.randrange(4) << 4 | rb])
            else:                                               # NOP, CLF, now and then HALT
                code.append([0x0F00 if rng.random() < 0.03 else rng.choice((0x0000, 0x0700))])
        code.append([0x0400, None])                             # and round again
        starts, address = [], 0
        for words in code:
            starts.append(address)
            address += len(words)
        words = []
        for i, item in enumerate(code):
            if item[-1] is None:                                # a jump: near, now and then far
                ahead = rng.randrange(-12, 0) if rng.random() < 0.2 else rng.randrange(1, 12)
                there = starts[max(0, min(len(code) - 1, i + ahead))]
                if i == len(code) - 1:
                    there = 0
                elif rng.random() < 0.004:
                    there = rng.choice((RAM | 0x5000, config.BANK_WORDS - 3, address + 5))
                if item[0] >> 8 == 0x03:
                    item = [item[0], there]                     # DATA R0, target
                else:
                    item = [item[0], (there - (starts[i] + 1)) & config.WORD_MASK]
            words += item
        return words

    saved = (config.A_FLAG_SIGNED, config.SHR_ARITHMETIC, translate.HOT)
    slow, fast, chunked = CPU(), CPU(), CPU()
    rom = slow.mem.rom
    for cpu in (slow, fast, chunked):
        cpu.bus.timer = Timer(clock=lambda: 0.0)
    made = 0                                                    # blocks there at the ends
    try:
        translate.HOT = 1
        for seed in range(40):
            config.A_FLAG_SIGNED = seed % 5 != 4
            config.SHR_ARITHMETIC = seed % 7 == 6
            words = program()
            rom[:len(words) + 8] = words + [0] * 8
            if seed % 4 == 3:                                   # some code at the top of ROM
                rom[config.BANK_WORDS - 3:] = [0x0302, 0xFFFFFFFF, 0x0400]
            in_ram = seed % 3 == 1          # from RAM 0x5000, where some stores land
            for cpu in (slow, fast, chunked):
                cpu.reset(clear_ram=False)
                cpu.mem.rom = rom
                cpu.bus.keyboard.type("q\b")
                if in_ram:
                    cpu.mem.ram[0x5000:0x5000 + len(words)] = words
                    cpu.iar = RAM | 0x5000
            for _ in range(3000):
                if slow.step() is None:
                    break
            fast.run(3000)
            while chunked.instructions < 3000 and chunked.run(
                    min(rng.randrange(1, 90), 3000 - chunked.instructions)):
                pass
            assert state(fast) == state(slow), f"run() differs from step(), seed {seed}"
            assert state(chunked) == state(slow), f"run() in pieces differs, seed {seed}"
            assert fast._code or in_ram, f"nothing was translated, seed {seed}"
            made += len(fast._code)
        assert made > 100, made
    finally:
        config.A_FLAG_SIGNED, config.SHR_ARITHMETIC, translate.HOT = saved


def test_translated_code_follows_changes():
    # a block is made from memory words: after ROM words change (and a
    # reset) the new words run, forget_code() drops blocks at once, and a
    # program that writes over its own (translated) RAM code runs the new code
    import translate
    saved = translate.HOT
    try:
        translate.HOT = 1
        # DATA R1,5 ; RJMP 4 ; (4:) ADD R1,#1 ; HALT
        cpu = run([0x0301, 5, 0x0400, 1, 0x5010, 1, 0x0F00])
        assert cpu.regs[0] == 6 and cpu._code
        cpu.mem.rom[5] = 10                                     # ADD R1,#10 now
        cpu.reset()
        cpu.run(100)
        assert cpu.regs[0] == 15, cpu.regs[0]
        cpu.reset()
        cpu.run(1)                                              # DATA R1,5 (translated, kept)
        cpu.mem.rom[5] = 20
        cpu.forget_code()
        cpu.run(100)
        assert cpu.regs[0] == 25, cpu.regs[0]
        # in RAM: DATA R4,RAM ; DATA R1,word 9 ; DATA R0,HALT ; ST R1,R0 ;
        # ++ R2 ; CPY R0,R2 ; (9:) JMRB R4 (the ST makes it HALT) ; HALT
        code = [0x0304, RAM, 0x0301, RAM | 9, 0x0300, 0x0F00, 0x0210, 0x1B02, 0x0E02,
                0x0A04, 0x0F00]
        for fast in (False, True):
            cpu = CPU()
            cpu.mem.ram[:len(code)] = code
            cpu.iar, cpu.regs[2] = RAM, 40
            cpu.run(1000) if fast else [cpu.step() for _ in range(1000)]
            assert cpu.halted and cpu.iar == RAM | 10 and cpu.regs[2] == 41, (fast, cpu.regs)
            cpu.mem.ram[5] = 0x0000             # now the ST writes a NOP over that HALT
            cpu.halted, cpu.iar = False, RAM
            cpu.run(1000) if fast else [cpu.step() for _ in range(1000)]
            assert cpu.halted and cpu.iar == RAM | 11 and cpu.regs[2] == 42, (fast, cpu.regs)
        # a store drops only the blocks made from the word it changed: block A
        # (words 0-2: DATA R1,5 ; HALT) and block B (10-12: ADD R1,#1 ; HALT)
        cpu = CPU()
        cpu.mem.ram[:13] = [0x0301, 5, 0x0F00] + [0] * 7 + [0x5010, 1, 0x0F00]
        for start in (0, 10):
            cpu.halted, cpu.iar = False, RAM | start
            cpu.run(100)
        a, b = RAM, RAM | 10
        assert cpu.regs[0] == 6 and a in cpu._code and b in cpu._code
        cpu._code_written(11)                       # a store of the value it had: both stay
        assert a in cpu._code and b in cpu._code
        cpu.mem.ram[11] = 7                         # ADD R1,#7 now
        cpu._code_written(11)
        assert a in cpu._code and b not in cpu._code and not cpu._ram_code[11]
        cpu.halted, cpu.iar = False, RAM
        cpu.run(100)                                # block A, kept: R1 = 5 again
        cpu.halted, cpu.iar = False, RAM | 10
        cpu.run(100)
        assert cpu.regs[0] == 12, cpu.regs[0]       # the new word ran
    finally:
        translate.HOT = saved


# ------------------------------------------------------------ interrupts
RTI, EI, DI, TRAP, WAIT = 0x2000, 0x2100, 0x2200, 0x2300, 0x2400
HALT, NOP = 0x0F00, 0x0000


def GSP(rb): return 0x2500 | rb
def SSP(rb): return 0x2600 | rb
def SLIM(rb): return 0x2900 | rb
def DATA(rb, value): return [0x0300 | rb, value]
def ADDI(ra, value): return [0x5000 | ra << 4, value]          # R0 = Ra + value
def OUT(device, value, scratch=(14, 15)):
    """Send value to an output device: OUTADDR, then OUTDATA."""
    a, b = scratch
    return (DATA(a, device) + [0x0830 | a] + DATA(b, value) + [0x0820 | b])


def build(*items):
    """ROM words: items are words, lists of words, ("at", address), ("L", name),
    ("RJMP", name). The vectors: reset at 0 (RJMP start), 2 NMI, 4 IRQ, 6 TRAP,
    8 FAULT, each an RJMP to the label nmi / irq / trap / fault if there is one,
    else RTI (2 words)."""
    labels, words = {}, []
    flat = []
    for item in items:
        flat.extend([item] if isinstance(item, (int, tuple)) else item)
    for item in flat:
        if isinstance(item, tuple) and item[0] == "L":
            labels[item[1]] = len(words)
        elif isinstance(item, tuple) and item[0] == "RJMP":
            words += [0x0400, item]
        else:
            words.append(item)
    out = []
    for i, w in enumerate(words):
        out.append(((labels[w[1]] - i) & 0xFFFFFFFF) if isinstance(w, tuple) else w)
    # the sixteen words of vectors in front: the program starts at 10
    head = []
    for vector, name in ((0, "start"), (2, "nmi"), (4, "irq"), (6, "trap"), (8, "fault")):
        if name in labels:
            head += [0x0400, (10 + labels[name]) - (vector + 1)]
        else:
            head += [RTI, NOP]
    return head + out


def machine(rom, now=None, interrupted=True):
    from devices import Timer
    cpu = CPU()
    cpu.mem.load_rom(rom)
    if now is not None:
        cpu.bus.timer = Timer(clock=lambda: now[0])
    return cpu


def both(rom, steps, check, now=None):
    """Run the program once with step() and once with run() (translating
    everything), and check both end the same."""
    import translate
    saved = translate.HOT
    translate.HOT = 1
    try:
        a, b = machine(rom, now), machine(rom, now)
        for _ in range(steps):
            if a.step() is None:
                break
        b.run(steps)
        for cpu in (a, b):
            check(cpu)
        assert (a.regs, a.iar, a.esp, a.ie, a.instructions) == \
               (b.regs, b.iar, b.esp, b.ie, b.instructions), "run() differs from step()"
    finally:
        translate.HOT = saved


def test_trap_and_rti():
    # CMP sets the flags, TRAP calls the handler, which changes them and
    # returns: the flags, the interrupt enable bit and the address come back
    # (the program has selected the display; the handler selects another
    # device, and the display is selected again after RTI)
    rom = build(("L", "start"), DATA(1, 5), EI, NOP, [0x1F11], DATA(14, 0x5C), [0x0830 | 14],
                [TRAP], [HALT],
                ("L", "trap"), DATA(2, 7), ADDI(2, 1), [0x0E03], DATA(13, 0xAC), [0x0830 | 13],
                [0x0810 | 13], [RTI])

    def check(cpu):
        assert cpu.regs[1] == 5 and cpu.regs[2] == 7 and cpu.regs[3] == 8, cpu.regs
        assert cpu.flags == 1 and cpu.ie == 1 and cpu.esp == 0 and cpu.halted, cpu.flags
        assert cpu.bus.out_addr == 0x5C and cpu.bus.in_addr == 0, "RTI left the handler's devices"

    both(rom, 100, check)
    cpu = machine(rom)
    while cpu.iar != 6:
        cpu.step()
    devices, word = cpu.mem.ram[0], cpu.mem.ram[1]     # TRAP pushed two words
    assert cpu.esp == 2 and cpu.ie == 0 and devices == 0x5C, (cpu.esp, hex(devices))
    assert word & 0x1FFFFFF == 19 and word >> 27 & 1 and word >> 28 == 1, hex(word)


def test_timer_interrupt_and_acknowledge():
    # the timer period 10 ms, enable source 0, EI; the main loop counts in
    # R3, the handler counts in R4 and acknowledges; the clock is moved by hand
    rom = build(("L", "start"), OUT(0xAD, 1), OUT(0x7C, 10), EI,
                ("L", "loop"), ADDI(3, 1), [0x0E03], ("RJMP", "loop"),
                ("L", "irq"), ADDI(4, 1), [0x0E04], OUT(0xAC, 1), [RTI])
    for fast in (False, True):
        now = [100.0]
        cpu = machine(rom, now)
        cpu.run(60) if fast else [cpu.step() for _ in range(60)]        # the setup
        for tick in range(4):
            now[0] += 0.011
            if fast:
                cpu.run(3000)
            else:
                for _ in range(3000):
                    cpu.step()
        assert cpu.regs[4] == 4 and cpu.regs[3] > 100, (cpu.regs[3], cpu.regs[4])
        assert cpu.bus.interrupts.pending == 0 and cpu.ie == 1


def test_snapshot():
    # snapshot.py: a program with timer interrupts, a key still in the buffer,
    # text, a pixel, the hex display and RAM writes; saved after N steps, the
    # snapshot loaded into a fresh CPU and both run M more steps: the same
    # state (the clock counts instructions, so both see the same ticks)
    import os
    import tempfile
    import snapshot
    from devices import Timer
    rom = build(("L", "start"), OUT(0xAD, 1), OUT(0x7C, 2), EI, OUT(0x5C, ord("h")),
                OUT(0x6C, 0x05060000 | 0xF800), OUT(0x3C, 0xC0FFEE),
                ("L", "loop"), ADDI(3, 1), [0x0E03],
                DATA(5, RAM + 7), [0x0253], ("RJMP", "loop"),       # ST R5, R3
                ("L", "irq"), ADDI(4, 1), [0x0E04], OUT(0xAC, 1), [RTI])

    def fresh():
        cpu = CPU()
        cpu.bus.timer = Timer(clock=lambda: cpu.instructions / 10_000)    # 10 instructions a ms
        cpu.bus.timer.reset()
        return cpu

    a = fresh()
    a.mem.load_rom(rom)
    a.bus.keyboard.type("zz")
    for _ in range(1500):
        a.step()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "s.state")
        snapshot.save(a, path, "made.rom")
        b = fresh()
        rom_path, warnings = snapshot.load(b, path)
        assert rom_path.endswith("made.rom") and warnings == [], warnings
        assert snapshot.digest(a) == snapshot.digest(b)
        assert os.path.getsize(path) < 8000, os.path.getsize(path)     # two 16M-word banks, a few chunks
    for cpu in (a, b):
        for _ in range(3000):
            cpu.step()
    assert a.regs[4] > 20 and a.mem.ram[7] > 20, (a.regs[4], a.mem.ram[7])   # ticks taken, RAM written
    assert snapshot.digest(a) == snapshot.digest(b), "the loaded CPU went another way"
    assert b.bus.display.text == "h" and b.bus.hex_value == 0xC0FFEE and list(b.bus.keyboard.buffer) == [122, 122]


def test_a_request_nobody_acknowledges_does_not_starve_the_program():
    # a key raises source 1; the handler never acknowledges, so the IRQ line
    # stays active: one instruction still runs after every RTI
    rom = build(("L", "start"), OUT(0xAD, 2), EI,
                ("L", "loop"), ADDI(3, 1), [0x0E03], ("RJMP", "loop"),
                ("L", "irq"), ADDI(4, 1), [0x0E04], [RTI])
    for fast in (False, True):
        cpu = machine(rom)
        cpu.bus.keyboard.type("x")
        cpu.run(600) if fast else [cpu.step() for _ in range(600)]
        assert cpu.regs[3] > 30 and cpu.regs[4] > 30, (cpu.regs[3], cpu.regs[4])
        assert cpu.bus.interrupts.pending == 2         # still waiting, nobody asked it to stop


def test_a_masked_interrupt_waits():
    # the same program with DI: the request is pending, nothing is taken; EI takes it
    rom = build(("L", "start"), OUT(0xAD, 2), DI, NOP, NOP, NOP, EI, NOP, NOP, [HALT],
                ("L", "irq"), DATA(5, 99), OUT(0xAC, 2), [RTI])
    cpu = machine(rom)
    cpu.bus.keyboard.type("x")
    cpu.run(60)
    assert cpu.regs[5] == 99 and cpu.halted and cpu.bus.interrupts.pending == 0


def test_nmi_is_not_masked_and_does_not_nest():
    # NMI works with interrupts off; a second NMI waits for the first one's RTI
    # and for one instruction after it
    rom = build(("L", "start"), DI,
                ("L", "loop"), NOP, ("RJMP", "loop"),
                ("L", "nmi"), ADDI(5, 1), [0x0E05], NOP, NOP, [RTI])
    cpu = machine(rom)
    cpu.run(10)
    cpu.nmi()
    cpu.step()                                         # taken
    assert cpu.in_nmi == 1 and cpu.ie == 0 and cpu.iar == 2
    cpu.nmi()                                          # during the handler: it waits
    for _ in range(5):                                 # RJMP, ADD, CPY, NOP, NOP
        cpu.step()
    assert cpu.regs[5] == 1 and cpu.in_nmi == 1
    cpu.step()                                         # RTI
    assert cpu.in_nmi == 0 and cpu.inhibit == 1
    cpu.step()                                         # the one instruction that must run
    assert cpu.regs[5] == 1 and cpu.in_nmi == 0
    cpu.step()                                         # now the second NMI is taken
    assert cpu.in_nmi == 1 and cpu.iar == 2
    cpu.run(10)
    assert cpu.regs[5] == 2 and cpu.in_nmi == 0


def test_nmi_wakes_a_halt():
    # HALT is the shutdown: nothing but NMI (or a reset) wakes it
    rom = build(("L", "start"), EI, [HALT], DATA(1, 1), [HALT],
                ("L", "nmi"), DATA(2, 2), [HALT])
    cpu = machine(rom)
    cpu.run(10)
    assert cpu.halted and cpu.regs[2] == 0
    cpu.bus.keyboard.type("x")                         # a key doesn't
    assert cpu.run(10) == 0 and cpu.halted
    cpu.nmi()
    cpu.run(10)
    assert cpu.regs[2] == 2 and cpu.halted


def test_wait_sleeps_until_an_interrupt():
    rom = build(("L", "start"), OUT(0xAD, 1), OUT(0x7C, 5), EI, WAIT, DATA(6, 1), [HALT],
                ("L", "irq"), DATA(7, 1), OUT(0xAC, 1), [RTI])
    for fast in (False, True):
        now = [10.0]
        cpu = machine(rom, now)
        cpu.run(40) if fast else [cpu.step() for _ in range(40)]
        assert cpu.waiting and cpu.regs[6] == 0 and not cpu.halted
        assert 0 < cpu.idle_seconds() <= 0.005
        assert (cpu.run(10) == 0) if fast else (cpu.step() is None)      # still asleep
        now[0] += 0.006
        cpu.run(40) if fast else [cpu.step() for _ in range(40)]
        assert cpu.regs[7] == 1 and cpu.regs[6] == 1 and cpu.halted and not cpu.waiting


def test_stack_limit_faults_before_the_push():
    # SLIM 3: three PUSHes fit, the fourth is not executed and takes the fault vector
    rom = build(("L", "start"), DATA(1, 3), SLIM(1), DATA(0, 0x11), [0x0B00], [0x0B00],
                [0x0B00], ("L", "again"), [0x0B00], DATA(8, 1), [HALT],
                ("L", "fault"), DATA(9, 1), [HALT])

    # (3 pushes at 0,1,2; the fault pushes its two words at 3 and 4)
    def check(cpu):
        assert cpu.regs[9] == 1 and cpu.regs[8] == 0 and cpu.halted
        assert cpu.mem.ram[:3] == [0x11, 0x11, 0x11] and cpu.esp == 5   # the fault pushed 2 words
        pushed = cpu.mem.ram[4] & 0x1FFFFFF
        assert cpu.mem.rom[pushed] == 0x0B00, hex(pushed)   # the PUSH that did not run

    both(rom, 100, check)


def test_ssp_gsp_move_the_stack_anywhere():
    # the stack at RAM word 0x1234, read back with GSP / GBP, a frame there too
    rom = build(("L", "start"), DATA(1, 0x1234), SSP(1), DATA(0, 0xAB), [0x0B00],
                [0x2500 | 2], [0x0B20], [0x2700 | 3], DATA(4, 0x2000), [0x2800 | 4], [HALT])

    def check(cpu):
        assert cpu.mem.ram[0x1234] == 0xAB and cpu.regs[2] == 0x1235
        assert cpu.regs[3] == 0x1235 and cpu.ebp == 0x2000 and cpu.esp == 0x1236

    both(rom, 100, check)


def test_interrupt_controller_priority():
    from devices import InterruptController
    c = InterruptController()
    c.set_enable(0b110)
    c.raise_(0)
    assert not c.line and c.highest() == 0xFF            # source 0 is not enabled
    c.raise_(2)
    c.raise_(1)
    assert c.line and c.highest() == 1                   # lower number first
    assert c.status() == 0b111 | 1 << 8 | 0b110 << 16
    c.acknowledge(0b010)
    assert c.highest() == 2 and c.pending == 0b101
    c.acknowledge(0xFF)
    assert not c.line


def test_the_stack_lives_anywhere_in_ram():
    # ESP and EBP are 24 bits wide now: they don't wrap at 16K words
    rom = build(("L", "start"), DATA(1, 0x00FFFFFE), SSP(1), DATA(0, 5), [0x0B00],
                [0x0B10], [0x2500 | 2], [HALT])
    cpu = machine(rom)
    cpu.run(30)
    assert cpu.regs[2] == 0x00FFFFFE and cpu.mem.ram[0x00FFFFFE] == 5


def test_run_only_looks_for_interrupts_in_chunks_when_one_can_come():
    # starting _run() costs: with the timer off and no enabled request latched,
    # nothing can arrive during a run(), so it is one chunk (it was half the speed)
    cpu = CPU()
    assert cpu._chunk(1_000_000) == 1_000_000
    cpu.bus.keyboard.type("x")                          # latched, but source 1 is not enabled
    assert cpu._chunk(1_000_000) == 1_000_000
    cpu.bus.interrupts.set_enable(2)                    # now it is a request
    assert cpu._chunk(1_000_000) == config.INTERRUPT_CHUNK
    cpu = CPU()
    cpu.bus.timer.set_period(10)
    assert cpu._chunk(1_000_000) == config.INTERRUPT_CHUNK
    cpu = CPU()
    cpu.nmi()
    assert cpu._chunk(1_000_000) == config.INTERRUPT_CHUNK


def test_run_stops_at_breakpoints():
    # DATA R1,1 ; ADD R1,#1 ; RJMP back to the ADD
    cpu = run([0x0301, 1, 0x5010, 1, 0x0400, 0xFFFFFFFD], steps=0)
    assert cpu.run(100, stop_at={2}) == 1 and cpu.iar == 2     # stops before the ADD
    assert cpu.run(100, stop_at={2}) == 2 and cpu.iar == 2     # leaves it, comes back
    assert cpu.regs[0] == 2 and cpu.instructions == 3


# ---------------------------------------------------------------- the Claude device (0x9C)
# All with claude.FakeBackend: no network, no key, no cost.

import os as _os
import sys as _sys
import tempfile as _tempfile
import time as _time
from pathlib import Path as _Path

import claude


def _device(script=(), tmp=None, **kwargs):
    tmp = _Path(tmp or _tempfile.mkdtemp())
    access = claude.Access(tmp / "claude", tmp / "access.conf")
    dev = claude.ClaudeDevice(screenshot=kwargs.pop("screenshot", None),
                              backend=claude.FakeBackend(script), access=access,
                              system_file=tmp / "no_prompt.md")
    return dev


def _send(dev, text, end=0):
    for c in text:
        dev.write(ord(c))
    if end is not None:
        dev.write(end)


def _turn(dev, answer_tool=None, limit=5.0):
    """What the CPU reads up to EOT, as text; a tool frame is answered with
    answer_tool(letter, fields) and shown as {letter|field|field}."""
    got, start = [], _time.time()
    while _time.time() - start < limit:
        c = dev.read()
        if c == 0:
            _time.sleep(0.001)
            continue
        if c == claude.EOT:
            return "".join(got)
        if c == claude.STX:
            frame = []
            while (c := dev.read()) != claude.ETX:
                if c:
                    frame.append(chr(c))
            letter, fields = frame[0], "".join(frame[1:]).split(chr(claude.US))
            got.append("{" + letter + "|" + "|".join(fields) + "}")
            _send(dev, answer_tool(letter, fields) if answer_tool else "ok")
            continue
        got.append(chr(c))
    raise AssertionError("no EOT: " + "".join(got))


def _roles(dev):
    return [m["role"] for m in dev.history]


def test_claude_streams_ascii_and_ends_the_turn():
    dev = _device([claude.text_reply("Héllo “world” — ", "ok… \U0001F600\tend")])
    _send(dev, "hi")
    assert _turn(dev) == 'Hello "world" -- ok... ?    end'
    assert _roles(dev) == ["user", "assistant"] and dev.history[0]["content"] == "hi"
    req = dev.backend.requests[0]
    assert req["model"] == "claude-haiku-5-5" and req["max_tokens"] == 100_000
    assert req["output_config"] == {"effort": "low"} and req["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in req and "tool_choice" not in req and "temperature" not in req
    assert [t["name"] for t in req["tools"]] == ["run_command", "write_file", "read_host_file",
                                                 "list_host_dir", "write_host_file", "screenshot"]
    assert all(t["eager_input_streaming"] for t in req["tools"])
    assert "plain ASCII" in req["system"][0]["text"]       # the fallback prompt: no file here
    assert dev.read() == 0 and dev.state == "idle"


def test_claude_errors_end_the_turn():
    dev = _device([RuntimeError("overloaded")])
    _send(dev, "hi")
    assert _turn(dev) == "\n[claude: overloaded]\n"
    saved = _sys.modules.get("anthropic")
    _sys.modules["anthropic"] = None                      # import anthropic fails: no SDK
    try:
        dev.backend = None                                # the real backend, made on use
        _send(dev, "again")
        assert "the anthropic package is not installed" in _turn(dev)
    finally:
        if saved is None:
            del _sys.modules["anthropic"]
        else:
            _sys.modules["anthropic"] = saved
    dev.backend = claude.FakeBackend([([], [], "refusal"), claude.text_reply("fine")])
    _send(dev, "x")
    assert _turn(dev) == "\n[claude declined to answer]\n"
    _send(dev, "y")
    assert _turn(dev) == "fine"
    roles = _roles(dev)                  # a valid history: the users stay, every turn answered
    assert roles[-4:] == ["user", "assistant", "user", "assistant"], roles


def test_claude_slash_commands_stay_in_the_simulator():
    dev = _device()

    def cmd(line):
        _send(dev, line)
        return _turn(dev)

    assert "/model" in cmd("/help") and "/approve" in cmd("/help")
    assert cmd("/model opus") .startswith("model claude-opus-5-5")
    assert dev.settings["model"] == "claude-opus-5-5"
    assert cmd("/model gpt") .startswith("unknown model gpt")
    assert cmd("/model claude-haiku-5-5").startswith("model claude-haiku-5-5")
    assert cmd("/effort high") == "effort high\n" and cmd("/effort huge").startswith("effort: one of")
    assert cmd("/max 2048") == "max_tokens 2048\n" and cmd("/max 0").startswith("max: a number")
    assert cmd("/max 999999").startswith("max: a number") and dev.settings["max_tokens"] == 2048
    assert cmd("/tools off") == "tools off\n" and cmd("/approve on") == "approve on\n"
    assert cmd("/timeout 5") == "timeout 5 s\n" and cmd("/timeout x").startswith("timeout: seconds")
    assert cmd("/usage").startswith("0 requests") and cmd("/reload").startswith("read no_prompt.md")
    assert "write" in cmd("/access") and cmd("/nope").startswith("unknown command /nope")
    assert dev.backend.requests == [] and dev.history == []   # none of it reached Claude
    dev.backend.script = [claude.text_reply("a"), claude.text_reply("b")]
    _send(dev, "q")
    _turn(dev)
    req = dev.backend.requests[0]
    assert req["tool_choice"] == {"type": "none"} and req["max_tokens"] == 2048
    assert req["output_config"] == {"effort": "high"} and len(req["tools"]) == 6
    assert cmd("/clear") == "new conversation\n" and dev.history == []
    dev.write(claude.CAN)                                   # the CPU's /new: the same
    assert dev.history == [] and dev.read() == 0


def test_claude_runs_tools_on_the_cpu():
    tool = claude.tool_reply
    dev = _device([
        tool("run_command", {"command": "ls /bin"}, "Looking."),
        lambda req: claude.text_reply("seen: " + req["messages"][-1]["content"][0]["content"]),
        tool("write_file", {"path": "/a.txt", "content": "xé\ty"}, tool_id="t2"),
        claude.text_reply("written"),
        tool("run_command", {"command": "a\nb"}, tool_id="t3"),
        tool("run_command", {"cmd": "ls"}, tool_id="t4"),
        claude.text_reply("gave up"),
    ])
    _send(dev, "go")
    assert _turn(dev, lambda letter, f: "exit status 0\nsh echo") == \
        "Looking.{r|30|ls /bin|}seen: exit status 0\nsh echo"
    _send(dev, "write")
    assert _turn(dev, lambda letter, f: "wrote 4 chars") == "{w|/a.txt|xe\ty}written"
    _send(dev, "bad")                                       # bad inputs never reach the CPU
    assert _turn(dev) == "gave up"
    results = [m["content"][0] for m in dev.history if m["role"] == "user"
               and isinstance(m["content"], list)]
    assert [r.get("is_error", False) for r in results] == [False, False, True, True]
    assert "one non-empty line" in results[2]["content"] and "INVALID_INPUT" in results[3]["content"]
    assert "missing command" in results[3]["content"]
    dev.settings.update(approve=True, timeout=7)            # /approve on: the letter asks first
    dev.backend.script = [tool("run_command", {"command": "pwd", "input": "a\nb"}),
                          claude.text_reply("ok")]
    _send(dev, "again")
    assert _turn(dev, lambda letter, f: "the user said no") == "{R|7|pwd|a\nb}ok"


def test_claude_stop_new_conversation_and_hello():
    dev = _device([claude.text_reply("first ", "second")])
    dev.backend.gate = gate = __import__("threading").Event()
    _send(dev, "talk")
    start = _time.time()
    while dev.read() == 0 and _time.time() - start < 5:     # "first " has come
        _time.sleep(0.001)
    dev.write(claude.ETX)                                   # Ctrl-X: stop it
    gate.set()
    rest = _turn(dev)
    assert rest.endswith("\n[stopped]\n") and "second" not in rest, rest
    assert dev.history[-1]["content"][0]["text"] == "first  [stopped by the user]"
    # a program killed while its tool ran: the next one says hello (SYN)
    dev.backend = claude.FakeBackend([claude.tool_reply("run_command", {"command": "spin"}),
                                      claude.text_reply("after")])
    _send(dev, "run it")
    start = _time.time()
    while dev.state != "tool" and _time.time() - start < 5:
        _time.sleep(0.001)
    assert dev.waiting_tool
    dev.write(claude.SYN)
    assert dev.read() == 0 and not dev.waiting_tool
    last = dev.history[-1]["content"][0]
    assert last["type"] == "tool_result" and last["is_error"] and "stopped" in last["content"]
    _send(dev, "and now")
    assert _turn(dev) == "after"
    assert _roles(dev)[-4:] == ["assistant", "user", "user", "assistant"], _roles(dev)
    dev.write(claude.CAN)
    assert dev.history == []


def test_claude_reads_only_the_permitted_pc_files():
    tmp = _Path(_tempfile.mkdtemp())
    (tmp / "docs").mkdir()
    (tmp / "docs" / "spec.md").write_text("the spec")
    (tmp / "secret.txt").write_text("no")
    (tmp / "out").mkdir()
    (tmp / "bin.dat").write_bytes(b"\0\1\2")
    dev = _device(tmp=tmp)
    access = dev.access
    conf = tmp / "access.conf"
    deny = claude.AccessError

    def refused(call, *args):
        try:
            call(*args)
        except deny as e:
            return str(e)
        raise AssertionError(f"allowed: {args}")

    assert "not allowed" in refused(claude.read_host_file, access, str(tmp / "docs" / "spec.md"))
    conf.write_text(f"# a comment\nread {tmp}/docs/\nwrite {tmp}/out/  # trailing\nread bin.dat\n")
    assert claude.read_host_file(access, str(tmp / "docs" / "spec.md")) == "the spec"
    assert "not allowed" in refused(claude.read_host_file, access, str(tmp / "secret.txt"))
    assert "'..'" in refused(claude.read_host_file, access, str(tmp / "docs" / ".." / "secret.txt"))
    assert "binary" in refused(claude.read_host_file, access, str(tmp / "bin.dat"))
    assert claude.write_host_file(access, "notes/n.txt", "mine").startswith("wrote 4 chars")
    assert (tmp / "claude" / "notes" / "n.txt").read_text() == "mine"   # relative: Claude's folder
    assert claude.read_host_file(access, "notes/n.txt") == "mine"
    assert "not allowed (write)" in refused(claude.write_host_file, access,
                                            str(tmp / "docs" / "x.txt"), "x")
    assert claude.write_host_file(access, str(tmp / "out" / "r.txt"), "r").startswith("wrote")
    if hasattr(_os, "symlink"):                                 # a link out of the folder
        _os.symlink(tmp / "secret.txt", tmp / "claude" / "link.txt")
        assert "not allowed" in refused(claude.read_host_file, access, "link.txt")
    listing = claude.list_host_dir(access, "")
    assert f"read  {tmp}/docs" in listing and f"write {tmp}/out" in listing, listing
    assert claude.list_host_dir(access, str(tmp / "docs")) == "spec.md  8"
    conf.write_text("")                                         # edited while it runs
    assert "not allowed" in refused(claude.read_host_file, access, str(tmp / "docs" / "spec.md"))
    # through the device: the CPU only gets a line, the result goes to Claude
    dev.backend.script = [claude.tool_reply("read_host_file", {"path": str(tmp / "secret.txt")}),
                          lambda req: claude.text_reply(str(req["messages"][-1]["content"][0].get("is_error")))]
    _send(dev, "read it")
    assert _turn(dev).endswith("[refused: " + str(tmp / "secret.txt") +
                               ": not allowed (read); the permitted paths are in "
                               "tynix/claude_access.conf]\nTrue")


def test_claude_screenshot_and_costs():
    shots = []
    dev = _device([claude.tool_reply("screenshot", {}), claude.text_reply("a red square")],
                  screenshot=lambda: shots.append(1) or b"\x89PNG fake")
    _send(dev, "look")
    assert _turn(dev) == "\n[claude looks at the RGB screen]\na red square"
    image = dev.history[-2]["content"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert image["source"]["data"] == "iVBORyBmYWtl" and shots == [1]
    dev.reset_usage()
    small = {"input_tokens": 50_000, "output_tokens": 50_000}  # $0.10 / $0.50 per M
    assert abs(dev.price(small) - 0.03) < 1e-9 and abs(dev.price({"input_tokens": 10_000,
               "cache_read_input_tokens": 50_000, "output_tokens": 2000}) - 0.0025) < 1e-9
    big = {"input_tokens": 200_000, "output_tokens": 1000}      # past 100K: 0.50 / 2.50
    assert abs(dev.price(big) - 0.1025) < 1e-9
    dev.settings["model"] = "claude-opus-5-5"
    assert abs(dev.price(big) - 0.82) < 1e-9
    dev.settings["model"] = "claude-haiku-5-5"
    dev.backend.usage = dict(big, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    dev.backend.script = [claude.text_reply("x"), claude.text_reply("y")]
    _send(dev, "a")
    assert "is 200000 tokens long" in _turn(dev)
    _send(dev, "b")
    assert _turn(dev) == "y"                                    # the warning comes once
    assert dev.usage["requests"] == 2 and abs(dev.usage["dollars"] - 0.205) < 1e-9
    try:
        dev.configure("gpt-9")
    except ValueError as e:
        assert "unknown Claude model" in str(e)
    else:
        raise AssertionError("gpt-9 accepted")
    dev.configure("sonnet")
    assert dev.settings["model"] == "claude-sonnet-5-5"


def test_claude_device_on_the_bus():
    """OUTDATA/INDATA at 0x9C reach the device; a reset keeps the conversation."""
    cpu = CPU()
    cpu.bus.claude.backend = claude.FakeBackend([claude.text_reply("ok")])
    cpu.bus.out_address(config.CLAUDE_ADDR)
    cpu.bus.in_address(config.CLAUDE_ADDR)
    for c in "hi":
        cpu.bus.out_data(ord(c))
    cpu.bus.out_data(0)
    got, start = [], _time.time()
    while claude.EOT not in got and _time.time() - start < 5:
        c = cpu.bus.in_data()
        if c:
            got.append(c)
    assert got == [ord("o"), ord("k"), claude.EOT]
    assert cpu.bus.in_data() == 0
    cpu.reset()
    assert len(cpu.bus.claude.history) == 2


FACT_C = """
#include <stdio.h>
#include <stdlib.h>
int depth_probe;
int fact(int n) { if (n <= 1) { depth_probe = n; return 1; } return n * fact(n - 1); }
int main(void) {
    int *a = malloc(10), *b = malloc(20), *c = malloc(5);
    free(b);
    printf("%d %d\\n", fact(5), a != 0 && c != 0);
    return 0;
}
"""


def test_machine_view():
    """machine_view.py: stopped in fact(1) called from fact(5), the chain is
    fact x5, main, start with the arguments 1..5; the heap holds the blocks
    malloc(10), malloc(20) freed, malloc(5), then the free rest; the regions
    tile RAM from the data to its end; no map, no answers."""
    import sys
    import tempfile
    from pathlib import Path
    from debuginfo import DebugInfo
    import machine_view as mv
    cc = str(Path(__file__).resolve().parents[2] / "compiler" / "src" / "cc")
    sys.path.insert(0, cc)
    try:
        import driver
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fact.c").write_text(FACT_C)
            program, _ = driver.build([str(Path(tmp) / "fact.c")])
            (Path(tmp) / "fact.map").write_text(driver.format_map(program, "fact.rom"))
            info = DebugInfo.load(Path(tmp) / "fact.map")
    finally:
        sys.path.remove(cc)
    cpu = CPU()
    cpu.mem.load_rom(program.rom)
    assert mv.frames(cpu, None) == [] and mv.heap(cpu, None) == ([], None) and mv.regions(cpu, None) == []
    assert mv.heap(cpu, info) == ([], None)                       # before the first malloc
    probe = info.symbols["depth_probe"]
    for _ in range(100000):
        cpu.run(1)
        if cpu.mem.read(probe) == 1:                               # fact(1) just stored its mark
            break
    chain = mv.frames(cpu, info)
    assert [f[0] for f in chain] == ["fact"] * 5 + ["main", "start"], chain
    assert [f[4][0] for f in chain[:5]] == [1, 2, 3, 4, 5]
    assert chain[0][2][1] == 5 and chain[5][2][1] == 9, (chain[0][2], chain[5][2])
    blocks, damaged = mv.heap(cpu, info)
    assert damaged is None and [(b[1], b[2]) for b in blocks[:3]] == [(11, True), (21, False), (6, True)], blocks
    assert blocks[3][2] is False and blocks[3][0] + blocks[3][1] == cpu.mem.read(info.symbols["_heap_end"])
    cpu.mem.write(blocks[1][0], 0)                                 # a damaged header
    assert mv.heap(cpu, info)[1] == blocks[1][0]
    cpu.regs[3], cpu.esp = 0x40, 0x200
    for text, want in (("0x10", 16), ("1000a", 0x1000A), ("R3", 0x40), ("r3+2", 0x42), ("ESP-4", 0x1FC),
                       ("fact", info.symbols["fact"]), ("fact + 0x10 - 1", info.symbols["fact"] + 15)):
        assert mv.resolve_address(text, cpu, info) == want, text
    for bad in ("", "nosuch", "+3", "R3+", "fact+zz"):
        try:
            mv.resolve_address(bad, cpu, info)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} accepted")
    parts = mv.regions(cpu, info)
    assert [p[0] for p in parts] == ["data", "stack", "heap", "free"][:len(parts)] and parts[0][1] == config.RAM_BIT
    assert all(a[2] == b[1] for a, b in zip(parts, parts[1:])) and parts[-1][2] == config.RAM_BIT + config.BANK_WORDS


def test_window_view_panes():
    """gui.py's Stack, Heap and Map tabs draw the machine_view answers in a
    real window (skipped without tkinter or a display)."""
    try:
        import tkinter
        import gui
    except ImportError:
        return
    import tempfile
    import machine_view
    from pathlib import Path
    import sys
    cc = str(Path(__file__).resolve().parents[2] / "compiler" / "src" / "cc")
    sys.path.insert(0, cc)
    try:
        import driver
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "fact.c").write_text(FACT_C)
            program, _ = driver.build([str(Path(tmp) / "fact.c")])
            rom = Path(tmp) / "fact.rom"
            rom.write_text(driver.linker.format_raw(program.rom))
            (Path(tmp) / "fact.map").write_text(driver.format_map(program, "fact.rom"))
            cpu = CPU()
            cpu.mem.load_rom(program.rom)
            try:
                window = gui.SimulatorWindow(cpu, str(rom))
            except tkinter.TclError:                    # no display
                return
    finally:
        sys.path.remove(cc)
    try:
        probe = window.info.symbols["depth_probe"]
        for _ in range(100000):
            cpu.run(1)
            if cpu.mem.read(probe) == 1:
                break
        window.update()
        for pane in window.view_panes:
            pane.render()
        stack, heap_pane, map_pane = window.view_panes
        assert stack.text.get("1.0", "end").count(" fact ") == 5 and "main" in stack.text.get("1.0", "end")
        assert "4 blocks" in heap_pane.label.cget("text") and "ESP index" in map_pane.label.cget("text")
        stack.pick(type("E", (), {"x": 5, "y": 5})())      # a click on the first frame
        click = type("E", (), {"x": 6 * window.screen_zoom, "y": 9 * window.screen_zoom})()
        window._mouse_button(click, 0, True)                # a left press on the screen picture
        assert cpu.bus.mouse.state() == (6 << 24 | 9 << 16 | 1 | 8) and cpu.bus.mouse.events
        window._mouse_button(click, 0, False)
        ram = window.ram_pane
        ram.show_float.set(True)
        ram.show_text.set(True)
        ram.goto.insert(0, "depth_probe")
        ram.jump_to()
        text = ram.text.get("1.0", "end")
        assert "<depth_probe>" in text and "<handlers>" in text and "0x1000000  00000001" in text, text[:300]
        ram.render()
        cpu.mem.write(window.info.symbols["depth_probe"], 7)
        ram.render()
        assert ram.text.tag_ranges("changed"), "a changed word is not marked"
        ram.render()
        assert not ram.text.tag_ranges("changed")           # marked for one redraw
        window.refresh()
    finally:
        window.destroy()


def test_mouse_device():
    """The mouse (0xBC state, 0xBD events): the state word's layout, a button
    event raises IRQ_MOUSE and queues, motion does not, the queue keeps 64,
    --mouse scripts parse, and paint.c under a script draws, erases and quits."""
    import sys
    from pathlib import Path
    import main as main_module
    cpu = CPU()
    bus, mouse = cpu.bus, cpu.bus.mouse
    bus.in_address(config.MOUSE_STATE_ADDR)
    assert bus.in_data() == 0
    mouse.move(300, -4)                                       # clamped to the screen
    assert (mouse.x, mouse.y) == (config.VIDEO_WIDTH - 1, 0) and bus.interrupts.pending == 0
    mouse.move(0x12, 0x34)
    mouse.button(0, True)
    mouse.button(0, True)                                     # no change: no second event
    mouse.button(1, True)
    mouse.wheel(False)
    assert bus.in_data() == 0x12340000 | 3 | 8 and bus.interrupts.pending == 1 << config.IRQ_MOUSE
    bus.in_address(config.MOUSE_EVENT_ADDR)
    got = [bus.in_data() for _ in range(5)]
    assert got == [0x12340101, 0x12340103, 0x12340403, 0, 0], [hex(g) for g in got]
    mouse.button(0, False)
    mouse.button(1, False)
    assert [bus.in_data() >> 8 & 0xFF for _ in range(3)] == [config.MOUSE_RELEASE] * 2 + [0]
    for i in range(100):
        mouse.wheel(True)
    assert len(mouse.events) == config.MOUSE_QUEUE
    cpu.reset()
    assert mouse.events == type(mouse.events)() and mouse.state() == 0
    assert main_module.parse_mouse("5,6,1@20; 1,2,0@10") == [(10, 1, 2, 0), (20, 5, 6, 1)]
    try:
        main_module.parse_mouse("1,2")
    except ValueError:
        pass
    else:
        raise AssertionError("a bad --mouse script was accepted")
    cc = str(Path(__file__).resolve().parents[2] / "compiler" / "src" / "cc")
    sys.path.insert(0, cc)
    try:
        import driver
        program, _ = driver.build([str(Path(__file__).resolve().parents[2] / "compiler" / "examples" / "c" / "graphics" / "paint.c")])
    finally:
        sys.path.remove(cc)
    cpu = CPU()
    cpu.mem.load_rom(program.rom)
    script = ("40,5,0@300000;40,5,1@400000;40,5,0@450000;10,50,1@500000;60,50,1@600000;60,90,1@700000;"
              "60,90,0@750000;100,100,2@800000;120,100,2@850000;0,0,4@900000")
    for step, x, y, buttons in main_module.parse_mouse(script):
        cpu.run(step - cpu.instructions)
        main_module.apply_mouse(cpu.bus.mouse, x, y, buttons)
    cpu.run(2_000_000)
    pixels = cpu.bus.video.pixels
    assert cpu.halted and cpu.bus.display.text == "painted 5\n", cpu.bus.display.text
    red = 0xF800
    assert [pixels[y * 256 + x] for x, y in ((40, 5), (10, 50), (35, 50), (60, 70), (60, 90))] == [red] * 5
    assert pixels[100 * 256 + 110] == 0                      # erased with black


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"\n{len(tests)} checks passed")


if __name__ == "__main__":
    main()