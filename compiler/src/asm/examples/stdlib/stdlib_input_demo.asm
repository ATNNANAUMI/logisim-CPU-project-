; stdlib_input_demo.asm - tries the four input functions (needs typing)
;
; python compiler/src/asm build stdlib_input_demo.asm stdlib.asm -o input_demo.rom
;
; Example session (typed text shown after each prompt):
;   name? Arthur
;   hi Arthur (6 letters)
;   int? 21
;   x2 = 42
;   float? 3.5
;   /2 = 1.7500
;   press a key... you pressed: q

        .extern print_char, print_string, print_int, print_newline
        .extern print_float
        .extern read_char, read_line, read_int, read_float
        .global start

        .equ NAME_SIZE, 20

        .ram
name:   .space NAME_SIZE

        .rom
start:
; ---- read_line
        DATA R0, q_name
        STK PUSH
        CALL print_string, 1
        DATA R0, name               ; R5 = read_line(name, NAME_SIZE)
        STK PUSH
        DATA R0, NAME_SIZE
        STK PUSH
        CALL read_line, 2
        CPY R0, R5
        SAVE R5
        DATA R0, a_hi
        STK PUSH
        CALL print_string, 1
        DATA R0, name
        STK PUSH
        CALL print_string, 1
        DATA R0, a_open
        STK PUSH
        CALL print_string, 1
        RESTORE R5
        CPY R5, R0
        STK PUSH
        CALL print_int, 1
        DATA R0, a_letters
        STK PUSH
        CALL print_string, 1

; ---- read_int
        DATA R0, q_int
        STK PUSH
        CALL print_string, 1
        CALL read_int
        MULT R0, #2
        CPY R0, R5
        SAVE R5
        DATA R0, a_x2
        STK PUSH
        CALL print_string, 1
        RESTORE R5
        CPY R5, R0
        STK PUSH
        CALL print_int, 1
        CALL print_newline

; ---- read_float
        DATA R0, q_float
        STK PUSH
        CALL print_string, 1
        CALL read_float
        FDIV R0, #2.0
        CPY R0, R5
        SAVE R5
        DATA R0, a_half
        STK PUSH
        CALL print_string, 1
        RESTORE R5
        CPY R5, R0
        STK PUSH
        CALL print_float, 1
        CALL print_newline

; ---- read_char
        DATA R0, q_key
        STK PUSH
        CALL print_string, 1
        CALL read_char
        CPY R0, R5
        SAVE R5
        DATA R0, a_key
        STK PUSH
        CALL print_string, 1
        RESTORE R5
        CPY R5, R0
        STK PUSH
        CALL print_char, 1
        CALL print_newline
        HALT

q_name:     .string "name? "
a_hi:       .string "hi "
a_open:     .string " ("
a_letters:  .string " letters)\n"
q_int:      .string "int? "
a_x2:       .string "x2 = "
q_float:    .string "float? "
a_half:     .string "/2 = "
q_key:      .string "press a key... "
a_key:      .string "you pressed: "
