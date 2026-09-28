; diag6.asm - prints raw results in hex instead of pass/fail
;
; print_hex is the one thing that has worked reliably all along, so this
; asks the circuit what each instruction actually produces rather than
; whether it matches. Nothing here depends on a flag being right.
;
;   python compiler/src/asm build diag6.asm stdlib.asm -o diag6.rom
;
; Each line is:  <what ran>  CANZ  0x<result>
;
; For the one-operand instructions (NEG, INT, FLOAT, FNEG) only N and Z
; mean anything - A compares the unused RA field, so ignore C and A there.
; CANZ are the four flags the instruction left, as 0 or 1, printed with
; jumps only (no ALU), so reading them cannot disturb them.
;
; Expected on a correct CPU:
;
;   ADD -2,#1     0010 0xFFFFFFFF
;   SUB 3,#4      1010 0xFFFFFFFF
;   ADD -2,R2=1   0010 0xFFFFFFFF
;   MULT -1,#1    1010 0xFFFFFFFF
;   NEG R0=-8     1000 0x00000008    <- NEG where the operand IS R0
;   NEG R1=-8     0100 0x00000008
;   INT 5.0       0000 0x00000005
;   INT 1.5       0000 0x00000001    (0x00000002 if it rounds - either is fine)
;   INT 3.14159   0000 0x00000003
;   INT 100.0     0000 0x00000064
;   FLOAT 7       0000 0x40E00000
;   FLOAT 3       0000 0x40400000
;   FADD 1.0,2.0  0000 0x40400000
;   FSUB 3.0,3.0  0001 0x00000000    <- Z must be ON
;   FSUB -1.0,4.0 0010 0xC0A00000    <- N must be ON
;   FSUB 3.14,3.0 1100 0x3E10FD00    <- N must be OFF: this is the one
;                                       print_float depends on
;   FMULT 2.5,10  0000 0x41C80000
;   FDIV 5.0,2.0  0100 0x40200000
;   FNEG 1.5      0010 0xBFC00000
;   str_to_int    0010 0xFFFFFEBF    (-321; the flags here are meaningless)
;   that +1       0010 0xFFFFFEC0    (-320)
;
; The last hex digits of FSUB 3.14,3.0 may differ by a bit or two - my
; rounding may not match the circuit's. Everything else is exact.
;
; The C flag on subtraction is "no borrow" in the notes, so 0 above may
; read as 1 on your circuit - that difference is not a fault, nothing in
; the library uses C.

        .extern print_string, print_hex, print_newline, str_to_int
        .global start

        .rom
start:
        DATA R6, 0x5C
        COMM OUTADDR, R6

; ---- integer immediates, negative results
        DATA R0, l_addi
        STK PUSH
        CALL print_string, 1
        DATA R1, -2
        ADD R1, #1
        CPY R0, R5
        CALL report

        DATA R0, l_subi
        STK PUSH
        CALL print_string, 1
        DATA R1, 3
        SUB R1, #4
        CPY R0, R5
        CALL report

        DATA R0, l_addr
        STK PUSH
        CALL print_string, 1
        DATA R1, -2
        DATA R2, 1
        ADD R1, R2
        CPY R0, R5
        CALL report

        DATA R0, l_multi
        STK PUSH
        CALL print_string, 1
        DATA R1, -1
        MULT R1, #1
        CPY R0, R5
        CALL report

; ---- NEG, once with R0 as the operand and once with R1
        DATA R0, l_neg0
        STK PUSH
        CALL print_string, 1
        DATA R0, -8
        NEG R0
        CPY R0, R5
        CALL report

        DATA R0, l_neg1
        STK PUSH
        CALL print_string, 1
        DATA R1, -8
        NEG R1
        CPY R0, R5
        CALL report

; ---- float to int
        DATA R0, l_int5
        STK PUSH
        CALL print_string, 1
        DATA R1, 5.0
        INT R1
        CPY R0, R5
        CALL report

        DATA R0, l_int15
        STK PUSH
        CALL print_string, 1
        DATA R1, 1.5
        INT R1
        CPY R0, R5
        CALL report

        DATA R0, l_int314
        STK PUSH
        CALL print_string, 1
        DATA R1, 3.14159
        INT R1
        CPY R0, R5
        CALL report

        DATA R0, l_int100
        STK PUSH
        CALL print_string, 1
        DATA R1, 100.0
        INT R1
        CPY R0, R5
        CALL report

; ---- int to float
        DATA R0, l_flt7
        STK PUSH
        CALL print_string, 1
        DATA R1, 7
        FLOAT R1
        CPY R0, R5
        CALL report

        DATA R0, l_flt3
        STK PUSH
        CALL print_string, 1
        DATA R1, 3
        FLOAT R1
        CPY R0, R5
        CALL report

; ---- float arithmetic
        DATA R0, l_fadd
        STK PUSH
        CALL print_string, 1
        DATA R1, 1.0
        FADD R1, #2.0
        CPY R0, R5
        CALL report

        DATA R0, l_fsub0
        STK PUSH
        CALL print_string, 1
        DATA R1, 3.0
        FSUB R1, #3.0
        CPY R0, R5
        CALL report

        DATA R0, l_fsubn
        STK PUSH
        CALL print_string, 1
        DATA R1, -1.0
        FSUB R1, #4.0
        CPY R0, R5
        CALL report

        DATA R0, l_fsubp
        STK PUSH
        CALL print_string, 1
        DATA R1, 3.14159
        FSUB R1, #3.0
        CPY R0, R5
        CALL report

        DATA R0, l_fmult
        STK PUSH
        CALL print_string, 1
        DATA R1, 2.5
        FMULT R1, #10.0
        CPY R0, R5
        CALL report

        DATA R0, l_fdiv
        STK PUSH
        CALL print_string, 1
        DATA R1, 5.0
        FDIV R1, #2.0
        CPY R0, R5
        CALL report

        DATA R0, l_fneg
        STK PUSH
        CALL print_string, 1
        DATA R1, 1.5
        FNEG R1
        CPY R0, R5
        CALL report

; ---- the conv line: what str_to_int gives, and what +1 gives
        DATA R0, l_sti
        STK PUSH
        CALL print_string, 1
        DATA R0, minus321
        STK PUSH
        CALL str_to_int, 1
        CPY R0, R5
        CALL report

        DATA R0, l_sti1
        STK PUSH
        CALL print_string, 1
        DATA R0, minus321
        STK PUSH
        CALL str_to_int, 1
        ADD R0, #1
        CPY R0, R5
        CALL report

        HALT

; report(): the caller puts the value in R5 (CPY leaves the flags alone)
; and CALL itself only changes R0, so the flags arrive here intact.
report:
        DATA R6, 0x5C
        COMM OUTADDR, R6
        DATA R6, '0'                ; C
        RJNF C, rp_c
        DATA R6, '1'
rp_c:   COMM OUTDATA, R6
        DATA R6, '0'                ; A
        RJNF A, rp_a
        DATA R6, '1'
rp_a:   COMM OUTDATA, R6
        DATA R6, '0'                ; N
        RJNF N, rp_n
        DATA R6, '1'
rp_n:   COMM OUTDATA, R6
        DATA R6, '0'                ; Z
        RJNF Z, rp_z
        DATA R6, '1'
rp_z:   COMM OUTDATA, R6
        DATA R6, ' '
        COMM OUTDATA, R6
        CPY R5, R0                  ; flags are printed, R0 is free now
        STK PUSH
        CALL print_hex, 1
        CALL print_newline
        RET

l_addi:     .string "ADD -2,#1     "
l_subi:     .string "SUB 3,#4      "
l_addr:     .string "ADD -2,R2=1   "
l_multi:    .string "MULT -1,#1    "
l_neg0:     .string "NEG R0=-8     "
l_neg1:     .string "NEG R1=-8     "
l_int5:     .string "INT 5.0       "
l_int15:    .string "INT 1.5       "
l_int314:   .string "INT 3.14159   "
l_int100:   .string "INT 100.0     "
l_flt7:     .string "FLOAT 7       "
l_flt3:     .string "FLOAT 3       "
l_fadd:     .string "FADD 1.0,2.0  "
l_fsub0:    .string "FSUB 3.0,3.0  "
l_fsubn:    .string "FSUB -1.0,4.0 "
l_fsubp:    .string "FSUB 3.14,3.0 "
l_fmult:    .string "FMULT 2.5,10  "
l_fdiv:     .string "FDIV 5.0,2.0  "
l_fneg:     .string "FNEG 1.5      "
l_sti:      .string "str_to_int    "
l_sti1:     .string "that +1       "
minus321:   .string "-321"
