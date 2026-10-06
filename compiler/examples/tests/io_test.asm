; io_test.asm - the smallest possible keyboard test
;
; The input demo does nothing because the keyboard side of COMM is not
; responding. This strips it down to the fewest instructions that can
; still show something, so the circuit can be probed while it runs.
;
;   python compiler/src/asm build compiler/examples/tests/io_test.asm
;
; No stdlib, no calls, no stack. Just the display, the keyboard and a
; loop.
;
; What it does, in order:
;   1. selects the display and prints  >
;      If you do not even see that, the fault is on the OUTPUT side and
;      has nothing to do with the keyboard.
;   2. selects the keyboard with COMM INADDR
;   3. reads with COMM INDATA over and over. Every read that comes back
;      non-zero is echoed to the display, and every 65536th read prints a
;      dot so you can see the loop is alive.
;
; Reading it:
;   nothing at all, not even >   output side, or the CPU is not running
;   > and nothing else          the loop is stuck before its first read
;   > then dots, no characters  the loop runs and INDATA always returns 0:
;                               the keyboard is not being selected, or its
;                               read strobe never fires, or the buffer
;                               never fills
;   > dots and your keys        it works, and the problem is higher up in
;                               read_line / read_char
;
; Places to probe while the dots are printing:
;   - the device-select register: does it hold 0x0F after the INADDR?
;   - the input strobe: does it pulse once per INDATA?
;   - the keyboard buffer: does a keypress put anything in it at all?
;
; R1 display, R2 keyboard, R3 the key read, R4 the dot counter.

        .equ DISPLAY, 0x5C
        .equ KEYBOARD, 0xF0
        .equ DOT_MASK, 0xFFFF       ; one dot per 65536 reads - lower it
                                    ; (0xFFF, 0xFF) if the CPU is running
                                    ; slowly and you want dots sooner

        .global start

        .rom
start:
        DATA R1, DISPLAY
        COMM OUTADDR, R1            ; display on
        DATA R1, '>'
        COMM OUTDATA, R1            ; proof the output side works

        DATA R2, KEYBOARD
        COMM INADDR, R2             ; keyboard on

        DATA R4, 0
io_loop:
        COMM INDATA, R3             ; read one word from the keyboard
        TEST R3
        RJF Z, io_tick              ; nothing there
        DATA R1, DISPLAY
        COMM OUTADDR, R1
        COMM OUTDATA, R3            ; echo whatever came back
io_tick:
        ++ R4
        CPY R0, R4
        AND R4, #DOT_MASK
        RJNF Z, io_loop             ; only every 65536th time round
        DATA R1, DISPLAY
        COMM OUTADDR, R1
        DATA R1, '.'
        COMM OUTDATA, R1            ; a dot, to show the loop is alive
        RJMP io_loop
