; diag5.asm - CMP's flags, and the float conversions
;
; One test per line, so a stray character on the display can't make the
; result ambiguous.
;
; Stands alone, no stdlib needed:
;   python compiler/src/asm build diag5.asm -o diag5.rom
;
; Value checks here use SUB and its Z flag, never CMP, because CMP is
; what is under suspicion.
;
;   CMP's flags
;     a  CMP 3, 2     Z off
;     b  CMP 3, 3     Z on
;     c  CMP 1, 4     Z off    <- int_to_str's reversal depends on this
;     d  CMP 0, 5     Z off    <- mem_set / mem_copy depend on this
;     e  CMP 3, #4    Z off    (immediate form)
;     f  CMP 3, 2     A on
;     g  CMP 1, 4     A off
;     h  CMP 1, 4     N on
;   MULT
;     i  MULT -1, #1  Z off    (immediate)
;     j  MULT -1, 1   Z off    (register)
;   SUB / ADD immediate, N flag
;     k  SUB 3, #4    N on
;     l  ADD -2, #1   N on
;   float conversions, used by print_float
;     m  FLOAT 7      = 7.0
;     n  INT 5.0      = 5
;     o  INT 1.5      = 1 or 2 (either is fine, it prints the digit)
;     p  FSUB 3.0 - 3.0   Z on
;
; Expected on a correct CPU: a-n and p all P, and o prints 1 or 2.

        .global start

start:
        DATA R3, 0x5C
        COMM OUTADDR, R3

        DATA R4, 'a'                ; CMP 3, 2 -> Z off
        COMM OUTDATA, R4
        DATA R1, 3
        DATA R2, 2
        CMP R1, R2
        CALL expect_not_z

        DATA R4, 'b'                ; CMP 3, 3 -> Z on
        COMM OUTDATA, R4
        DATA R1, 3
        DATA R2, 3
        CMP R1, R2
        CALL expect_z

        DATA R4, 'c'                ; CMP 1, 4 -> Z off
        COMM OUTDATA, R4
        DATA R1, 1
        DATA R2, 4
        CMP R1, R2
        CALL expect_not_z

        DATA R4, 'd'                ; CMP 0, 5 -> Z off
        COMM OUTDATA, R4
        DATA R1, 0
        DATA R2, 5
        CMP R1, R2
        CALL expect_not_z

        DATA R4, 'e'                ; CMP 3, #4 -> Z off
        COMM OUTDATA, R4
        DATA R1, 3
        CMP R1, #4
        CALL expect_not_z

        DATA R4, 'f'                ; CMP 3, 2 -> A on
        COMM OUTDATA, R4
        DATA R1, 3
        DATA R2, 2
        CMP R1, R2
        CALL expect_a

        DATA R4, 'g'                ; CMP 1, 4 -> A off
        COMM OUTDATA, R4
        DATA R1, 1
        DATA R2, 4
        CMP R1, R2
        CALL expect_not_a

        DATA R4, 'h'                ; CMP 1, 4 -> N on
        COMM OUTDATA, R4
        DATA R1, 1
        DATA R2, 4
        CMP R1, R2
        CALL expect_n

        DATA R4, 'i'                ; MULT -1, #1 -> Z off
        COMM OUTDATA, R4
        DATA R1, -1
        MULT R1, #1
        CALL expect_not_z

        DATA R4, 'j'                ; MULT -1, 1 -> Z off
        COMM OUTDATA, R4
        DATA R1, -1
        DATA R2, 1
        MULT R1, R2
        CALL expect_not_z

        DATA R4, 'k'                ; SUB 3, #4 -> N on
        COMM OUTDATA, R4
        DATA R1, 3
        SUB R1, #4
        CALL expect_n

        DATA R4, 'l'                ; ADD -2, #1 -> N on
        COMM OUTDATA, R4
        DATA R1, -2
        ADD R1, #1
        CALL expect_n

        DATA R4, 'm'                ; FLOAT 7 = 7.0
        COMM OUTDATA, R4
        DATA R1, 7
        FLOAT R1
        CPY R0, R5
        DATA R6, 7.0
        SUB R5, R6                  ; SUB, not CMP
        CALL expect_z

        DATA R4, 'n'                ; INT 5.0 = 5
        COMM OUTDATA, R4
        DATA R1, 5.0
        INT R1
        CPY R0, R5
        DATA R6, 5
        SUB R5, R6
        CALL expect_z

        DATA R4, 'o'                ; INT 1.5, printed as a digit
        COMM OUTDATA, R4
        DATA R4, ' '
        COMM OUTDATA, R4
        DATA R1, 1.5
        INT R1
        ADD R0, #'0'
        COMM OUTDATA, R0
        DATA R4, '\n'
        COMM OUTDATA, R4

        DATA R4, 'p'                ; FSUB 3.0 - 3.0 -> Z on
        COMM OUTDATA, R4
        DATA R1, 3.0
        DATA R2, 3.0
        FSUB R1, R2
        CALL expect_z

        HALT

; CALL and COMM leave the flags alone, so these see the test's flags.
; Each prints " P" or " F" and a newline.
expect_z:
        RJF Z, pass
        RJMP fail
expect_not_z:
        RJNF Z, pass
        RJMP fail
expect_a:
        RJF A, pass
        RJMP fail
expect_not_a:
        RJNF A, pass
        RJMP fail
expect_n:
        RJF N, pass
fail:
        DATA R4, ' '
        COMM OUTDATA, R4
        DATA R4, 'F'
        COMM OUTDATA, R4
        RJMP gap
pass:
        DATA R4, ' '
        COMM OUTDATA, R4
        DATA R4, 'P'
        COMM OUTDATA, R4
gap:
        DATA R4, '\n'
        COMM OUTDATA, R4
        RET
