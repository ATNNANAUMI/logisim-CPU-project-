; stack_reverse.asm - print a word backwards, using the stack
;
; python compiler/src/asm build compiler/examples/programs/stack_reverse.asm
; Expected display: kcats
; The stack ends where it started (ESP = 0).

        .equ DISPLAY, 0x5C
        .global start

start:  DATA R1, word           ; R1 = address of the text
        DATA R2, 0              ; R2 = how many pushed
push:   ALD R1, R2              ; R0 = next character
        TEST R0
        RJF Z, popping          ; the 0 at the end
        STK PUSH                ; onto the stack
        ++ R2
        CPY R0, R2
        RJMP push

popping:
        DATA R3, DISPLAY
        COMM OUTADDR, R3
pop:    TEST R2
        RJF Z, done             ; all popped
        STK POP                 ; last pushed comes off first
        COMM OUTDATA, R0
        -- R2
        CPY R0, R2
        RJMP pop
done:   HALT

word:   .string "stack"
