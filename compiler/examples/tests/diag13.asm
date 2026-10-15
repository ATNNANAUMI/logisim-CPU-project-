; ==================================================================
; diag13.asm - the carry flag (and the rest of C A N Z) after SUB, --,
; ++, NEG, SHL, SHR, MULT, ADD, AND and TEST. diag12 found that CMP
; never sets C and that SUB 3, 5 sets it, so C may mean "borrow".
;
; From the project root:
;   python compiler/src/asm build compiler/examples/tests/diag13.asm
;          compiler/examples/stdlib/stdlib.asm
;   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diag13.rom
;
; diag13.asm must come FIRST on the command line: its results then sit in
; RAM from 0x14000. They are also printed, one hex word per line, in the
; same order. Each line holds C A N Z as bits 3..0 (C=8 A=4 N=2 Z=1).
; One-operand ops run with R0 = 0, so A compares 0 with RB.
;
; line RAM      what                         C as the ISA says   C = borrow
;                                            (no borrow = 1)
;  1  0x14000  SUB 5, 3                      0000000C            00000004
;  2  0x14001  SUB 3, 5                      00000002            0000000A
;  3  0x14002  SUB 5, 5                      00000009            00000001
;  4  0x14003  SUB 0, 1                      00000002            0000000A
;  5  0x14004  SUB 0x80000000, 1             00000008            00000000
;  6  0x14005  SUB 1, 0xFFFFFFFF             00000004            0000000C
;  7  0x14006  SUB 0xFFFFFFFF, 0             0000000A            00000002
;  8  0x14007  SUB 3, #5                     00000002            0000000A
;  9  0x14008  SUB 5, #3                     0000000C            00000004
; 10  0x14009  -- 0                          00000002            0000000A
; 11  0x1400A  -- 5                          00000008            00000000
; 12  0x1400B  ++ 0xFFFFFFFF                 0000000D
; 13  0x1400C  ++ 5                          00000000
; 14  0x1400D  NEG 0                         00000009            00000001
; 15  0x1400E  NEG 5                         00000002            0000000A
; 16  0x1400F  SHL 0x80000000                0000000D
; 17  0x14010  SHL 1                         00000000
; 18  0x14011  SHR 1                         00000009
; 19  0x14012  SHR 2                         00000000
; 20  0x14013  MULT 0x10000, 0x10000         00000009
; 21  0x14014  MULT 3, 4                     00000000
; 22  0x14015  ADD 1, 2                      00000000
; 23  0x14016  AND 0xF0, 0x0F                00000005
; 24  0x14017  TEST 5                        00000000
;
; MEASURED on the circuit (2026-10-10):
;   lines 1-9: the "C = borrow" column, every one: SUB sets C when RA < RB
;   unsigned
;   lines 10, 11 (--), 14 (NEG 0), 20 (MULT overflow): C stays 0:
;   00000002 00000000 00000001 00000001; A N Z as the ISA says
;   every other line: as the ISA says
;
; ==================================================================

        .extern print_hex, print_newline
        .global start

        .equ COUNT, 24

        .ram
results:    .space COUNT

        .rom
start:
        DATA R9, results            ; R9 = results
        DATA R10, 0                 ; R10 = how many stored

; SUB 5, 3
        DATA R1, 5
        DATA R2, 3
        SUB R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f1c
        DATA R5, 8
f1c:
        RJNF A, f1a
        DATA R6, 4
f1a:
        RJNF N, f1n
        DATA R7, 2
f1n:
        RJNF Z, f1z
        DATA R8, 1
f1z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 1: flags of SUB 5, 3
        ++ R10
        CPY R0, R10
; SUB 3, 5
        DATA R1, 3
        DATA R2, 5
        SUB R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f2c
        DATA R5, 8
f2c:
        RJNF A, f2a
        DATA R6, 4
f2a:
        RJNF N, f2n
        DATA R7, 2
f2n:
        RJNF Z, f2z
        DATA R8, 1
f2z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 2: flags of SUB 3, 5
        ++ R10
        CPY R0, R10
; SUB 5, 5
        DATA R1, 5
        DATA R2, 5
        SUB R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f3c
        DATA R5, 8
f3c:
        RJNF A, f3a
        DATA R6, 4
f3a:
        RJNF N, f3n
        DATA R7, 2
f3n:
        RJNF Z, f3z
        DATA R8, 1
f3z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 3: flags of SUB 5, 5
        ++ R10
        CPY R0, R10
; SUB 0, 1
        DATA R1, 0
        DATA R2, 1
        SUB R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f4c
        DATA R5, 8
f4c:
        RJNF A, f4a
        DATA R6, 4
f4a:
        RJNF N, f4n
        DATA R7, 2
f4n:
        RJNF Z, f4z
        DATA R8, 1
f4z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 4: flags of SUB 0, 1
        ++ R10
        CPY R0, R10
; SUB 0x80000000, 1
        DATA R1, 0x80000000
        DATA R2, 1
        SUB R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f5c
        DATA R5, 8
f5c:
        RJNF A, f5a
        DATA R6, 4
f5a:
        RJNF N, f5n
        DATA R7, 2
f5n:
        RJNF Z, f5z
        DATA R8, 1
f5z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 5: flags of SUB 0x80000000, 1
        ++ R10
        CPY R0, R10
; SUB 1, 0xFFFFFFFF
        DATA R1, 1
        DATA R2, 0xFFFFFFFF
        SUB R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f6c
        DATA R5, 8
f6c:
        RJNF A, f6a
        DATA R6, 4
f6a:
        RJNF N, f6n
        DATA R7, 2
f6n:
        RJNF Z, f6z
        DATA R8, 1
f6z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 6: flags of SUB 1, 0xFFFFFFFF
        ++ R10
        CPY R0, R10
; SUB 0xFFFFFFFF, 0
        DATA R1, 0xFFFFFFFF
        DATA R2, 0
        SUB R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f7c
        DATA R5, 8
f7c:
        RJNF A, f7a
        DATA R6, 4
f7a:
        RJNF N, f7n
        DATA R7, 2
f7n:
        RJNF Z, f7z
        DATA R8, 1
f7z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 7: flags of SUB 0xFFFFFFFF, 0
        ++ R10
        CPY R0, R10
; SUB 3, #5
        DATA R1, 3
        SUB R1, #5
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f8c
        DATA R5, 8
f8c:
        RJNF A, f8a
        DATA R6, 4
f8a:
        RJNF N, f8n
        DATA R7, 2
f8n:
        RJNF Z, f8z
        DATA R8, 1
f8z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 8: flags of SUB 3, #5
        ++ R10
        CPY R0, R10
; SUB 5, #3
        DATA R1, 5
        SUB R1, #3
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f9c
        DATA R5, 8
f9c:
        RJNF A, f9a
        DATA R6, 4
f9a:
        RJNF N, f9n
        DATA R7, 2
f9n:
        RJNF Z, f9z
        DATA R8, 1
f9z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 9: flags of SUB 5, #3
        ++ R10
        CPY R0, R10
; -- 0 (R0 = 0)
        DATA R1, 0
        DATA R0, 0
        -- R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f10c
        DATA R5, 8
f10c:
        RJNF A, f10a
        DATA R6, 4
f10a:
        RJNF N, f10n
        DATA R7, 2
f10n:
        RJNF Z, f10z
        DATA R8, 1
f10z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 10: flags of -- 0 (R0 = 0)
        ++ R10
        CPY R0, R10
; -- 5 (R0 = 0)
        DATA R1, 5
        DATA R0, 0
        -- R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f11c
        DATA R5, 8
f11c:
        RJNF A, f11a
        DATA R6, 4
f11a:
        RJNF N, f11n
        DATA R7, 2
f11n:
        RJNF Z, f11z
        DATA R8, 1
f11z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 11: flags of -- 5 (R0 = 0)
        ++ R10
        CPY R0, R10
; ++ 0xFFFFFFFF (R0 = 0)
        DATA R1, 0xFFFFFFFF
        DATA R0, 0
        ++ R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f12c
        DATA R5, 8
f12c:
        RJNF A, f12a
        DATA R6, 4
f12a:
        RJNF N, f12n
        DATA R7, 2
f12n:
        RJNF Z, f12z
        DATA R8, 1
f12z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 12: flags of ++ 0xFFFFFFFF (R0 = 0)
        ++ R10
        CPY R0, R10
; ++ 5 (R0 = 0)
        DATA R1, 5
        DATA R0, 0
        ++ R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f13c
        DATA R5, 8
f13c:
        RJNF A, f13a
        DATA R6, 4
f13a:
        RJNF N, f13n
        DATA R7, 2
f13n:
        RJNF Z, f13z
        DATA R8, 1
f13z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 13: flags of ++ 5 (R0 = 0)
        ++ R10
        CPY R0, R10
; NEG 0 (R0 = 0)
        DATA R1, 0
        DATA R0, 0
        NEG R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f14c
        DATA R5, 8
f14c:
        RJNF A, f14a
        DATA R6, 4
f14a:
        RJNF N, f14n
        DATA R7, 2
f14n:
        RJNF Z, f14z
        DATA R8, 1
f14z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 14: flags of NEG 0 (R0 = 0)
        ++ R10
        CPY R0, R10
; NEG 5 (R0 = 0)
        DATA R1, 5
        DATA R0, 0
        NEG R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f15c
        DATA R5, 8
f15c:
        RJNF A, f15a
        DATA R6, 4
f15a:
        RJNF N, f15n
        DATA R7, 2
f15n:
        RJNF Z, f15z
        DATA R8, 1
f15z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 15: flags of NEG 5 (R0 = 0)
        ++ R10
        CPY R0, R10
; SHL 0x80000000 (R0 = 0)
        DATA R1, 0x80000000
        DATA R0, 0
        SHL R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f16c
        DATA R5, 8
f16c:
        RJNF A, f16a
        DATA R6, 4
f16a:
        RJNF N, f16n
        DATA R7, 2
f16n:
        RJNF Z, f16z
        DATA R8, 1
f16z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 16: flags of SHL 0x80000000 (R0 = 0)
        ++ R10
        CPY R0, R10
; SHL 1 (R0 = 0)
        DATA R1, 1
        DATA R0, 0
        SHL R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f17c
        DATA R5, 8
f17c:
        RJNF A, f17a
        DATA R6, 4
f17a:
        RJNF N, f17n
        DATA R7, 2
f17n:
        RJNF Z, f17z
        DATA R8, 1
f17z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 17: flags of SHL 1 (R0 = 0)
        ++ R10
        CPY R0, R10
; SHR 1 (R0 = 0)
        DATA R1, 1
        DATA R0, 0
        SHR R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f18c
        DATA R5, 8
f18c:
        RJNF A, f18a
        DATA R6, 4
f18a:
        RJNF N, f18n
        DATA R7, 2
f18n:
        RJNF Z, f18z
        DATA R8, 1
f18z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 18: flags of SHR 1 (R0 = 0)
        ++ R10
        CPY R0, R10
; SHR 2 (R0 = 0)
        DATA R1, 2
        DATA R0, 0
        SHR R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f19c
        DATA R5, 8
f19c:
        RJNF A, f19a
        DATA R6, 4
f19a:
        RJNF N, f19n
        DATA R7, 2
f19n:
        RJNF Z, f19z
        DATA R8, 1
f19z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 19: flags of SHR 2 (R0 = 0)
        ++ R10
        CPY R0, R10
; MULT 0x10000, 0x10000
        DATA R1, 0x10000
        DATA R2, 0x10000
        MULT R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f20c
        DATA R5, 8
f20c:
        RJNF A, f20a
        DATA R6, 4
f20a:
        RJNF N, f20n
        DATA R7, 2
f20n:
        RJNF Z, f20z
        DATA R8, 1
f20z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 20: flags of MULT 0x10000, 0x10000
        ++ R10
        CPY R0, R10
; MULT 3, 4
        DATA R1, 3
        DATA R2, 4
        MULT R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f21c
        DATA R5, 8
f21c:
        RJNF A, f21a
        DATA R6, 4
f21a:
        RJNF N, f21n
        DATA R7, 2
f21n:
        RJNF Z, f21z
        DATA R8, 1
f21z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 21: flags of MULT 3, 4
        ++ R10
        CPY R0, R10
; ADD 1, 2
        DATA R1, 1
        DATA R2, 2
        ADD R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f22c
        DATA R5, 8
f22c:
        RJNF A, f22a
        DATA R6, 4
f22a:
        RJNF N, f22n
        DATA R7, 2
f22n:
        RJNF Z, f22z
        DATA R8, 1
f22z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 22: flags of ADD 1, 2
        ++ R10
        CPY R0, R10
; AND 0xF0, 0x0F
        DATA R1, 0xF0
        DATA R2, 0x0F
        AND R1, R2
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f23c
        DATA R5, 8
f23c:
        RJNF A, f23a
        DATA R6, 4
f23a:
        RJNF N, f23n
        DATA R7, 2
f23n:
        RJNF Z, f23z
        DATA R8, 1
f23z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 23: flags of AND 0xF0, 0x0F
        ++ R10
        CPY R0, R10
; TEST 5 (R0 = 0)
        DATA R1, 5
        DATA R0, 0
        TEST R1
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, f24c
        DATA R5, 8
f24c:
        RJNF A, f24a
        DATA R6, 4
f24a:
        RJNF N, f24n
        DATA R7, 2
f24n:
        RJNF Z, f24z
        DATA R8, 1
f24z:
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; result 24: flags of TEST 5 (R0 = 0)
        ++ R10
        CPY R0, R10

; ---- print every result
        DATA R11, 0                 ; R11 = index
print:
        CMP R11, R10
        RJF AZ, done
        SAVE R9, R10, R11
        ALD R9, R11
        STK PUSH
        CALL print_hex, 1
        CALL print_newline
        RESTORE R9, R10, R11
        ++ R11
        CPY R0, R11
        RJMP print
done:
        HALT
