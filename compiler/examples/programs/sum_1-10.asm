; sum_1-10.asm - add 1 + 2 + ... + 10 and print the total
;
; python compiler/src/asm build compiler/examples/programs/sum_1-10.asm
; Expected display: 55

        .equ DISPLAY, 0x5C
        .global start

start:  DATA R1, 0              ; R1 = total
        DATA R2, 1              ; R2 = next number
loop:   ADD R1, R2
        CPY R0, R1              ; total += number
        ++ R2
        CPY R0, R2
        CMP R2, #11
        RJNF Z, loop            ; up to and including 10

        DATA R3, DISPLAY        ; print the two digits of R1
        COMM OUTADDR, R3
        DIV R1, #10             ; tens
        ADD R0, #'0'
        COMM OUTDATA, R0
        MOD R1, #10             ; units
        ADD R0, #'0'
        COMM OUTDATA, R0
        HALT
