; stdlib_demo.asm - runs every non-input stdlib function once
;
; python compiler/src/asm build compiler/examples/stdlib/stdlib_demo.asm compiler/examples/stdlib/stdlib.asm
;
; Expected output:
;   int:    -1234 2147483647 -2147483648
;   hex:    0x0000BEEF 0xFFFFFFFF
;   float:  3.1416 -0.5000 100.0000
;   math:   42 -7 9 1024
;   fmath:  2.5000 -1.0000 4.0000
;   string: 5 hello 1 0
;   memory: ***** hel**
;   conv:   -905 -320

        .extern print_char, print_string, print_int, print_newline
        .extern print_float, print_hex
        .extern str_len, str_copy, str_eq
        .extern mem_copy, mem_set
        .extern abs, min, max, pow
        .extern fabs, fmin, fmax
        .extern int_to_str, str_to_int
        .global start

        .ram
buf:    .space 16

        .rom
start:
; ---- ints
        DATA R0, t_int
        STK PUSH
        CALL print_string, 1
        DATA R0, -1234
        STK PUSH
        CALL print_int, 1
        CALL space
        DATA R0, 2147483647
        STK PUSH
        CALL print_int, 1
        CALL space
        DATA R0, -2147483648
        STK PUSH
        CALL print_int, 1
        CALL print_newline

; ---- hex
        DATA R0, t_hex
        STK PUSH
        CALL print_string, 1
        DATA R0, 0xBEEF
        STK PUSH
        CALL print_hex, 1
        CALL space
        DATA R0, -1
        STK PUSH
        CALL print_hex, 1
        CALL print_newline

; ---- floats
        DATA R0, t_float
        STK PUSH
        CALL print_string, 1
        DATA R0, 3.14159
        STK PUSH
        CALL print_float, 1
        CALL space
        DATA R0, -0.5
        STK PUSH
        CALL print_float, 1
        CALL space
        DATA R0, 100.0
        STK PUSH
        CALL print_float, 1
        CALL print_newline

; ---- int math: each result goes straight into print_int
        DATA R0, t_math
        STK PUSH
        CALL print_string, 1
        DATA R0, -42                ; abs(-42)
        STK PUSH
        CALL abs, 1
        STK PUSH
        CALL print_int, 1
        CALL space
        DATA R0, -7                 ; min(-7, 3)
        STK PUSH
        DATA R0, 3
        STK PUSH
        CALL min, 2
        STK PUSH
        CALL print_int, 1
        CALL space
        DATA R0, 9                  ; max(9, 2)
        STK PUSH
        DATA R0, 2
        STK PUSH
        CALL max, 2
        STK PUSH
        CALL print_int, 1
        CALL space
        DATA R0, 2                  ; pow(2, 10)
        STK PUSH
        DATA R0, 10
        STK PUSH
        CALL pow, 2
        STK PUSH
        CALL print_int, 1
        CALL print_newline

; ---- float math
        DATA R0, t_fmath
        STK PUSH
        CALL print_string, 1
        DATA R0, -2.5               ; fabs(-2.5)
        STK PUSH
        CALL fabs, 1
        STK PUSH
        CALL print_float, 1
        CALL space
        DATA R0, -1.0               ; fmin(-1.0, 4.0)
        STK PUSH
        DATA R0, 4.0
        STK PUSH
        CALL fmin, 2
        STK PUSH
        CALL print_float, 1
        CALL space
        DATA R0, -1.0               ; fmax(-1.0, 4.0)
        STK PUSH
        DATA R0, 4.0
        STK PUSH
        CALL fmax, 2
        STK PUSH
        CALL print_float, 1
        CALL print_newline

; ---- strings (SAVE/RESTORE keeps R5 across a call)
        DATA R0, hello              ; R5 = str_len("hello")
        STK PUSH
        CALL str_len, 1
        CPY R0, R5
        SAVE R5
        DATA R0, t_string
        STK PUSH
        CALL print_string, 1
        RESTORE R5
        CPY R5, R0
        STK PUSH
        CALL print_int, 1
        CALL space
        DATA R0, buf                ; str_copy(buf, "hello")
        STK PUSH
        DATA R0, hello
        STK PUSH
        CALL str_copy, 2
        DATA R0, buf
        STK PUSH
        CALL print_string, 1
        CALL space
        DATA R0, hello              ; str_eq("hello", buf) -> 1
        STK PUSH
        DATA R0, buf
        STK PUSH
        CALL str_eq, 2
        STK PUSH
        CALL print_int, 1
        CALL space
        DATA R0, hello              ; str_eq("hello", "help") -> 0
        STK PUSH
        DATA R0, help
        STK PUSH
        CALL str_eq, 2
        STK PUSH
        CALL print_int, 1
        CALL print_newline

; ---- memory
        DATA R0, t_memory
        STK PUSH
        CALL print_string, 1
        DATA R0, buf                ; mem_set(buf, '*', 5)
        STK PUSH
        DATA R0, '*'
        STK PUSH
        DATA R0, 5
        STK PUSH
        CALL mem_set, 3
        DATA R0, buf + 5            ; mem_set(buf + 5, 0, 1): end marker
        STK PUSH
        DATA R0, 0
        STK PUSH
        DATA R0, 1
        STK PUSH
        CALL mem_set, 3
        DATA R0, buf
        STK PUSH
        CALL print_string, 1
        CALL space
        DATA R0, buf                ; mem_copy(buf, "hello", 3)
        STK PUSH
        DATA R0, hello
        STK PUSH
        DATA R0, 3
        STK PUSH
        CALL mem_copy, 3
        DATA R0, buf
        STK PUSH
        CALL print_string, 1
        CALL print_newline

; ---- conversion
        DATA R0, t_conv
        STK PUSH
        CALL print_string, 1
        DATA R0, -905               ; int_to_str(-905, buf)
        STK PUSH
        DATA R0, buf
        STK PUSH
        CALL int_to_str, 2
        DATA R0, buf
        STK PUSH
        CALL print_string, 1
        CALL space
        DATA R0, minus321           ; str_to_int("-321") + 1
        STK PUSH
        CALL str_to_int, 1
        ADD R0, #1
        STK PUSH
        CALL print_int, 1
        CALL print_newline
        HALT

; space(): print one space (a local helper, not from the stdlib)
space:
        DATA R0, ' '
        STK PUSH
        CALL print_char, 1
        RET

t_int:      .string "int:    "
t_hex:      .string "hex:    "
t_float:    .string "float:  "
t_math:     .string "math:   "
t_fmath:    .string "fmath:  "
t_string:   .string "string: "
t_memory:   .string "memory: "
t_conv:     .string "conv:   "
hello:      .string "hello"
help:       .string "help"
minus321:   .string "-321"
