; ==================================================================
; diag17.asm - follow-up to diag16, which found three surprises: NOT
; 0xFFFFFFFF gave FFFFFFFF (as if NOT inverted R0, the RA input, not RB),
; MOD 7, 0 gave 0, and float opcodes 4, 5, B and C did not write 0.
; This pins them down with other inputs, and with NOT encoded with RA
; and RB both set (the assembler always puts RA = 0 for one-operand ops).
;
; From the project root:
;   python compiler/src/asm build compiler/examples/tests/diag17.asm
;          compiler/examples/stdlib/stdlib.asm
;   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diag17.rom --seconds 600
;
; diag17.asm must come FIRST on the command line: its results then sit in
; RAM from 0x14000. They are also printed, one hex word per line, in the
; same order. Each test stores R0 and then the flags, C A N Z as bits
; 3..0 (C=8 A=4 N=2 Z=1).
;
; ---- A: NOT                                   R0 if NOT inverts ...
;                                               RB        RA        RA AND RB
;  1/2   word 0x1602 (NOT R2 as assembled       F0F0F0F0  EDCBA987  FDFBF9F7
;        before 2026-10-13, RA = 0), R0 = 12345678, R2 = 0F0F0F0F
;  3/4   word 0x1612: RA = R1 = FFFF0000,      FF00FF00  0000FFFF  FF00FFFF
;        RB = R2 = 00FF00FF
;  5/6   word 0x1621: RA = R2, RB = R1         0000FFFF  FF00FF00  FF00FFFF
;
; ---- B: DIV and MOD edge cases                simulator (ISA)
;  7/8   MOD -7, 0                              FFFFFFF9  00000002
;  9/10  DIV -7, 0                              FFFFFFF9  00000002
; 11/12  DIV 0x80000000, -1                     80000000  00000002
; 13/14  MOD 0x80000000, -1                     00000000  00000001
;
; ---- C: float opcodes 4, 5, B, C (word 0x3n12: RA = R1, RB = R2),
;      R0 = 77777777 before.        a guess to test: 4 = RB x 2, 5 = RB / 2,
;                                   B = RB + 1.0, C = RB - 1.0
;      first R1 = 2.5, R2 = 5.0
; 15/16  opcode 4                               41200000 (10.0)
; 17/18  opcode 5                               40200000 (2.5)
; 19/20  opcode B                               40C00000 (6.0)
; 21/22  opcode C                               40800000 (4.0)
;      then R1 = -3.0, R2 = 0.75
; 23/24  opcode 4                               3FC00000 (1.5)
; 25/26  opcode 5                               3EC00000 (0.375)
; 27/28  opcode B                               3FE00000 (1.75)
; 29/30  opcode C                               BE800000 (-0.25)
;
; MEASURED on the circuit (2026-10-13):
;   A: the "RA" column, every one: EDCBA987 00000006, 0000FFFF 00000000,
;   FF00FF00 00000006. NOT inverts RA. The assembler now writes NOT Rx with
;   x in both fields, so it gives ~Rx on the circuit and in the simulator.
;   B: MOD -7, 0 gives 00000000 00000001 (MOD by 0 is 0); the other three
;   as the simulator.
;   C: opcode 4 gives 41200000 and 3FC00000 (RB x 2), flags 00000000;
;   opcodes 5, B and C give FFFFFFFF 00000003 every time (N and Z both on).
;
; MEASURED again (2026-10-15), after NOT was rewired to RB in the ALU:
;   A: the "RB" column, every one: F0F0F0F0 00000006, FF00FF00 00000002,
;   0000FFFF 00000004, as the simulator. B and C as on 2026-10-13.
;
; After the 30 lines the program halts.
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

; ---- A: NOT. Each test sets R13 to where grab comes back, runs the op
; and jumps to grab, which stores R0 and then the flags
        DATA R2, 0x0F0F0F0F
        DATA R13, a1
        DATA R0, 0x12345678
        .word 0x1602                ; NOT R2 as it was encoded (RA = 0)
        RJMP grab
a1:
        DATA R1, 0xFFFF0000
        DATA R2, 0x00FF00FF
        DATA R13, a2
        DATA R0, 0x77777777
        .word 0x1612                ; NOT with RA = R1, RB = R2
        RJMP grab
a2:
        DATA R1, 0xFFFF0000
        DATA R2, 0x00FF00FF
        DATA R13, a3
        DATA R0, 0x77777777
        .word 0x1621                ; NOT with RA = R2, RB = R1
        RJMP grab
a3:

; ---- B: DIV and MOD edge cases
        DATA R1, -7
        DATA R2, 0
        DATA R13, b1
        MOD R1, R2
        RJMP grab
b1:
        DATA R1, -7
        DATA R2, 0
        DATA R13, b2
        DIV R1, R2
        RJMP grab
b2:
        DATA R1, 0x80000000
        DATA R2, -1
        DATA R13, b3
        DIV R1, R2
        RJMP grab
b3:
        DATA R1, 0x80000000
        DATA R2, -1
        DATA R13, b4
        MOD R1, R2
        RJMP grab
b4:

; ---- C: float opcodes 4, 5, B, C with two sets of inputs
        DATA R1, 0x40200000         ; 2.5
        DATA R2, 0x40A00000         ; 5.0
        DATA R13, c1
        DATA R0, 0x77777777
        .word 0x3412                ; opcode 4
        RJMP grab
c1:
        DATA R1, 0x40200000
        DATA R2, 0x40A00000
        DATA R13, c2
        DATA R0, 0x77777777
        .word 0x3512                ; opcode 5
        RJMP grab
c2:
        DATA R1, 0x40200000
        DATA R2, 0x40A00000
        DATA R13, c3
        DATA R0, 0x77777777
        .word 0x3B12                ; opcode B
        RJMP grab
c3:
        DATA R1, 0x40200000
        DATA R2, 0x40A00000
        DATA R13, c4
        DATA R0, 0x77777777
        .word 0x3C12                ; opcode C
        RJMP grab
c4:
        DATA R1, 0xC0400000         ; -3.0
        DATA R2, 0x3F400000         ; 0.75
        DATA R13, c5
        DATA R0, 0x77777777
        .word 0x3412                ; opcode 4
        RJMP grab
c5:
        DATA R1, 0xC0400000
        DATA R2, 0x3F400000
        DATA R13, c6
        DATA R0, 0x77777777
        .word 0x3512                ; opcode 5
        RJMP grab
c6:
        DATA R1, 0xC0400000
        DATA R2, 0x3F400000
        DATA R13, c7
        DATA R0, 0x77777777
        .word 0x3B12                ; opcode B
        RJMP grab
c7:
        DATA R1, 0xC0400000
        DATA R2, 0x3F400000
        DATA R13, c8
        DATA R0, 0x77777777
        .word 0x3C12                ; opcode C
        RJMP grab
c8:

; ---- print every result, one hex word per line
        DATA R8, 0
p_loop:
        SAVE R8, R9
        ALD R9, R8                  ; R0 = results[i]
        STK PUSH
        CALL print_hex, 1
        CALL print_newline
        RESTORE R8, R9
        ++ R8
        CPY R0, R8
        CMP R8, #COUNT
        RJNF Z, p_loop
        HALT

; grab: read the flags left by the op just run (nothing but DATA and the
; jump here has run since), store R0 and then the flags as C A N Z in
; bits 3..0, and go back to the address in R13
grab:
        DATA R5, 0
        DATA R6, 0
        DATA R7, 0
        DATA R8, 0
        RJNF C, g_c
        DATA R5, 8
g_c:
        RJNF A, g_a
        DATA R6, 4
g_a:
        RJNF N, g_n
        DATA R7, 2
g_n:
        RJNF Z, g_z
        DATA R8, 1
g_z:
        AST R9, R10                 ; R0 of the op
        ++ R10
        CPY R0, R10
        ADD R5, R6
        ADD R0, R7
        ADD R0, R8
        AST R9, R10                 ; its flags
        ++ R10
        CPY R0, R10
        JMRB R13
