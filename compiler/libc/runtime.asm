; ==================================================================
; runtime.asm - helpers that code from the C compiler calls
;
;   _pow2           table: _pow2 + n holds 2^n (n = 0..31), for shifts
;                   by a variable count
;   _udiv           R0 = R15 / R13, unsigned
;   _umod           R0 = R15 % R13, unsigned
;                   (call them with  DATA R14, back / RJMP _udiv ; back:
;                   they return with JMRB R14 and change only R0, R13,
;                   R14, R15 and the flags)
;   _Exit(status)   C's _Exit: stop the CPU with R0 = status; RESUME
;                   stops it again
;
; Part of the C library: the C compiler's build command links it in when
; a program needs it.
; ==================================================================

        .global _pow2, _udiv, _umod, _Exit

_pow2:
        .word 1, 2, 4, 8, 16, 32, 64, 128
        .word 256, 512, 1024, 2048, 4096, 8192, 16384, 32768
        .word 0x10000, 0x20000, 0x40000, 0x80000, 0x100000, 0x200000, 0x400000, 0x800000
        .word 0x1000000, 0x2000000, 0x4000000, 0x8000000, 0x10000000, 0x20000000, 0x40000000, 0x80000000

; ------------------------------------------------------------------
; unsigned division. The CPU's DIV and MOD are signed, so:
;   d >= 2^31:            the quotient is 0 or 1
;   n, d < 2^31:          DIV / MOD give the right answer
;   n >= 2^31, d < 2^31:  q = ((n >> 1) / d) * 2 is at most 1 too small;
;                         r = n - q*d < 2d, so one correction step is enough
; ------------------------------------------------------------------
_udiv:
        TEST R13
        RJF N, udv_big_d
        TEST R15
        RJF N, udv_big_n
        DIV R15, R13
        JMRB R14
udv_big_d:
        SUB R15, R13                ; C = borrow: n < d
        DATA R0, 0
        RJF C, udv_done
        DATA R0, 1
udv_done:
        JMRB R14
udv_big_n:                    ; q = ((n >> 1) / d) * 2, then one correction
        CPY R1, R0
        STK PUSH
        CPY R2, R0
        STK PUSH
        SHR R15                     ; R0 = n >> 1
        DIV R0, R13
        ADD R0, R0
        CPY R0, R1                  ; R1 = q
        MULT R1, R13
        CPY R0, R2
        SUB R15, R2
        CPY R0, R2                  ; R2 = r = n - q*d, 0 <= r < 2d
        SUB R2, R13                 ; R0 = r - d, C = borrow: r < d
        RJF C, udv_fixed
        CPY R0, R2                  ; r -= d
        ++ R1
        CPY R0, R1                  ; q += 1
udv_fixed:
        CPY R1, R15
        STK POP
        CPY R0, R2
        STK POP
        CPY R0, R1
        CPY R15, R0
        JMRB R14

_umod:
        TEST R13
        RJF N, umd_big_d
        TEST R15
        RJF N, umd_big_n
        MOD R15, R13
        JMRB R14
umd_big_d:
        SUB R15, R13                ; R0 = n - d, C = borrow: n < d
        RJNF C, umd_done
        CPY R15, R0                 ; n < d: the remainder is n
umd_done:
        JMRB R14
umd_big_n:                    ; q = ((n >> 1) / d) * 2, then one correction
        CPY R1, R0
        STK PUSH
        CPY R2, R0
        STK PUSH
        SHR R15                     ; R0 = n >> 1
        DIV R0, R13
        ADD R0, R0
        CPY R0, R1                  ; R1 = q
        MULT R1, R13
        CPY R0, R2
        SUB R15, R2
        CPY R0, R2                  ; R2 = r = n - q*d, 0 <= r < 2d
        SUB R2, R13                 ; R0 = r - d, C = borrow: r < d
        RJF C, umd_fixed
        CPY R0, R2                  ; r -= d
        ++ R1
        CPY R0, R1                  ; q += 1
umd_fixed:
        CPY R2, R15
        STK POP
        CPY R0, R2
        STK POP
        CPY R0, R1
        CPY R15, R0
        JMRB R14

; ------------------------------------------------------------------
; _Exit(status): stop with R0 = status
; ------------------------------------------------------------------
_Exit:
        DATA R1, -2
        STK GET, R1
_Exit_halt:
        HALT
        RJMP _Exit_halt
