; diag4.asm - the flags ALU instructions leave behind
;
; Every earlier test checked a VALUE with CMP, and CMP rewrites the flags.
; So the flags that DIV and MOD themselves produce were never tested.
; The digit loop in int_to_str depends on exactly those: after
; "DIV R1, #10" giving -1, Z must be OFF so RJNF Z jumps back.
;
; These tests branch on the flags directly, with no CMP in between.
; Stands alone, no stdlib needed:
;   python compiler/src/asm build diag4.asm -o diag4.rom
;
;   a  DIV -12 / 10    = -1     Z off      <- the failing case
;   b  DIV -12 / 10    = -1     N on
;   c  MOD -12 % 10    = -2     Z off
;   d  MOD -12 % 10    = -2     N on
;   e  DIV -1234 / 10  = -123   Z off
;   f  DIV 12 / 10     = 1      Z off      (positive, for contrast)
;   g  DIV 5 / 10      = 0      Z on
;   h  MOD 10 % 10     = 0      Z on
;   i  SUB 3 - 4       = -1     Z off
;   j  ADD -2 + 1      = -1     Z off
;   k  MULT -1 * 1     = -1     Z off
;   l  NEG 1           = -1     Z off
;   m  ++ -2           = -1     Z off
;   n  -- 0            = -1     Z off
;   o  TEST -1                  Z off
;   p  CMP 3, 4        = -1     Z off
;
; Then two digit-loop counts, printed as a digit:
;   2  how many times the loop runs for 12     (must be 2)
;   4  how many times it runs for 1234         (must be 4)
;
; Reading it:
;   a c e fail, f g h pass  -> DIV/MOD set Z wrongly on a NEGATIVE result
;   a ... p all fail        -> every instruction does
;   only the counts wrong   -> the flags are right and RJNF is at fault

        .global start

start:
        DATA R3, 0x5C
        COMM OUTADDR, R3

        DATA R4, 'a'                ; DIV -12 / 10 = -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, -12
        DIV R1, #10
        CALL expect_not_z

        DATA R4, 'b'                ; the same, N must be on
        COMM OUTDATA, R4
        DATA R1, -12
        DIV R1, #10
        CALL expect_n

        DATA R4, 'c'                ; MOD -12 % 10 = -2, Z must be off
        COMM OUTDATA, R4
        DATA R1, -12
        MOD R1, #10
        CALL expect_not_z

        DATA R4, 'd'                ; the same, N must be on
        COMM OUTDATA, R4
        DATA R1, -12
        MOD R1, #10
        CALL expect_n

        DATA R4, 'e'                ; DIV -1234 / 10 = -123, Z must be off
        COMM OUTDATA, R4
        DATA R1, -1234
        DIV R1, #10
        CALL expect_not_z

        DATA R4, 'f'                ; DIV 12 / 10 = 1, Z must be off
        COMM OUTDATA, R4
        DATA R1, 12
        DIV R1, #10
        CALL expect_not_z

        DATA R4, 'g'                ; DIV 5 / 10 = 0, Z must be on
        COMM OUTDATA, R4
        DATA R1, 5
        DIV R1, #10
        CALL expect_z

        DATA R4, 'h'                ; MOD 10 % 10 = 0, Z must be on
        COMM OUTDATA, R4
        DATA R1, 10
        MOD R1, #10
        CALL expect_z

        DATA R4, 'i'                ; SUB 3 - 4 = -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, 3
        SUB R1, #4
        CALL expect_not_z

        DATA R4, 'j'                ; ADD -2 + 1 = -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, -2
        ADD R1, #1
        CALL expect_not_z

        DATA R4, 'k'                ; MULT -1 * 1 = -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, -1
        MULT R1, #1
        CALL expect_not_z

        DATA R4, 'l'                ; NEG 1 = -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, 1
        NEG R1
        CALL expect_not_z

        DATA R4, 'm'                ; ++ -2 = -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, -2
        ++ R1
        CALL expect_not_z

        DATA R4, 'n'                ; -- 0 = -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, 0
        -- R1
        CALL expect_not_z

        DATA R4, 'o'                ; TEST -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, -1
        TEST R1
        CALL expect_not_z

        DATA R4, 'p'                ; CMP 3, 4 = -1, Z must be off
        COMM OUTDATA, R4
        DATA R1, 3
        CMP R1, #4
        CALL expect_not_z

        DATA R4, '\n'
        COMM OUTDATA, R4

; count the digit-loop passes for 12: must print 2
        DATA R1, -12
        DATA R3, 0
loop12: MOD R1, #10                 ; the digit, thrown away here
        ++ R3
        CPY R0, R3
        DIV R1, #10
        CPY R0, R1
        RJNF Z, loop12
        ADD R3, #'0'
        COMM OUTDATA, R0

; the same for 1234: must print 4
        DATA R1, -1234
        DATA R3, 0
loop1234:
        MOD R1, #10
        ++ R3
        CPY R0, R3
        DIV R1, #10
        CPY R0, R1
        RJNF Z, loop1234
        ADD R3, #'0'
        COMM OUTDATA, R0

        DATA R4, '\n'
        COMM OUTDATA, R4
        HALT

; CALL and COMM leave the flags alone, so these see the test's flags.
expect_z:
        RJF Z, pass
        RJMP fail
expect_not_z:
        RJNF Z, pass
        RJMP fail
expect_n:
        RJF N, pass
fail:
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
