; Uses the functions in lib.asm. Build both files together:
;   python src/asm build examples/asm/two_files/main.asm examples/asm/two_files/lib.asm

        .extern print_newline, print_dashes
        .global start

        .equ DISPLAY, 0x5C

        .ram
dashes: .space 1                ; print_dashes' return value goes here

        .rom
start:  CALL print_dashes
        DATA R3, dashes
        ST R3, R0               ; save the return value in RAM
        DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R1, 'o'
        COMM OUTDATA, R1
        DATA R1, 'k'
        COMM OUTDATA, R1
        CALL print_newline
        HALT
