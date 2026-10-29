; ==================================================================
; diag18.asm - the flags after OR and XOR (the last integer ops whose N
; and Z the C compiler's peephole pass relies on without a measurement),
; and NOT as the assembler writes it since diag17 (the register in both
; the RA and RB fields).
;
; From the project root:
;   python compiler/src/asm build compiler/examples/asm/tests/diag18.asm
;          compiler/examples/asm/stdlib/stdlib.asm
;   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diag18.rom --seconds 600
;
; diag18.asm must come FIRST on the command line: its results then sit in
; RAM from 0x14000. They are also printed, one hex word per line, in the
; same order. Each test stores R0 and then the flags, C A N Z as bits
; 3..0 (C=8 A=4 N=2 Z=1).
;
; lines  RAM      what                               R0        flags
;                                                    (as the ISA says)
;  1/2   0x14000  OR 0, 0                            00000000  00000001
;  3/4   0x14002  OR 0x80000000, 1                   80000001  00000002
;  5/6   0x14004  OR 3, 4                            00000007  00000000
;  7/8   0x14006  XOR 5, 5                           00000000  00000001
;  9/10  0x14008  XOR -1, 1                          FFFFFFFE  00000002
; 11/12  0x1400A  XOR 1, -1                          FFFFFFFE  00000006
; 13/14  0x1400C  NOT R2 (0x1622), R0 = 12345678,    F0F0F0F0  00000002
;                 R2 = 0F0F0F0F
; 15/16  0x1400E  NOT R0 (0x1600), R0 = 0            FFFFFFFF  00000002
;
; MEASURED on the circuit (2026-10-13): every line as above, the same as
; the simulator.
;
; After the 16 lines the program halts.
; ==================================================================

        .extern print_hex, print_newline
        .global start

        .equ COUNT, 16

        .ram
results:    .space COUNT

        .rom
start:
        DATA R9, results            ; R9 = results
        DATA R10, 0                 ; R10 = how many stored

; each test sets R13 to where grab comes back, runs the op and jumps to
; grab, which stores R0 and then the flags
        DATA R1, 0
        DATA R2, 0
        DATA R13, t1
        OR R1, R2
        RJMP grab
t1:
        DATA R1, 0x80000000
        DATA R2, 1
        DATA R13, t2
        OR R1, R2
        RJMP grab
t2:
        DATA R1, 3
        DATA R2, 4
        DATA R13, t3
        OR R1, R2
        RJMP grab
t3:
        DATA R1, 5
        DATA R2, 5
        DATA R13, t4
        XOR R1, R2
        RJMP grab
t4:
        DATA R1, -1
        DATA R2, 1
        DATA R13, t5
        XOR R1, R2
        RJMP grab
t5:
        DATA R1, 1
        DATA R2, -1
        DATA R13, t6
        XOR R1, R2
        RJMP grab
t6:
        DATA R2, 0x0F0F0F0F
        DATA R13, t7
        DATA R0, 0x12345678
        NOT R2                      ; the assembler writes 0x1622
        RJMP grab
t7:
        DATA R13, t8
        DATA R0, 0
        NOT R0
        RJMP grab
t8:

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
