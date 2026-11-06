; probe_addr.asm - does every address bit reach the RAM, and does RA + RB carry? (24-bit widening)
;
;   python compiler/src/asm build logisim/tests/probe_addr.asm compiler/examples/asm/stdlib/stdlib.asm
;
; Phase 1 writes a different value to seven RAM words, above the stack, whose addresses differ in bits 0, 8, 16, 20, 22 and 23
; Phase 2 reads them back. A bit that is not wired makes two
; addresses the same word: the earlier value is overwritten and the line shows the later one.
; Phase 3 stores through ALD/AST's adder (RA + RB) where the sum carries across bit 16
; and bit 20, and reads the word back by its plain address.
;
; Expected output, 9 lines:
;   A0000000 A0000001 A0000002 A0000003 A0000004 A0000005 A0000006   (phase 2, one per line)
;   00C0FFEE   (0x100FFFF + 1 stored, read at 0x1010000)
;   BEEF0002   (0x10FFFFF + 1 stored, read at 0x1100000)
        .extern print_hex, print_newline
        .global start
        .equ N, 7

        .rom
start:
        DATA R7, addrs
        DATA R6, vals
        DATA R5, 0
        DATA R8, 0
w_loop:
        ALD R7, R8
        CPY R0, R3                  ; R3 = address
        ALD R6, R8
        AST R3, R5                  ; mem[R3 + 0] = value
        ++ R8
        CPY R0, R8
        CMP R8, #N
        RJNF Z, w_loop

        DATA R8, 0
r_loop:
        ALD R7, R8
        CPY R0, R3
        ALD R3, R5                  ; R0 = mem[address]
        CPY R0, R1                  ; CALL clobbers R0
        CALL show
        ++ R8
        CPY R0, R8
        CMP R8, #N
        RJNF Z, r_loop

        DATA R3, 0x100FFFF
        DATA R4, 1
        DATA R0, 0xC0FFEE
        AST R3, R4                  ; address = 0x100FFFF + 1
        DATA R3, 0x1010000
        ALD R3, R5
        CPY R0, R1                  ; CALL clobbers R0
        CALL show

        DATA R3, 0x10FFFFF
        DATA R4, 1
        DATA R0, 0xBEEF0002
        AST R3, R4                  ; address = 0x10FFFFF + 1
        DATA R3, 0x1100000
        ALD R3, R5
        CPY R0, R1                  ; CALL clobbers R0
        CALL show
        HALT

show:                               ; prints R1 in hex and a newline; keeps R3..R8
        SAVE R3, R8
        CPY R1, R0
        STK PUSH
        CALL print_hex, 1
        CALL print_newline
        RESTORE R3, R8
        RET

addrs:  .word 0x1005000, 0x1005001, 0x1005100, 0x1010000, 0x1100000, 0x1400000, 0x1800000   ; past the 16K-word stack (RAM 0..0x3FFF)
vals:   .word 0xA0000000, 0xA0000001, 0xA0000002, 0xA0000003, 0xA0000004, 0xA0000005, 0xA0000006
