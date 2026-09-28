; stack_test.asm - push 2 args, call a function, return, check the result
; expected output: 4!   (then a newline)
;   '4' = 7 - 3, so both args were read, in the right order
;         (if the order were swapped you'd see ',' = '0' - 4)
;   '!' = R2 survived the call via SAVE / RESTORE (stack is balanced)

        .equ DISPLAY, 0x5C
        .global start

start:  DATA R1, DISPLAY
        COMM OUTADDR, R1

        DATA R2, '!'        ; value that must survive the call
        SAVE R2

        DATA R0, 7          ; arg1 = a
        STK PUSH
        DATA R0, 3          ; arg2 = b
        STK PUSH
        CALL sub2, 2        ; R0 = a - b, then drop the 2 args

        RESTORE R2          ; R2 back, R0 still holds the result

        ADD R0, #'0'        ; number -> ASCII digit
        COMM OUTDATA, R0    ; prints '4'
        COMM OUTDATA, R2    ; prints '!'
        DATA R3, '\n'
        COMM OUTDATA, R3
        HALT

; sub2(a, b): returns a - b
; frame: ebp-3 = a, ebp-2 = b, ebp-1 = return address, ebp+0 = old ebp
sub2:   DATA R1, -3
        STK GET R1          ; R0 = a
        CPY R0, R4
        DATA R1, -2
        STK GET R1          ; R0 = b
        CPY R0, R5
        SUB R4, R5          ; R0 = a - b
        RET
