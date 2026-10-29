; ==================================================================
; diag15.asm - more float special cases, after diag14 found that the
; circuit gives 0.0/0.0 = NaN, 1.0/-0.0 = -inf and INT(inf) = FFFFFFFF
; (the simulator gave +inf, +inf and 0). Measures INT of -inf and of
; other values out of range, and the remaining divisions by zero.
;
; From the project root:
;   python compiler/src/asm build compiler/examples/asm/tests/diag15.asm
;          compiler/examples/asm/stdlib/stdlib.asm
;   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diag15.rom
;
; diag15.asm must come FIRST on the command line: its results then sit in
; RAM from 0x14000. They are also printed, one hex word per line.
;
; line RAM      what                       expected (IEEE; INT keeping the
;                                          low 32 bits, as diag14 showed)
;  1  0x14000  INT -inf                   ?          (FFFFFFFF like +inf, or 0)
;  2  0x14001  INT -NaN (FFC00000)        00000000
;  3  0x14002  INT 3e9                    B2D05E00
;  4  0x14003  INT -3e9                   4D2FA200
;  5  0x14004  INT 2^31                   80000000
;  6  0x14005  INT 1e20                   00000000
;  7  0x14006  INT largest float          00000000
;  8  0x14007  FDIV -1.0, -0.0            7F800000
;  9  0x14008  FDIV 0.0, -0.0             7FC00000   (NaN)
; 10  0x14009  FDIV -0.0, 0.0             7FC00000   (NaN)
; 11  0x1400A  FDIV inf, inf              7FC00000   (NaN)
; 12  0x1400B  FDIV 1.0, inf              00000000
; 13  0x1400C  FDIV NaN, 0.0              7FC00000
; 14  0x1400D  FMULT -1.0, 0.0            80000000   (-0.0)
; 15  0x1400E  FSUB 0.0, 0.0              00000000
;
; MEASURED on the circuit (2026-10-10): every line as expected, line 1 is
; 00000000, and lines 6-7 (INT 1e20, INT largest float) are FFFFFFFF, not
; 0: INT is Java's (long) cast keeping the low 32 bits.
; ==================================================================

        .extern print_hex, print_newline
        .global start

        .equ COUNT, 15

        .ram
results:    .space COUNT

        .rom
start:
        DATA R9, results            ; R9 = results
        DATA R10, 0                 ; R10 = how many stored

; INT -inf
        DATA R1, 0xFF800000
        INT R1
        AST R9, R10                 ; result 1: INT -inf
        ++ R10
        CPY R0, R10
; INT -NaN
        DATA R1, 0xFFC00000
        INT R1
        AST R9, R10                 ; result 2: INT -NaN
        ++ R10
        CPY R0, R10
; INT 3e9
        DATA R1, 3e9
        INT R1
        AST R9, R10                 ; result 3: INT 3e9
        ++ R10
        CPY R0, R10
; INT -3e9
        DATA R1, -3e9
        INT R1
        AST R9, R10                 ; result 4: INT -3e9
        ++ R10
        CPY R0, R10
; INT 2^31
        DATA R1, 2147483648.0
        INT R1
        AST R9, R10                 ; result 5: INT 2^31
        ++ R10
        CPY R0, R10
; INT 1e20
        DATA R1, 1e20
        INT R1
        AST R9, R10                 ; result 6: INT 1e20
        ++ R10
        CPY R0, R10
; INT largest float
        DATA R1, 0x7F7FFFFF
        INT R1
        AST R9, R10                 ; result 7: INT largest float
        ++ R10
        CPY R0, R10
; FDIV -1.0, -0.0
        DATA R1, -1.0
        DATA R2, 0x80000000
        FDIV R1, R2
        AST R9, R10                 ; result 8: FDIV -1.0, -0.0
        ++ R10
        CPY R0, R10
; FDIV 0.0, -0.0
        DATA R1, 0.0
        DATA R2, 0x80000000
        FDIV R1, R2
        AST R9, R10                 ; result 9: FDIV 0.0, -0.0
        ++ R10
        CPY R0, R10
; FDIV -0.0, 0.0
        DATA R1, 0x80000000
        DATA R2, 0.0
        FDIV R1, R2
        AST R9, R10                 ; result 10: FDIV -0.0, 0.0
        ++ R10
        CPY R0, R10
; FDIV inf, inf
        DATA R1, 0x7F800000
        DATA R2, 0x7F800000
        FDIV R1, R2
        AST R9, R10                 ; result 11: FDIV inf, inf
        ++ R10
        CPY R0, R10
; FDIV 1.0, inf
        DATA R1, 1.0
        DATA R2, 0x7F800000
        FDIV R1, R2
        AST R9, R10                 ; result 12: FDIV 1.0, inf
        ++ R10
        CPY R0, R10
; FDIV NaN, 0.0
        DATA R1, 0x7FC00000
        DATA R2, 0.0
        FDIV R1, R2
        AST R9, R10                 ; result 13: FDIV NaN, 0.0
        ++ R10
        CPY R0, R10
; FMULT -1.0, 0.0
        DATA R1, -1.0
        DATA R2, 0.0
        FMULT R1, R2
        AST R9, R10                 ; result 14: FMULT -1.0, 0.0
        ++ R10
        CPY R0, R10
; FSUB 0.0, 0.0
        DATA R1, 0.0
        DATA R2, 0.0
        FSUB R1, R2
        AST R9, R10                 ; result 15: FSUB 0.0, 0.0
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
