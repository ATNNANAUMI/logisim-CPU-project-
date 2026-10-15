; ==================================================================
; diag12.asm - what the C compiler relies on: reading and setting
; ESP/EBP, stack slots as RAM addresses, the carry flag after SUB/CMP,
; the A flag after FCMP, MULT's low bits, DIV by 0x80000000
;
; From the project root:
;   python compiler/src/asm build compiler/examples/tests/diag12.asm
;          compiler/examples/stdlib/stdlib.asm
;   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diag12.rom
;
; diag12.asm must come FIRST on the command line: its results then sit in
; RAM from 0x14000. They are also printed, one hex word per line, in the
; same order. A flags line holds C A N Z as bits 3..0 (C=8 A=4 N=2 Z=1).
;
; line RAM      what                               as the ISA   other
;                                                  says         outcome
; ---- A: stack registers (run first, while ESP = EBP = 0)
;  1  0x14000  read EBP (EBP = 3)                  00000003
;  2  0x14001  read ESP (ESP = 4)                  00000004
;  3  0x14002  STK SET ebp+1, LD 0x10004           CAFE0003    stack slot i is
;  4  0x14003  ST 0x10005, STK GET ebp+2           CAFE0004    not RAM 0x10000+i
;  5  0x14004  EBP after setting EBP=2, ESP=10     00000002
;  6  0x14005  ESP after that                      0000000A
;  7  0x14006  EBP after setting both back to 0    00000000
;  8  0x14007  ESP after that                      00000000
; ---- B: carry flag                                C = no borrow  C = borrow
;  9  0x14008  CMP 5, 3                            0000000C    00000004
; 10  0x14009  CMP 3, 5                            00000002    0000000A
; 11  0x1400A  CMP 5, 5                            00000009    00000001
; 12  0x1400B  CMP 0x80000000, 1                   00000008    00000000
; 13  0x1400C  CMP 1, 0xFFFFFFFF                   00000004    0000000C
; 14  0x1400D  SUB 3, 5                            00000002    0000000A
; 15  0x1400E  ADD 0xFFFFFFFF, 1 (carry out)       00000009
; 16  0x1400F  CMP 0, 0                            00000009    00000001
; 17  0x14010  CMP 0, 1                            00000002    0000000A
; 18  0x14011  CMP 0xFFFFFFFF, 0                   0000000A    00000002
; 19  0x14012  CMP 7, #9                           00000002    0000000A
; ---- C: A flag after FCMP                         float compare  bits compared
; 20  0x14013  FCMP -2.0, -1.0                     00000002    00000006
; 21  0x14014  FCMP -1.0, -2.0                     00000004    00000000
; 22  0x14015  FCMP 1.0, 2.0                       00000002
; 23  0x14016  FCMP 2.0, 1.0                       00000004
; ---- D: MULT keeps the low 32 bits
; 24  0x14017  MULT 0x12345678, 0x100              34567800
; 25  0x14018  MULT -1, 0x80000000                 80000000
; 26  0x14019  MULT 0x10000, 0x10000               00000000
; 27  0x1401A  MULT 0x7FFFFFFF, 2                  FFFFFFFE
; ---- E: dividing by 0x80000000 (-2^31)
; 28  0x1401B  DIV 0x40000000, 0x80000000          00000000
; 29  0x1401C  DIV 0x80000000, 0x80000000          00000001
; 30  0x1401D  MOD 5, 0x80000000                   00000005
;
; After the 30 lines the program halts with ESP = EBP = 0.
;
; MEASURED on the circuit (2026-10-10):
;   lines 1-8, 20-30: as the ISA says (the ESP/EBP tricks work, stack slot
;   i is RAM 0x10000+i, FCMP's A is a float compare, MULT keeps the low
;   bits, DIV/MOD by 0x80000000 truncate)
;   lines 9-19: CMP never sets C: 4 2 1 0 4 A 9 1 2 2 2 (A N Z as the ISA
;   says); SUB 3, 5 sets it (line 14: A), so C is a borrow. diag13 follows up.
; ==================================================================

        .extern print_hex, print_newline
        .global start

        .equ COUNT, 30

        .ram
results:    .space COUNT

        .rom
start:
        DATA R9, results            ; R9 = results
        DATA R10, 0                 ; R10 = how many stored

; ---- A: stack registers
        DATA R0, 0x11
        STK PUSH
        STK PUSH
        STK PUSH                    ; ESP = 3
        STK CALL                    ; stack[3] = 0, EBP = 3, ESP = 4
        STK CALL                    ; read EBP: stack[4] = EBP = 3, EBP = 4, ESP = 5
        DATA R1, 0
        STK GET, R1                 ; R0 = stack[4] = 3
        STK RET                     ; ESP = 4, EBP = 3 again
        AST R9, R10                 ; result 1: EBP
        ++ R10
        CPY R0, R10
        STK CALL                    ; read ESP: stack[4] = 3, EBP = 4, ESP = 5
        STK CALL                    ; stack[5] = 4, EBP = 5, ESP = 6
        DATA R1, 0
        STK GET, R1                 ; R0 = stack[5] = 4, the ESP we had
        STK RET
        STK RET                     ; ESP = 4, EBP = 3 again
        AST R9, R10                 ; result 2: ESP
        ++ R10
        CPY R0, R10
        DATA R0, 0xCAFE0003
        DATA R1, 1
        STK SET, R1                 ; stack[ebp + 1] = stack[4]
        DATA R2, 0x10004
        LD R2, R0                   ; read it back as RAM 0x10004
        AST R9, R10                 ; result 3
        ++ R10
        CPY R0, R10
        DATA R2, 0x10005
        DATA R3, 0xCAFE0004
        ST R2, R3                   ; RAM 0x10005 = stack[5]
        DATA R1, 2
        STK GET, R1                 ; R0 = stack[ebp + 2]
        AST R9, R10                 ; result 4
        ++ R10
        CPY R0, R10
        ; set ESP = 10, EBP = 2: stack[ebp] = 10, STK RET (ESP = 3, EBP = 10),
        ; then stack[10] = 2, STK RET (ESP = 10, EBP = 2)
        DATA R1, 0
        DATA R0, 10
        STK SET, R1
        STK RET
        DATA R0, 2
        STK SET, R1
        STK RET
        STK CALL                    ; read EBP
        STK GET, R1
        STK RET
        AST R9, R10                 ; result 5: EBP
        ++ R10
        CPY R0, R10
        DATA R1, 0
        STK CALL                    ; read ESP
        STK CALL
        STK GET, R1
        STK RET
        STK RET
        AST R9, R10                 ; result 6: ESP
        ++ R10
        CPY R0, R10
        ; both back to 0: stack[2] = 0, STK RET (ESP = 2, EBP = 0),
        ; then stack[0] = 0, STK RET (ESP = 0, EBP = 0)
        DATA R1, 0
        DATA R0, 0
        STK SET, R1
        STK RET
        STK SET, R1
        STK RET
        STK CALL                    ; read EBP
        STK GET, R1
        STK RET
        AST R9, R10                 ; result 7: EBP
        ++ R10
        CPY R0, R10
        DATA R1, 0
        STK CALL                    ; read ESP
        STK CALL
        STK GET, R1
        STK RET
        STK RET
        AST R9, R10                 ; result 8: ESP
        ++ R10
        CPY R0, R10

; ---- B to E: one flags nibble or value per line
; CMP 5, 3
        DATA R1, 5
        DATA R2, 3
        CMP R1, R2
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
        AST R9, R10                 ; result 1: flags CANZ of CMP 5, 3
        ++ R10
        CPY R0, R10
; CMP 3, 5
        DATA R1, 3
        DATA R2, 5
        CMP R1, R2
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
        AST R9, R10                 ; result 2: flags CANZ of CMP 3, 5
        ++ R10
        CPY R0, R10
; CMP 5, 5
        DATA R1, 5
        DATA R2, 5
        CMP R1, R2
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
        AST R9, R10                 ; result 3: flags CANZ of CMP 5, 5
        ++ R10
        CPY R0, R10
; CMP 0x80000000, 1
        DATA R1, 0x80000000
        DATA R2, 1
        CMP R1, R2
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
        AST R9, R10                 ; result 4: flags CANZ of CMP 0x80000000, 1
        ++ R10
        CPY R0, R10
; CMP 1, 0xFFFFFFFF
        DATA R1, 1
        DATA R2, 0xFFFFFFFF
        CMP R1, R2
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
        AST R9, R10                 ; result 5: flags CANZ of CMP 1, 0xFFFFFFFF
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
        AST R9, R10                 ; result 6: flags CANZ of SUB 3, 5
        ++ R10
        CPY R0, R10
; ADD 0xFFFFFFFF, 1
        DATA R1, 0xFFFFFFFF
        DATA R2, 1
        ADD R1, R2
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
        AST R9, R10                 ; result 7: flags CANZ of ADD 0xFFFFFFFF, 1
        ++ R10
        CPY R0, R10
; CMP 0, 0
        DATA R1, 0
        DATA R2, 0
        CMP R1, R2
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
        AST R9, R10                 ; result 8: flags CANZ of CMP 0, 0
        ++ R10
        CPY R0, R10
; CMP 0, 1
        DATA R1, 0
        DATA R2, 1
        CMP R1, R2
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
        AST R9, R10                 ; result 9: flags CANZ of CMP 0, 1
        ++ R10
        CPY R0, R10
; CMP 0xFFFFFFFF, 0
        DATA R1, 0xFFFFFFFF
        DATA R2, 0
        CMP R1, R2
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
        AST R9, R10                 ; result 10: flags CANZ of CMP 0xFFFFFFFF, 0
        ++ R10
        CPY R0, R10
; CMP 7, #9 (immediate)
        DATA R1, 7
        CMP R1, #9
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
        AST R9, R10                 ; result 11: flags CANZ of CMP 7, #9 (immediate)
        ++ R10
        CPY R0, R10
; FCMP -2.0, -1.0
        DATA R1, -2.0
        DATA R2, -1.0
        FCMP R1, R2
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
        AST R9, R10                 ; result 12: flags CANZ of FCMP -2.0, -1.0
        ++ R10
        CPY R0, R10
; FCMP -1.0, -2.0
        DATA R1, -1.0
        DATA R2, -2.0
        FCMP R1, R2
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
        AST R9, R10                 ; result 13: flags CANZ of FCMP -1.0, -2.0
        ++ R10
        CPY R0, R10
; FCMP 1.0, 2.0
        DATA R1, 1.0
        DATA R2, 2.0
        FCMP R1, R2
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
        AST R9, R10                 ; result 14: flags CANZ of FCMP 1.0, 2.0
        ++ R10
        CPY R0, R10
; FCMP 2.0, 1.0
        DATA R1, 2.0
        DATA R2, 1.0
        FCMP R1, R2
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
        AST R9, R10                 ; result 15: flags CANZ of FCMP 2.0, 1.0
        ++ R10
        CPY R0, R10
; MULT 0x12345678, 0x100
        DATA R1, 0x12345678
        DATA R2, 0x100
        MULT R1, R2
        AST R9, R10                 ; result 16: MULT 0x12345678, 0x100
        ++ R10
        CPY R0, R10
; MULT -1, 0x80000000
        DATA R1, 0xFFFFFFFF
        DATA R2, 0x80000000
        MULT R1, R2
        AST R9, R10                 ; result 17: MULT -1, 0x80000000
        ++ R10
        CPY R0, R10
; MULT 0x10000, 0x10000
        DATA R1, 0x10000
        DATA R2, 0x10000
        MULT R1, R2
        AST R9, R10                 ; result 18: MULT 0x10000, 0x10000
        ++ R10
        CPY R0, R10
; MULT 0x7FFFFFFF, 2
        DATA R1, 0x7FFFFFFF
        DATA R2, 2
        MULT R1, R2
        AST R9, R10                 ; result 19: MULT 0x7FFFFFFF, 2
        ++ R10
        CPY R0, R10
; DIV 0x40000000, 0x80000000
        DATA R1, 0x40000000
        DATA R2, 0x80000000
        DIV R1, R2
        AST R9, R10                 ; result 20: DIV 0x40000000, 0x80000000
        ++ R10
        CPY R0, R10
; DIV 0x80000000, 0x80000000
        DATA R1, 0x80000000
        DATA R2, 0x80000000
        DIV R1, R2
        AST R9, R10                 ; result 21: DIV 0x80000000, 0x80000000
        ++ R10
        CPY R0, R10
; MOD 5, 0x80000000
        DATA R1, 5
        DATA R2, 0x80000000
        MOD R1, R2
        AST R9, R10                 ; result 22: MOD 5, 0x80000000
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
