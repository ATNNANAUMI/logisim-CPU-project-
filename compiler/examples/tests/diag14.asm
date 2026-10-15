; ==================================================================
; diag14.asm - floating-point special cases: division by zero, NaN,
; infinity, INT of values out of range, overflow, subnormals.
; The C library needs to know these; the simulator gave 0.0/0.0 = +inf.
;
; From the project root:
;   python compiler/src/asm build compiler/examples/tests/diag14.asm
;          compiler/examples/stdlib/stdlib.asm
;   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diag14.rom
;
; diag14.asm must come FIRST on the command line: its results then sit in
; RAM from 0x14000. They are also printed, one hex word per line, in the
; same order. A flags line holds C A N Z as bits 3..0 (C=8 A=4 N=2 Z=1).
;
; line RAM      what                             IEEE / Java      simulator
;                                                float rules      before
;  1  0x14000  FDIV 1.0, 0.0                     7F800000         7F800000
;  2  0x14001  FDIV -1.0, 0.0                    FF800000         FF800000
;  3  0x14002  FDIV 0.0, 0.0                     7FC00000 (NaN)   7F800000
;  4  0x14003  FDIV 1.0, -0.0                    FF800000         7F800000
;  5  0x14004  FSUB inf, inf                     7FC00000 (NaN)   7FC00000
;  6  0x14005  FMULT inf, 0.0                    7FC00000 (NaN)   7FC00000
;  7  0x14006  FSUB NaN, 1.0                     7FC00000         7FC00000
;  8  0x14007  flags of FCMP 1.0, NaN            00000000         00000000
;  9  0x14008  flags of FCMP NaN, 1.0            00000000         00000000
; 10  0x14009  flags of FCMP NaN, NaN            00000000         00000000
; 11  0x1400A  INT NaN                           00000000         00000000
; 12  0x1400B  INT inf                           7FFFFFFF         00000000
; 13  0x1400C  INT 1e10                          7FFFFFFF         540BE400
; 14  0x1400D  INT -1e10                         80000000         ABF41C00
; 15  0x1400E  INT 2147483520.0                  7FFFFF80         7FFFFF80
; 16  0x1400F  FADD 3e38, 3e38                   7F800000         7F800000
; 17  0x14010  flags of that FADD                00000000         00000000
; 18  0x14011  FMULT 1e-20, 1e-20 (subnormal)    000116C2         000116C2
;                                                (00000000 if subnormals flush to 0)
; 19  0x14012  FADD 1 + 1 (smallest subnormals)  00000002         00000002
; 20  0x14013  FDIV 0x00800000, 2.0              00400000         00400000
; 21  0x14014  FLOAT 0x7FFFFFFF                  4F000000         4F000000
; 22  0x14015  FLOAT 0x80000000                  CF000000         CF000000
;
; MEASURED on the circuit (2026-10-10): the IEEE / Java column on every line
; except line 12: INT inf gives FFFFFFFF, and lines 13-14 wrap (540BE400,
; ABF41C00) instead of saturating. diag15 follows up on INT.
; ==================================================================

        .extern print_hex, print_newline
        .global start

        .equ COUNT, 22

        .ram
results:    .space COUNT

        .rom
start:
        DATA R9, results            ; R9 = results
        DATA R10, 0                 ; R10 = how many stored

; FDIV 1.0, 0.0
        DATA R1, 1.0
        DATA R2, 0.0
        FDIV R1, R2
        AST R9, R10                 ; result 1: FDIV 1.0, 0.0
        ++ R10
        CPY R0, R10
; FDIV -1.0, 0.0
        DATA R1, -1.0
        DATA R2, 0.0
        FDIV R1, R2
        AST R9, R10                 ; result 2: FDIV -1.0, 0.0
        ++ R10
        CPY R0, R10
; FDIV 0.0, 0.0
        DATA R1, 0.0
        DATA R2, 0.0
        FDIV R1, R2
        AST R9, R10                 ; result 3: FDIV 0.0, 0.0
        ++ R10
        CPY R0, R10
; FDIV 1.0, -0.0
        DATA R1, 1.0
        DATA R2, 0x80000000
        FDIV R1, R2
        AST R9, R10                 ; result 4: FDIV 1.0, -0.0
        ++ R10
        CPY R0, R10
; FSUB inf, inf
        DATA R1, 0x7F800000
        DATA R2, 0x7F800000
        FSUB R1, R2
        AST R9, R10                 ; result 5: FSUB inf, inf
        ++ R10
        CPY R0, R10
; FMULT inf, 0.0
        DATA R1, 0x7F800000
        DATA R2, 0.0
        FMULT R1, R2
        AST R9, R10                 ; result 6: FMULT inf, 0.0
        ++ R10
        CPY R0, R10
; FSUB NaN, 1.0
        DATA R1, 0x7FC00000
        DATA R2, 1.0
        FSUB R1, R2
        AST R9, R10                 ; result 7: FSUB NaN, 1.0
        ++ R10
        CPY R0, R10
; FCMP 1.0, NaN
        DATA R1, 1.0
        DATA R2, 0x7FC00000
        FCMP R1, R2
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
        AST R9, R10                 ; result 8: flags CANZ of FCMP 1.0, NaN
        ++ R10
        CPY R0, R10
; FCMP NaN, 1.0
        DATA R1, 0x7FC00000
        DATA R2, 1.0
        FCMP R1, R2
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
        AST R9, R10                 ; result 9: flags CANZ of FCMP NaN, 1.0
        ++ R10
        CPY R0, R10
; FCMP NaN, NaN
        DATA R1, 0x7FC00000
        DATA R2, 0x7FC00000
        FCMP R1, R2
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
        AST R9, R10                 ; result 10: flags CANZ of FCMP NaN, NaN
        ++ R10
        CPY R0, R10
; INT NaN
        DATA R1, 0x7FC00000
        INT R1
        AST R9, R10                 ; result 11: INT NaN
        ++ R10
        CPY R0, R10
; INT inf
        DATA R1, 0x7F800000
        INT R1
        AST R9, R10                 ; result 12: INT inf
        ++ R10
        CPY R0, R10
; INT 1e10
        DATA R1, 1e10
        INT R1
        AST R9, R10                 ; result 13: INT 1e10
        ++ R10
        CPY R0, R10
; INT -1e10
        DATA R1, -1e10
        INT R1
        AST R9, R10                 ; result 14: INT -1e10
        ++ R10
        CPY R0, R10
; INT 2147483520.0 (largest float below 2^31)
        DATA R1, 2147483520.0
        INT R1
        AST R9, R10                 ; result 15: INT 2147483520.0 (largest float below 2^31)
        ++ R10
        CPY R0, R10
; FADD 3e38, 3e38
        DATA R1, 3e38
        DATA R2, 3e38
        FADD R1, R2
        AST R9, R10                 ; result 16: FADD 3e38, 3e38
        ++ R10
        CPY R0, R10
; FADD 3e38, 3e38
        DATA R1, 3e38
        DATA R2, 3e38
        FADD R1, R2
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
        AST R9, R10                 ; result 17: flags CANZ of FADD 3e38, 3e38
        ++ R10
        CPY R0, R10
; FMULT 1e-20, 1e-20 (1e-40 is subnormal)
        DATA R1, 1e-20
        DATA R2, 1e-20
        FMULT R1, R2
        AST R9, R10                 ; result 18: FMULT 1e-20, 1e-20 (1e-40 is subnormal)
        ++ R10
        CPY R0, R10
; FADD two smallest subnormals
        DATA R1, 0x00000001
        DATA R2, 0x00000001
        FADD R1, R2
        AST R9, R10                 ; result 19: FADD two smallest subnormals
        ++ R10
        CPY R0, R10
; FDIV smallest normal, 2.0
        DATA R1, 0x00800000
        DATA R2, 2.0
        FDIV R1, R2
        AST R9, R10                 ; result 20: FDIV smallest normal, 2.0
        ++ R10
        CPY R0, R10
; FLOAT 0x7FFFFFFF
        DATA R1, 0x7FFFFFFF
        FLOAT R1
        AST R9, R10                 ; result 21: FLOAT 0x7FFFFFFF
        ++ R10
        CPY R0, R10
; FLOAT 0x80000000
        DATA R1, 0x80000000
        FLOAT R1
        AST R9, R10                 ; result 22: FLOAT 0x80000000
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
