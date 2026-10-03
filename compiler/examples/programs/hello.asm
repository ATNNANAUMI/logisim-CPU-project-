; hello.asm - print a string stored in ROM
;
; python compiler/src/asm build compiler/src/asm/examples/programs/hello.asm
; Expected display: hello, world

        .equ DISPLAY, 0x5C
        .global start

start:  DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R1, message        ; R1 = address of the text
        DATA R2, 0              ; R2 = index
loop:   ALD R1, R2              ; R0 = next character (reading ROM works)
        TEST R0
        RJF Z, done             ; the 0 at the end
        COMM OUTDATA, R0
        ++ R2
        CPY R0, R2
        RJMP loop
done:   HALT

message: .string "hello, world\n"
