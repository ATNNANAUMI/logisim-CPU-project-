; probe_stack.asm - the stack registers on the circuit: SSP SBP GSP GBP SLIM, and a stack above 16 bits
;
;   python compiler/src/asm build logisim/tests/probe_stack.asm compiler/examples/asm/stdlib/stdlib.asm
;
; Expected output, 8 lines:
;   0x00005000   SSP 0x5000, then GSP gives it back
;   0x00006000   SBP 0x6000, then GBP gives it back
;   0x00005001   PUSH moved ESP from 0x5000 to 0x5001
;   0x0000CAFE   the pushed word is RAM word 0x5000 (read at 0x1005000)
;   0x00123457   ESP above 16 bits: SSP 0x123456, PUSH, GSP
;   0x0000BEEF   the word pushed there (RAM word 0x123456)
;   0x00FFFF00   ESP near the top of the 24 bits
;   0x00000000   the last line: SSP 0 and GSP give 0 back
; SLIM first: the simulator faults on a PUSH at or past the stack limit (the circuit has no abort yet).
        .extern print_hex, print_newline
        .global start

        .rom
start:
        DATA R1, 0xFFFFFF
        SLIM R1
        DATA R1, 0x5000
        SSP R1
        GSP R2
        CALL show

        DATA R1, 0x6000
        SBP R1
        GBP R2
        CALL show

        DATA R1, 0x5000
        SSP R1
        DATA R0, 0xCAFE
        STK PUSH
        GSP R2
        CALL show
        DATA R4, 0x1005000
        DATA R5, 0
        ALD R4, R5
        CPY R0, R2
        CALL show

        DATA R1, 0x123456
        SSP R1
        DATA R0, 0xBEEF
        STK PUSH
        GSP R2
        CALL show
        DATA R4, 0x1123456
        DATA R5, 0
        ALD R4, R5
        CPY R0, R2
        CALL show

        DATA R1, 0xFFFF00
        SSP R1
        GSP R2
        CALL show

        DATA R1, 0
        SSP R1
        GSP R2
        CALL show
        HALT

show:                               ; prints R2 in hex and a newline (CALL clobbers R0, R14, R15)
        CPY R2, R0
        STK PUSH
        CALL print_hex, 1
        CALL print_newline
        RET
