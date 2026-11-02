; ==================================================================
; spawn.asm - the jumps into and out of a program run by spawnv()
; (spawn.c), part of the C library
;
;   _spawn_jump(entry, block)   jump to entry with R1 = block; never returns
;   _spawn_return               the program's _Exit jumps here with
;                               R0 = its status, on the program's stack:
;                               saves the status, then longjmp(_spawn_back, 1)
;                               puts back the stack spawnv() had
; ==================================================================

        .global _spawn_jump, _spawn_return, _spawn_kill
        .extern _spawn_back, _spawn_status, longjmp

_spawn_jump:
        DATA R1, -3
        STK GET, R1
        CPY R0, R2                  ; R2 = entry
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = block
        JMRB R2

; Killed: an NMI handler returns this address instead of the program's
; (RTI jumps here, with the interrupt state already restored), and the
; program ends with status 130 (128 + 2, as a shell shows an interrupted one).
_spawn_kill:
        DATA R0, 130
        DATA R1, _spawn_return
        JMRB R1

_spawn_return:
        DATA R1, _spawn_status
        ST R1, R0                   ; _spawn_status = R0
        DATA R0, _spawn_back
        STK PUSH
        DATA R0, 1
        STK PUSH
        CALL longjmp, 2
