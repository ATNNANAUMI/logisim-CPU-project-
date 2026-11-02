; ==================================================================
; sys.asm - the system call of a program for Tynix (cc build --exe),
; part of its C library (compiler/libc/tynix/)
;
;   int _syscall(int n, int a, int b, int c, int d)
;       TRAP with R1 = n, R2..R5 = a..d; the kernel's answer is in R0
;       (sys/tynix.h lists the calls; a negative answer is -errno)
; ==================================================================

        .global _syscall

_syscall:
        DATA R1, -6
        STK GET, R1
        CPY R0, R6                  ; n
        DATA R1, -5
        STK GET, R1
        CPY R0, R2                  ; a
        DATA R1, -4
        STK GET, R1
        CPY R0, R3                  ; b
        DATA R1, -3
        STK GET, R1
        CPY R0, R4                  ; c
        DATA R1, -2
        STK GET, R1
        CPY R0, R5                  ; d
        CPY R6, R1
        TRAP
        RET
