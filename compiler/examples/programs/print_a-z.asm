; print_a-z.asm - print the alphabet (replaces print_a-z and print_a-z_fixed)
;
; python compiler/src/asm build compiler/examples/programs/print_a-z.asm
; Expected display: abcdefghijklmnopqrstuvwxyz

        .equ DISPLAY, 0x5C
        .global start

start:  DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R1, 'a'
loop:   COMM OUTDATA, R1
        ++ R1                   ; R0 = R1 + 1 ...
        CPY R0, R1              ; ... so move it back into R1
        CMP R1, #'z' + 1
        RJNF Z, loop            ; keep going until R1 passes 'z'
        HALT
