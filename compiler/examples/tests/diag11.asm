; ==================================================================
; diag11.asm - three behaviours never measured, plus INT once more
;
; From the project root:
;   python compiler/src/asm build compiler/examples/tests/diag11.asm
;          compiler/examples/stdlib/stdlib.asm
;   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/diag11.rom --jar <logisim jar>
;
; diag11.asm must come FIRST on the command line: its results then sit in
; RAM from 0x14000, ready for a RAM dump. They are also printed, one hex
; word per line, in the same order.
;
; line RAM      what                              truncating   other
;                                                 / as ISA     outcome
; ---- C: STK SET/GET with a negative index while EBP = 0
;  1  0x14000  SET at ebp-1, then LD 0x13FFF      CAFE0001    anything else: the
;              (the slot it should wrap to)                    sum didn't wrap there
;              MEASURED on the circuit: the write lands on 0x1FFFF (the last
;              RAM word): the sum wraps across all of RAM, not at 14 bits
;  2  0x14001  GET at ebp-1                       CAFE0001
; ---- B: does STK GET also write RB?
;  3  0x14002  R0 after GET index 0               1234ABCD
;  4  0x14003  R1 (the index) after that GET      00000000    1234ABCD: GET wrote RB
;  5  0x14004  R1 after GET -2 inside a call      FFFFFFFE    00005678: GET wrote RB
; ---- A: INT, positive and negative             truncates   rounds, ties away
;  6  0x14005  INT(0.5)                           00000000    00000001
;  7  0x14006  INT(1.5)                           00000001    00000002
;  8  0x14007  INT(2.5)                           00000002    00000003
;  9  0x14008  INT(1.7)                           00000001    00000002
; 10  0x14009  INT(0.4)                           00000000    00000000
; 11  0x1400A  INT(-0.4)                          00000000    00000000
; 12  0x1400B  INT(-0.5)                          00000000    FFFFFFFF
; 13  0x1400C  INT(-0.6)                          00000000    FFFFFFFF
; 14  0x1400D  INT(-1.5)                          FFFFFFFF    FFFFFFFE
; 15  0x1400E  INT(-2.5)                          FFFFFFFE    FFFFFFFD
; 16  0x1400F  INT(-3.7)                          FFFFFFFD    FFFFFFFC
;
; After the 16 lines the program halts with ESP = EBP = 0.
; ==================================================================

        .extern print_hex, print_newline
        .global start

        .equ COUNT, 16
        .equ INT_TESTS, 11

        .ram
results:    .space COUNT

        .rom
start:
        DATA R9, results            ; R9 = results
        DATA R10, 0                 ; R10 = how many stored

; ---- C: negative index, EBP = 0 (nothing has been called yet)
        DATA R0, 0xCAFE0001
        DATA R1, -1
        STK SET, R1                 ; stack[ebp - 1] = R0
        DATA R2, 0x13FFF
        LD R2, R3                   ; R3 = the top stack slot, read as RAM
        CPY R3, R0
        AST R9, R10                 ; result 1
        ++ R10
        CPY R0, R10
        DATA R1, -1
        DATA R0, 0
        STK GET, R1                 ; R0 = stack[ebp - 1]
        AST R9, R10                 ; result 2
        ++ R10
        CPY R0, R10

; ---- B: does STK GET write RB as well as R0?
        DATA R0, 0x1234ABCD
        STK PUSH                    ; stack[0] = 0x1234ABCD
        DATA R1, 0                  ; index 0 = ebp + 0
        DATA R0, 0
        STK GET, R1                 ; R0 = stack[0]
        CPY R1, R5                  ; R5 = R1 afterwards (before R0 is reused)
        AST R9, R10                 ; result 3: R0
        ++ R10
        CPY R0, R10
        CPY R5, R0
        AST R9, R10                 ; result 4: R1
        ++ R10
        CPY R0, R10
        STK POP                     ; ESP back to 0

        DATA R0, 0x5678             ; the case seen once: GET of an argument
        STK PUSH
        CALL get_arg, 1             ; R0 = what R1 held after the GET
        AST R9, R10                 ; result 5
        ++ R10
        CPY R0, R10

; ---- A: INT of each value in int_inputs
        DATA R7, int_inputs
        DATA R8, 0
a_loop:
        ALD R7, R8                  ; R0 = next input (reading ROM works)
        CPY R0, R1
        INT R1
        AST R9, R10                 ; results 6 .. 16
        ++ R10
        CPY R0, R10
        ++ R8
        CPY R0, R8
        CMP R8, #INT_TESTS
        RJNF Z, a_loop

; ---- print every result, one hex word per line
        DATA R8, 0
p_loop:
        SAVE R8, R9
        ALD R9, R8                  ; R0 = results[i]
        STK PUSH
        CALL print_hex, 1
        CALL print_newline
        RESTORE R8, R9
        ++ R8
        CPY R0, R8
        CMP R8, #COUNT
        RJNF Z, p_loop
        HALT

; get_arg(x): read x the way every stdlib function does, then return R1
get_arg:
        DATA R1, -2
        STK GET, R1                 ; R0 = x; R1 should still be -2
        CPY R1, R0
        RET

int_inputs: .word 0.5, 1.5, 2.5, 1.7, 0.4, -0.4, -0.5, -0.6, -1.5, -2.5, -3.7
