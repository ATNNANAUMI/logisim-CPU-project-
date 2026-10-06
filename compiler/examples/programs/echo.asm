; echo.asm - show every key typed, until Enter
;
; python compiler/src/asm build compiler/examples/programs/echo.asm
; Type something and press Enter; the display shows what you typed.
; Backspace is echoed too, so the display deletes the last character.
;
; INADDR selects the keyboard and OUTADDR the display; the two selections
; are independent, so both are made once, before the loop.

        .equ DISPLAY, 0x5C
        .equ KEYBOARD, 0xF0
        .global start

start:  DATA R1, KEYBOARD
        COMM INADDR, R1
        DATA R1, DISPLAY
        COMM OUTADDR, R1
wait:   COMM INDATA, R2         ; 0 = nothing typed yet
        TEST R2
        RJF Z, wait
        COMM OUTDATA, R2        ; echo it
        CMP R2, #'\n'
        RJNF Z, wait            ; Enter ends it
        HALT
