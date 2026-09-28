; diag3.asm - the same RA check as diag2, but with negative numbers
;
; diag2 passed, and every value in it was positive. int_to_str works
; entirely with negative numbers, so these repeat the check on the
; negative path.
;
; Stands alone, no stdlib needed:
;   python compiler/src/asm build diag3.asm -o diag3.rom
;
;   a  MOD  R1, #10   R1 = -12    R1 unchanged   operand -, result -
;   b  DIV  R1, #10   R1 = -12    R1 unchanged   operand -, result -
;   c  MOD  R1, R2    R1 = -12    R1 unchanged   register form
;   d  MOD  R1, #10   R1 = -10    R1 unchanged   operand -, result 0
;   e  DIV  R1, #100  R1 = -12    R1 unchanged   operand -, result 0
;   f  SUB  R1, #20   R1 =  12    R1 unchanged   operand +, result -
;   g  ADD  R1, #-20  R1 =  12    R1 unchanged   operand +, result -
;   h  MULT R1, #-1   R1 =  12    R1 unchanged   operand +, result -
;   i  NEG  R1        R1 =  12    R1 unchanged   result -
;   j  -12 MOD 10 then -12 DIV 10 = -1   the digit loop, negative
;   k  -1234 MOD 10 then -1234 DIV 10 = -123
;
; Reading the failures:
;   a b c d e fail, f g h pass  -> a NEGATIVE OPERAND triggers it
;   a b c f g h i fail, d e pass -> a NEGATIVE RESULT triggers it
;   a c d fail only              -> only MOD
;   a b c d e fail only          -> DIV and MOD
;   j or k fail                  -> that is the digit loop failing

        .global start

start:
        DATA R3, 0x5C
        COMM OUTADDR, R3

        DATA R4, 'a'                ; MOD, negative operand and result
        COMM OUTDATA, R4
        DATA R1, -12
        MOD R1, #10
        DATA R2, -12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'b'                ; DIV, negative operand and result
        COMM OUTDATA, R4
        DATA R1, -12
        DIV R1, #10
        DATA R2, -12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'c'                ; MOD, register form
        COMM OUTDATA, R4
        DATA R1, -12
        DATA R2, 10
        MOD R1, R2
        DATA R2, -12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'd'                ; MOD, negative operand, result 0
        COMM OUTDATA, R4
        DATA R1, -10
        MOD R1, #10
        DATA R2, -10
        CMP R1, R2
        CALL expect_z

        DATA R4, 'e'                ; DIV, negative operand, result 0
        COMM OUTDATA, R4
        DATA R1, -12
        DIV R1, #100
        DATA R2, -12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'f'                ; SUB, positive operand, negative result
        COMM OUTDATA, R4
        DATA R1, 12
        SUB R1, #20
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'g'                ; ADD, positive operand, negative result
        COMM OUTDATA, R4
        DATA R1, 12
        ADD R1, #-20
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'h'                ; MULT, positive operand, negative result
        COMM OUTDATA, R4
        DATA R1, 12
        MULT R1, #-1
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'i'                ; NEG, negative result
        COMM OUTDATA, R4
        DATA R1, 12
        NEG R1
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'j'                ; the digit loop: -12 % 10 then -12 / 10
        COMM OUTDATA, R4
        DATA R1, -12
        MOD R1, #10                 ; R0 = -2, R1 must stay -12
        DIV R1, #10                 ; R0 = -1 if R1 is still -12
        CPY R0, R5
        DATA R2, -1
        CMP R5, R2
        CALL expect_z

        DATA R4, 'k'                ; the same with -1234
        COMM OUTDATA, R4
        DATA R1, -1234
        MOD R1, #10                 ; R0 = -4
        DIV R1, #10                 ; R0 = -123 if R1 is still -1234
        CPY R0, R5
        DATA R2, -123
        CMP R5, R2
        CALL expect_z

        DATA R4, '\n'
        COMM OUTDATA, R4
        HALT

; CALL leaves the flags alone, so these see the test's flags.
expect_z:
        RJF Z, pass
        DATA R4, 'F'
        COMM OUTDATA, R4
        RJMP gap
pass:
        DATA R4, 'P'
        COMM OUTDATA, R4
gap:
        DATA R4, ' '
        COMM OUTDATA, R4
        RET
