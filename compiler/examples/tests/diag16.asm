; ==================================================================
; diag16.asm - where STK SET/GET put EBP + RB (diag11 found the sum
; leaves the stack area), the flags after DIV, MOD and NOT, the float
; opcodes that have no defined result, and how the float unit rounds.
;
; From the project root:
;   python compiler/src/asm build compiler/examples/tests/diag16.asm
;          compiler/examples/stdlib/stdlib.asm
;   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diag16.rom --seconds 600
;
; diag16.asm must come FIRST on the command line: its results then sit in
; RAM from 0x14000. They are also printed, one hex word per line, in the
; same order. Flag words hold C A N Z as bits 3..0 (C=8 A=4 N=2 Z=1).
;
; line RAM      what                              sum wraps    sum wraps
;                                                 at 16 bits   at 14 bits
; ---- A: STK SET/GET with EBP + RB outside 0..0x3FFF (EBP = 0 at first)
;  1  0x14000  SET -1, then LD 0x1FFFF            A1A1A1A1     00000000
;  2  0x14001  ... LD 0x13FFF                     00000000     A1A1A1A1
;  3  0x14002  SET 0x8000, then LD 0x18000        A2A2A2A2     00000000
;  4  0x14003  ... LD 0x10000                     00000000     A2A2A2A2
;  5  0x14004  ST A3A3A3A3 at 0x18000, GET 0x8000 A3A3A3A3     A2A2A2A2
;  6  0x14005  SET 0x28004, then LD 0x18004       A4A4A4A4     00000000
;  7  0x14006  ... LD 0x10004                     00000000     A4A4A4A4
;              (push 11111111 and 22222222, STK CALL: EBP = 2)
;  8  0x14007  SET 0x7FFF (2 + 0x7FFF = 0x8001),  A5A5A5A5     00000000
;              then LD 0x18001
;  9  0x14008  ... LD 0x10001 (the second push)   22222222     A5A5A5A5
;
; ---- B: R0, then the flags, as the ISA says (A compares RA with RB;
;      one-operand ops run with R0 = 0, so A compares 0 with RB)
; 10/11  0x14009  DIV 6, 3                        00000002  00000004
; 12/13  0x1400B  DIV 3, 6                        00000000  00000001
; 14/15  0x1400D  DIV -6, 3                       FFFFFFFE  00000002
; 16/17  0x1400F  DIV 7, 0  (the simulator gives  00000007  00000004
;                 back the dividend)
; 18/19  0x14011  MOD 6, 3                        00000000  00000005
; 20/21  0x14013  MOD -7, 3                       FFFFFFFF  00000002
; 22/23  0x14015  MOD 7, 0  (as DIV 7, 0)         00000007  00000004
; 24/25  0x14017  NOT 0xFFFFFFFF                  00000000  00000005
; 26/27  0x14019  NOT 0                           FFFFFFFF  00000002
; 28/29  0x1401B  MULT -3, 4                      FFFFFFF4  00000002
; 30/31  0x1401D  SHL 0x40000000                  80000000  00000002
;
; ---- C: float opcodes with no defined result: word 0x3n12 (float group,
;      opcode n, RA = R1 = 2.5, RB = R2 = 1.5), R0 = 77777777 before.
;      The simulator writes 0 to R0 (FLOAT_NOP_RESULT): R0 00000000, flags
;      00000005 (Z, and A = 2.5 > 1.5) on every pair.
; 32/33  0x1401F  opcode 4 (SHL in the integer group)
; 34/35  0x14021  opcode 5 (SHR)
; 36/37  0x14023  opcode 8
; 38/39  0x14025  opcode 9
; 40/41  0x14027  opcode A
; 42/43  0x14029  opcode B (++)
; 44/45  0x1402B  opcode C (--)
; 46/47  0x1402D  opcode E
;
; ---- D: float rounding, R0 only        nearest, ties   other
;                                         to even
; 48  0x1402F  FADD 1.0 + 2^-24 (a tie)  3F800000        3F800001: ties round up
; 49  0x14030  FADD (1 + 2^-23) + 2^-24  3F800002        3F800001: truncates
;              (a tie)
; 50  0x14031  FSUB 1.0 - 2^-25 (a tie)  3F800000        3F7FFFFF: truncates
; 51  0x14032  FDIV 1.0 / 3.0            3EAAAAAB        3EAAAAAA: truncates
; 52  0x14033  FMULT 0x3EAAAAAB squared  3DE38E3A        3DE38E39: truncates
;
; MEASURED on the circuit (2026-10-13):
;   A, lines 1-9: the "16 bits" column, every one. The simulator now does
;   the same.
;   B: as the ISA says, except
;     22/23  MOD 7, 0            00000000  00000005  (MOD by 0 gives 0)
;     24/25  NOT 0xFFFFFFFF      FFFFFFFF  00000006  (NOT inverts R0, the RA
;            input: see diag17)
;   C: opcode 4                  40400000  00000004  (3.0 = RB x 2)
;      opcodes 5, B, C           FFFFFFFF  00000007  (N and Z both on)
;      opcodes 8, 9, A, E        00000000  00000005  (as the simulator)
;   D: the "nearest, ties to even" column, every one.
;
; After the 52 lines the program halts with ESP = EBP = 0.
; ==================================================================

        .extern print_hex, print_newline
        .global start

        .equ COUNT, 52

        .ram
results:    .space COUNT

        .rom
start:
        DATA R9, results            ; R9 = results
        DATA R10, 0                 ; R10 = how many stored

; ---- A: STK SET/GET, EBP = 0 (nothing has been called yet)
        DATA R0, 0xA1A1A1A1
        DATA R1, -1
        STK SET, R1                 ; stack[ebp - 1] = R0
        DATA R2, 0x1FFFF
        LD R2, R0                   ; result 1
        AST R9, R10
        ++ R10
        CPY R0, R10
        DATA R2, 0x13FFF
        LD R2, R0                   ; result 2
        AST R9, R10
        ++ R10
        CPY R0, R10

        DATA R0, 0xA2A2A2A2
        DATA R1, 0x8000
        STK SET, R1                 ; stack[ebp + 0x8000] = R0
        DATA R2, 0x18000
        LD R2, R0                   ; result 3
        AST R9, R10
        ++ R10
        CPY R0, R10
        DATA R2, 0x10000
        LD R2, R0                   ; result 4
        AST R9, R10
        ++ R10
        CPY R0, R10

        DATA R2, 0x18000
        DATA R3, 0xA3A3A3A3
        ST R2, R3                   ; RAM 0x18000 = A3A3A3A3
        DATA R1, 0x8000
        DATA R0, 0
        STK GET, R1                 ; result 5: R0 = stack[ebp + 0x8000]
        AST R9, R10
        ++ R10
        CPY R0, R10

        DATA R0, 0xA4A4A4A4
        DATA R1, 0x28004
        STK SET, R1                 ; stack[ebp + 0x28004] = R0
        DATA R2, 0x18004
        LD R2, R0                   ; result 6
        AST R9, R10
        ++ R10
        CPY R0, R10
        DATA R2, 0x10004
        LD R2, R0                   ; result 7
        AST R9, R10
        ++ R10
        CPY R0, R10

; ---- A, with EBP = 2
        DATA R0, 0x11111111
        STK PUSH                    ; stack[0]
        DATA R0, 0x22222222
        STK PUSH                    ; stack[1]
        STK CALL                    ; stack[2] = EBP (0), EBP = 2, ESP = 3
        DATA R0, 0xA5A5A5A5
        DATA R1, 0x7FFF
        STK SET, R1                 ; stack[2 + 0x7FFF] = R0
        DATA R2, 0x18001
        LD R2, R0                   ; result 8
        AST R9, R10
        ++ R10
        CPY R0, R10
        DATA R2, 0x10001
        LD R2, R0                   ; result 9
        AST R9, R10
        ++ R10
        CPY R0, R10
        STK RET                     ; ESP = 2, EBP = stack[2] = 0
        STK POP
        STK POP                     ; ESP = 0

; ---- B: each test sets R13 to where grab comes back, runs the op and
; jumps to grab, which stores R0 and then the flags
        DATA R1, 6
        DATA R2, 3
        DATA R13, b1
        DIV R1, R2
        RJMP grab
b1:
        DATA R1, 3
        DATA R2, 6
        DATA R13, b2
        DIV R1, R2
        RJMP grab
b2:
        DATA R1, -6
        DATA R2, 3
        DATA R13, b3
        DIV R1, R2
        RJMP grab
b3:
        DATA R1, 7
        DATA R2, 0
        DATA R13, b4
        DIV R1, R2
        RJMP grab
b4:
        DATA R1, 6
        DATA R2, 3
        DATA R13, b5
        MOD R1, R2
        RJMP grab
b5:
        DATA R1, -7
        DATA R2, 3
        DATA R13, b6
        MOD R1, R2
        RJMP grab
b6:
        DATA R1, 7
        DATA R2, 0
        DATA R13, b7
        MOD R1, R2
        RJMP grab
b7:
        DATA R2, 0xFFFFFFFF
        DATA R13, b8
        DATA R0, 0
        NOT R2
        RJMP grab
b8:
        DATA R2, 0
        DATA R13, b9
        DATA R0, 0
        NOT R2
        RJMP grab
b9:
        DATA R1, -3
        DATA R2, 4
        DATA R13, b10
        MULT R1, R2
        RJMP grab
b10:
        DATA R2, 0x40000000
        DATA R13, b11
        DATA R0, 0
        SHL R2
        RJMP grab
b11:

; ---- C: the float opcodes with no defined result, as raw words
        DATA R1, 0x40200000         ; 2.5
        DATA R2, 0x3FC00000         ; 1.5
        DATA R13, c1
        DATA R0, 0x77777777
        .word 0x3412                ; float group, opcode 4
        RJMP grab
c1:
        DATA R1, 0x40200000
        DATA R2, 0x3FC00000
        DATA R13, c2
        DATA R0, 0x77777777
        .word 0x3512                ; opcode 5
        RJMP grab
c2:
        DATA R1, 0x40200000
        DATA R2, 0x3FC00000
        DATA R13, c3
        DATA R0, 0x77777777
        .word 0x3812                ; opcode 8
        RJMP grab
c3:
        DATA R1, 0x40200000
        DATA R2, 0x3FC00000
        DATA R13, c4
        DATA R0, 0x77777777
        .word 0x3912                ; opcode 9
        RJMP grab
c4:
        DATA R1, 0x40200000
        DATA R2, 0x3FC00000
        DATA R13, c5
        DATA R0, 0x77777777
        .word 0x3A12                ; opcode A
        RJMP grab
c5:
        DATA R1, 0x40200000
        DATA R2, 0x3FC00000
        DATA R13, c6
        DATA R0, 0x77777777
        .word 0x3B12                ; opcode B
        RJMP grab
c6:
        DATA R1, 0x40200000
        DATA R2, 0x3FC00000
        DATA R13, c7
        DATA R0, 0x77777777
        .word 0x3C12                ; opcode C
        RJMP grab
c7:
        DATA R1, 0x40200000
        DATA R2, 0x3FC00000
        DATA R13, c8
        DATA R0, 0x77777777
        .word 0x3E12                ; opcode E
        RJMP grab
c8:

; ---- D: float rounding
        DATA R1, 0x3F800000         ; 1.0
        DATA R2, 0x33800000         ; 2^-24
        FADD R1, R2                 ; result 48
        AST R9, R10
        ++ R10
        CPY R0, R10
        DATA R1, 0x3F800001         ; 1 + 2^-23
        DATA R2, 0x33800000         ; 2^-24
        FADD R1, R2                 ; result 49
        AST R9, R10
        ++ R10
        CPY R0, R10
        DATA R1, 0x3F800000         ; 1.0
        DATA R2, 0x33000000         ; 2^-25
        FSUB R1, R2                 ; result 50
        AST R9, R10
        ++ R10
        CPY R0, R10
        DATA R1, 0x3F800000         ; 1.0
        DATA R2, 0x40400000         ; 3.0
        FDIV R1, R2                 ; result 51
        AST R9, R10
        ++ R10
        CPY R0, R10
        DATA R1, 0x3EAAAAAB         ; 1/3 as a float
        FMULT R1, R1                ; result 52
        AST R9, R10
        ++ R10
        CPY R0, R10

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
