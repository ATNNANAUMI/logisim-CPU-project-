; abs_value.asm - print the absolute value of -5
;
; python compiler/src/asm build compiler/src/asm/examples/programs/abs_value.asm
; Expected display: 5

        .equ DISPLAY, 0x5C
        .global start

start:  DATA R1, -5
        TEST R1                 ; R0 = R1, sets N and Z from it
        RJNF N, positive        ; N off (>= 0): skip the negation
        NEG R1                  ; R0 = -R1
        CPY R0, R1              ; results live in R0, move it back
positive:
        ADD R1, #'0'            ; one digit, as ASCII
        CPY R0, R1
        DATA R2, DISPLAY
        COMM OUTADDR, R2
        COMM OUTDATA, R1
        HALT
