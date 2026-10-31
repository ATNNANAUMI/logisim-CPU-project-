; ==================================================================
; memory.asm - memcpy and memset (string.h), part of the C library
;
; In assembly because the compiled loops took 13 and 9 instructions a
; word; these take 6. Arguments are read from the frame like the compiled
; functions do (the last one at EBP - 2). The counter is compared as an
; unsigned number (SUB sets C on a borrow). memmove and the rest of
; string.h are in string.c.
; ==================================================================

        .global memcpy, memset

; void *memcpy(void *dst, const void *src, size_t n)
memcpy:
        DATA R13, -4
        STK GET, R13
        CPY R0, R9                  ; R9 = dst (also the result)
        DATA R13, -3
        STK GET, R13
        CPY R0, R10                 ; R10 = src
        DATA R13, -2
        STK GET, R13
        CPY R0, R11                 ; R11 = n
        DATA R12, 0                 ; R12 = i
        RJMP mc_test
mc_loop:
        ALD R10, R12                ; R0 = src[i]
        AST R9, R12                 ; dst[i] = R0
        ++ R12
        CPY R0, R12
mc_test:
        SUB R12, R11                ; C: i < n
        RJF C, mc_loop
        CPY R9, R0
        RET

; void *memset(void *dst, int c, size_t n)
memset:
        DATA R13, -4
        STK GET, R13
        CPY R0, R9                  ; R9 = dst (also the result)
        DATA R13, -3
        STK GET, R13
        CPY R0, R10                 ; R10 = c
        DATA R13, -2
        STK GET, R13
        CPY R0, R11                 ; R11 = n
        DATA R12, 0                 ; R12 = i
        RJMP ms_test
ms_loop:
        CPY R10, R0
        AST R9, R12                 ; dst[i] = c
        ++ R12
        CPY R0, R12
ms_test:
        SUB R12, R11                ; C: i < n
        RJF C, ms_loop
        CPY R9, R0
        RET
