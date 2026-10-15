; ==================================================================
; setjmp.asm - setjmp and longjmp (setjmp.h), part of the C library
;
; jmp_buf holds three words:
;   [0]  E, setjmp's frame (its EBP)
;   [1]  the caller's EBP (stack[E])
;   [2]  setjmp's return address (stack[E-1])
; A normal return from setjmp leaves ESP = E - 1 before the caller drops
; the argument. longjmp rebuilds exactly that: ESP = E - 1, EBP = the
; caller's, then jumps to the return address with R0 = val (1 if val is 0).
; ESP and EBP can't be written directly; two STK RETs set them:
;   stack[EBP] = Y; STK RET  ->  ESP = EBP, EBP = Y
;   stack[Y]   = V; STK RET  ->  ESP = Y,   EBP = V
; (measured on the circuit with compiler/examples/tests/diag12.asm)
; ==================================================================

        .global setjmp, longjmp

; int setjmp(jmp_buf env)
setjmp:
        DATA R1, -2
        STK GET, R1
        CPY R0, R2                  ; R2 = env
        STK CALL                    ; read EBP: R0 = E
        DATA R1, 0
        STK GET, R1
        STK RET
        AST R2, R1                  ; env[0] = E
        STK GET, R1                 ; R0 = stack[E] = the caller's EBP
        DATA R1, 1
        AST R2, R1                  ; env[1]
        DATA R1, -1
        STK GET, R1                 ; R0 = the return address
        DATA R1, 2
        AST R2, R1                  ; env[2]
        DATA R0, 0
        RET

; void longjmp(jmp_buf env, int val)
longjmp:
        DATA R1, -3
        STK GET, R1
        CPY R0, R2                  ; R2 = env
        DATA R1, -2
        STK GET, R1
        CPY R0, R3                  ; R3 = val
        TEST R3
        RJNF Z, lj_value
        DATA R3, 1                  ; longjmp(env, 0) makes setjmp return 1
lj_value:
        DATA R1, 0
        ALD R2, R1
        -- R0                       ; R0 = Y = E - 1
        STK SET, R1                 ; stack[EBP] = Y
        STK RET                     ; ESP = EBP, EBP = Y
        DATA R1, 1
        ALD R2, R1                  ; R0 = V = the caller's EBP
        DATA R1, 0
        STK SET, R1                 ; stack[Y] = V
        STK RET                     ; ESP = Y, EBP = V
        DATA R1, 2
        ALD R2, R1
        CPY R0, R4                  ; R4 = the return address
        CPY R3, R0                  ; R0 = val
        JMRB R4
