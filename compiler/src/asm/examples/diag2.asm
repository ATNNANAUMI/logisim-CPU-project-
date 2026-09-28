; diag2.asm - does an ALU instruction wrongly write its result into RA?
;
; The ISA says an ALU instruction writes ONLY R0. RA and RB keep their
; values. Each test below puts a known value in a register, runs one
; instruction on it, and checks the register still holds that value.
;
; Stands alone, no stdlib needed:
;   python compiler/src/asm build diag2.asm -o diag2.rom
;
; Every check compares with a register CMP, so the checking never depends
; on the immediate form working.
;
;   a  MOD  R1, #10      R1 unchanged
;   b  DIV  R1, #10      R1 unchanged
;   c  MULT R1, #2       R1 unchanged
;   d  ADD  R1, #1       R1 unchanged
;   e  SUB  R1, #1       R1 unchanged
;   f  AND  R1, #0x3     R1 unchanged
;   g  CMP  R1, #99      R1 unchanged
;   h  ADD  R1, R2       R1 unchanged   (register form)
;   i  MOD  R1, R2       R1 unchanged   (register form)
;   j  NEG  R1           R1 unchanged   (one operand: checks the RB field)
;   k  ++   R1           R1 unchanged   (one operand: checks the RB field)
;   l  FMULT R1, #2.0    R1 unchanged   (float immediate)
;   m  FADD R1, R2       R1 unchanged   (float register)
;   o  ADD  R1, R2       R2 unchanged   (checks the RB field)
;   n  12 MOD 10 then 12 DIV 10 = 1     (the int_to_str digit loop)
;
; All P  -> no register is being overwritten; the fault is elsewhere.
; Any F  -> that instruction also writes its result into RA.
;           The letters that fail say how wide the fault is:
;             a only          -> just MOD
;             a b c d e f g   -> every immediate instruction
;             a ... m         -> every ALU instruction
;           n fails whenever a or b does.

        .global start

start:
        DATA R3, 0x5C
        COMM OUTADDR, R3

        DATA R4, 'a'                ; MOD immediate
        COMM OUTDATA, R4
        DATA R1, 12
        MOD R1, #10
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'b'                ; DIV immediate
        COMM OUTDATA, R4
        DATA R1, 12
        DIV R1, #10
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'c'                ; MULT immediate
        COMM OUTDATA, R4
        DATA R1, 12
        MULT R1, #2
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'd'                ; ADD immediate
        COMM OUTDATA, R4
        DATA R1, 12
        ADD R1, #1
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'e'                ; SUB immediate
        COMM OUTDATA, R4
        DATA R1, 12
        SUB R1, #1
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'f'                ; AND immediate
        COMM OUTDATA, R4
        DATA R1, 12
        AND R1, #0x3
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'g'                ; CMP immediate
        COMM OUTDATA, R4
        DATA R1, 12
        CMP R1, #99
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'h'                ; ADD, register form
        COMM OUTDATA, R4
        DATA R1, 12
        DATA R2, 5
        ADD R1, R2
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'i'                ; MOD, register form
        COMM OUTDATA, R4
        DATA R1, 12
        DATA R2, 10
        MOD R1, R2
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'j'                ; NEG, one operand
        COMM OUTDATA, R4
        DATA R1, 12
        NEG R1
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'k'                ; ++, one operand
        COMM OUTDATA, R4
        DATA R1, 12
        ++ R1
        DATA R2, 12
        CMP R1, R2
        CALL expect_z

        DATA R4, 'l'                ; FMULT immediate
        COMM OUTDATA, R4
        DATA R1, 3.0
        FMULT R1, #2.0
        DATA R2, 3.0
        CMP R1, R2
        CALL expect_z

        DATA R4, 'm'                ; FADD, register form
        COMM OUTDATA, R4
        DATA R1, 3.0
        DATA R2, 2.0
        FADD R1, R2
        DATA R2, 3.0
        CMP R1, R2
        CALL expect_z

        DATA R4, 'o'                ; does a register-form op write RB?
        COMM OUTDATA, R4
        DATA R1, 12
        DATA R2, 5
        ADD R1, R2
        DATA R1, 5
        CMP R2, R1
        CALL expect_z

        DATA R4, 'n'                ; the digit loop: 12 % 10 then 12 / 10
        COMM OUTDATA, R4
        DATA R1, 12
        MOD R1, #10                 ; R0 = 2, R1 must stay 12
        DIV R1, #10                 ; R0 = 1 if R1 is still 12
        CPY R0, R5
        DATA R2, 1
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
