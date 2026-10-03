; A small library: two functions other files can CALL.

        .equ DISPLAY, 0x5C
        .global print_newline, print_dashes

; print_newline: sends a newline to the display.
print_newline:
        DATA R1, DISPLAY
        COMM OUTADDR, R1
        DATA R1, '\n'
        COMM OUTDATA, R1
        RET

; print_dashes: prints "-----" and a newline. Returns 5 in R0.
print_dashes:
        DATA R1, DISPLAY
        COMM OUTADDR, R1
        DATA R1, '-'
        DATA R2, 5              ; dashes left
dash:   COMM OUTDATA, R1
        -- R2
        CPY R0, R2
        RJNF Z, dash
        CALL print_newline      ; a call from inside a call
        DATA R0, 5              ; return value
        RET
