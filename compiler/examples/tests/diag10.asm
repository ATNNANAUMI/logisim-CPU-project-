; diag10.asm - what INT does with values below 1
;
; Every remaining wrong float in the demo comes from INT being handed a
; value smaller than 1, and nothing has ever tested that. diag6 tested INT
; at 1.5 and up, and diag8's trace only fed it 1.41, 1.63, 4.16 and 6.39 -
; all >= 1, all correct. print_float feeds it 0.5, 0.05, 0.005, 0.0005 and
; 0.00005, and those are exactly the cases that come out wrong.
;
;   python compiler/src/asm build diag10.asm stdlib.asm -o diag10.rom
;
; Each line: <letter> CANZ 0x<result of INT>
;
;   letter  input       exponent   expected (INT truncates)
;   a       3.14159        1        0x00000003
;   b       1.5            0        0x00000001
;   c       1.0            0        0x00000001
;   d       0.9           -1        0x00000000
;   e       0.5           -1        0x00000000
;   f       0.50005       -1        0x00000000
;   g       0.25          -2        0x00000000
;   h       0.1           -4        0x00000000
;   i       0.05          -5        0x00000000
;   j       0.005         -8        0x00000000
;   k       0.0005       -11        0x00000000
;   m       0.00005      -15        0x00000000
;   n       0.0         (zero)      0x00000000
;
; a b c are the controls and are known to work. Everything from d down
; should be 0x00000000 and Z should be 1.
;
; What a non-zero answer means: converting needs the mantissa shifted right
; by (23 - exponent), which for a value below 1 is 24 or more. If the
; shifter is five bits wide, or rotates instead of shifting, that count
; wraps and the mantissa survives in the result instead of being shifted
; away. The -0.5 case already looks like this: print_float's whole part
; came back as 0x80034600, and the mantissa of 0.50005 with its implicit
; leading 1 is 0x800347 - the same bits, sitting high in the word instead
; of shifted out. If that is the fault, d to m come back holding pieces of
; their own mantissa, and the fix is to force the result to 0 whenever the
; unbiased exponent is negative.

        .extern print_hex, print_newline
        .global start

        .rom
start:
        DATA R13, 0x5C
        COMM OUTADDR, R13

        DATA R7, 3.14159            ; a: control
        INT R7
        CPY R0, R5
        DATA R6, 'a'
        CALL rep

        DATA R7, 1.5                ; b: control
        INT R7
        CPY R0, R5
        DATA R6, 'b'
        CALL rep

        DATA R7, 1.0                ; c: control
        INT R7
        CPY R0, R5
        DATA R6, 'c'
        CALL rep

        DATA R7, 0.9                ; d: first one below 1
        INT R7
        CPY R0, R5
        DATA R6, 'd'
        CALL rep

        DATA R7, 0.5                ; e
        INT R7
        CPY R0, R5
        DATA R6, 'e'
        CALL rep

        DATA R7, 0.50005            ; f: the one print_float chokes on
        INT R7
        CPY R0, R5
        DATA R6, 'f'
        CALL rep

        DATA R7, 0.25               ; g
        INT R7
        CPY R0, R5
        DATA R6, 'g'
        CALL rep

        DATA R7, 0.1                ; h
        INT R7
        CPY R0, R5
        DATA R6, 'h'
        CALL rep

        DATA R7, 0.05               ; i
        INT R7
        CPY R0, R5
        DATA R6, 'i'
        CALL rep

        DATA R7, 0.005              ; j
        INT R7
        CPY R0, R5
        DATA R6, 'j'
        CALL rep

        DATA R7, 0.0005             ; k
        INT R7
        CPY R0, R5
        DATA R6, 'k'
        CALL rep

        DATA R7, 0.00005            ; m
        INT R7
        CPY R0, R5
        DATA R6, 'm'
        CALL rep

        DATA R7, 0.0                ; n: zero
        INT R7
        CPY R0, R5
        DATA R6, 'n'
        CALL rep

        HALT

; rep(): prints the letter in R6, the four flags, then R5 in hex.
; Only DATA, CPY, COMM and jumps run before the flags are out, and none of
; those touch the flags, so what it prints is what INT left.
rep:
        DATA R13, 0x5C
        COMM OUTADDR, R13
        COMM OUTDATA, R6
        DATA R13, ' '
        COMM OUTDATA, R13
        DATA R13, '0'
        RJNF C, r_c
        DATA R13, '1'
r_c:    COMM OUTDATA, R13
        DATA R13, '0'
        RJNF A, r_a
        DATA R13, '1'
r_a:    COMM OUTDATA, R13
        DATA R13, '0'
        RJNF N, r_n
        DATA R13, '1'
r_n:    COMM OUTDATA, R13
        DATA R13, '0'
        RJNF Z, r_z
        DATA R13, '1'
r_z:    COMM OUTDATA, R13
        DATA R13, ' '
        COMM OUTDATA, R13
        CPY R5, R0
        STK PUSH
        CALL print_hex, 1
        CALL print_newline
        RET
