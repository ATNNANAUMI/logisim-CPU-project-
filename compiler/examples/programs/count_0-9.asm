; count_0-9.asm - print the digits 0 to 9
;
; python compiler/src/asm build compiler/src/asm/examples/programs/count_0-9.asm
; Expected display: 0123456789

        .equ DISPLAY, 0x5C
        .global start

start:  DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R1, 0              ; R1 = the number
loop:   ADD R1, #'0'            ; R0 = its digit, as ASCII
        COMM OUTDATA, R0
        ++ R1
        CPY R0, R1
        CMP R1, #10
        RJNF Z, loop            ; stop after 9
        DATA R0, '\n'
        COMM OUTDATA, R0
        HALT
