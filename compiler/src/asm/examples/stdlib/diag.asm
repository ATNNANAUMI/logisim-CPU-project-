; diag.asm - checks, one at a time, the hardware behaviours the stdlib uses
;
; python compiler/src/asm build diag.asm stdlib.asm -o diag.rom
;
; Prints "aP bP ... pP", then 5, 12 and -1234 on separate lines.
; A failing test prints F instead of P.
;   a  -1234 / 10  = -123        DIV, negative
;   b  -1234 % 10  = -4          MOD, negative
;   c  -1 / 10     = 0
;   d  50 / 10     = 5           DIV, positive
;   e  CMP 3, 2    sets A
;   f  CMP 2, 3    clears A
;   g  CMP -1, 2   clears A      (A is signed)
;   h  CMP 0, 5    RJF AZ does not jump   (mem_set / mem_copy loop start)
;   i  Z from DIV survives a CPY and a DATA
;   j  nested call, 2 args       (GET at ebp-3 / ebp-2)
;   k  call with 3 args          (GET at ebp-4, used by mem_set)
;   l  5 + 3 with ADD R0, #3     (immediate op where RA is R0)
;   m  FSUB -1.0, 4.0 sets N     (float ops set flags)
;   n  FMULT 2.5, #10.0 = 25.0   (float immediate)
;   o  INT 5.0     = 5
;   p  FLOAT 7     = 7.0
; Every check compares with CMP R5, ... so it never relies on test l.

        .extern print_int, print_newline
        .global start

start:
        DATA R1, 0x5C
        COMM OUTADDR, R1

        DATA R1, 'a'                ; -1234 / 10 = -123
        COMM OUTDATA, R1
        DATA R1, -1234
        DIV R1, #10
        CPY R0, R5
        CMP R5, #-123
        CALL expect_z

        DATA R1, 'b'                ; -1234 % 10 = -4
        COMM OUTDATA, R1
        DATA R1, -1234
        MOD R1, #10
        CPY R0, R5
        CMP R5, #-4
        CALL expect_z

        DATA R1, 'c'                ; -1 / 10 = 0
        COMM OUTDATA, R1
        DATA R1, -1
        DIV R1, #10
        CPY R0, R5
        CMP R5, #0
        CALL expect_z

        DATA R1, 'd'                ; 50 / 10 = 5
        COMM OUTDATA, R1
        DATA R1, 50
        DIV R1, #10
        CPY R0, R5
        CMP R5, #5
        CALL expect_z

        DATA R1, 'e'                ; CMP 3, 2 sets A
        COMM OUTDATA, R1
        DATA R1, 3
        DATA R2, 2
        CMP R1, R2
        CALL expect_a

        DATA R1, 'f'                ; CMP 2, 3 clears A
        COMM OUTDATA, R1
        DATA R1, 2
        DATA R2, 3
        CMP R1, R2
        CALL expect_not_a

        DATA R1, 'g'                ; CMP -1, 2 clears A
        COMM OUTDATA, R1
        DATA R1, -1
        DATA R2, 2
        CMP R1, R2
        CALL expect_not_a

        DATA R1, 'h'                ; CMP 0, 5: RJF AZ must not jump
        COMM OUTDATA, R1
        DATA R1, 0
        DATA R2, 5
        CMP R1, R2
        CALL expect_not_az

        DATA R1, 'i'                ; Z survives CPY and DATA
        COMM OUTDATA, R1
        DATA R1, 5
        DIV R1, #10                 ; 0 -> Z on
        CPY R0, R2
        DATA R3, 7
        CALL expect_z

        DATA R1, 'j'                ; outer(10) = sub2(10, 3) = 7
        COMM OUTDATA, R1
        DATA R0, 10
        STK PUSH
        CALL outer, 1
        CPY R0, R5
        CMP R5, #7
        CALL expect_z

        DATA R1, 'k'                ; first3(11, 22, 33) = 11
        COMM OUTDATA, R1
        DATA R0, 11
        STK PUSH
        DATA R0, 22
        STK PUSH
        DATA R0, 33
        STK PUSH
        CALL first3, 3
        CPY R0, R5
        CMP R5, #11
        CALL expect_z

        DATA R1, 'l'                ; ADD R0, #3 with R0 = 5
        COMM OUTDATA, R1
        DATA R0, 5
        ADD R0, #3
        CPY R0, R5
        CMP R5, #8
        CALL expect_z

        DATA R1, 'm'                ; FSUB -1.0, 4.0 sets N
        COMM OUTDATA, R1
        DATA R1, -1.0
        DATA R2, 4.0
        FSUB R1, R2
        CALL expect_n

        DATA R1, 'n'                ; FMULT 2.5, #10.0 = 25.0
        COMM OUTDATA, R1
        DATA R1, 2.5
        FMULT R1, #10.0
        CPY R0, R5
        DATA R6, 25.0
        CMP R5, R6                  ; same bits?
        CALL expect_z

        DATA R1, 'o'                ; INT 5.0 = 5
        COMM OUTDATA, R1
        DATA R1, 5.0
        INT R1
        CPY R0, R5
        CMP R5, #5
        CALL expect_z

        DATA R1, 'p'                ; FLOAT 7 = 7.0
        COMM OUTDATA, R1
        DATA R1, 7
        FLOAT R1
        CPY R0, R5
        DATA R6, 7.0
        CMP R5, R6
        CALL expect_z
        CALL print_newline

        DATA R0, 5                  ; one digit
        STK PUSH
        CALL print_int, 1
        CALL print_newline
        DATA R0, 12                 ; two digits
        STK PUSH
        CALL print_int, 1
        CALL print_newline
        DATA R0, -1234
        STK PUSH
        CALL print_int, 1
        CALL print_newline
        HALT

; outer(x): returns sub2(x, 3)
outer:
        DATA R1, -2
        STK GET, R1
        STK PUSH
        DATA R0, 3
        STK PUSH
        CALL sub2, 2
        RET

; sub2(a, b): returns a - b
sub2:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1
        DATA R2, -2
        STK GET, R2
        SUB R1, R0
        RET

; first3(a, b, c): returns a
first3:
        DATA R1, -4
        STK GET, R1
        RET

; CALL doesn't touch the flags, so these see the test's flags.
expect_z:
        RJF Z, pass
        RJMP fail
expect_a:
        RJF A, pass
        RJMP fail
expect_n:
        RJF N, pass
        RJMP fail
expect_not_az:
        RJF AZ, fail
        RJMP pass
expect_not_a:
        RJNF A, pass
fail:
        DATA R1, 'F'
        COMM OUTDATA, R1
        RJMP gap
pass:
        DATA R1, 'P'
        COMM OUTDATA, R1
gap:
        DATA R1, ' '
        COMM OUTDATA, R1
        RET
