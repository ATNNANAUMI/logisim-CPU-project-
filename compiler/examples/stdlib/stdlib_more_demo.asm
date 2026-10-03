; stdlib_more_demo.asm - runs every function added on 2026-10-03 that needs
; no typing and no hex display (try_read_char, srand_key and show_hex are
; left out)
;
; python compiler/src/asm build compiler/examples/stdlib/stdlib_more_demo.asm compiler/examples/stdlib/stdlib.asm
;
; Expected output:
;   move:   ababcd babcdd
;   malloc: 98305 98310 98305 98305 0
;   rand:   16838 5758 10113
;   string: -1 1 0 -1 6 foobar 2 -1
;   chars:  Q q 5 1 0 1 0
;   float:  1.4142 12.0000 0.7071 0.0000 2.0000 -3.0000 -1.0000 5.0000

        .extern print_char, print_string, print_int, print_newline, print_float
        .extern str_copy, str_cmp, str_cat, str_chr
        .extern to_upper, to_lower, is_digit, is_alpha
        .extern mem_move, malloc, free
        .extern srand, rand
        .extern ffloor, fsqrt
        .global start

        .ram
buf:    .space 16
p1:     .space 1
p2:     .space 1
p3:     .space 1

        .rom
start:
; ---- mem_move: "abcdef" -> move(buf+2, buf, 4) -> "ababcd"
;                         -> move(buf, buf+1, 5) -> "babcdd"
        DATA R0, t_move
        STK PUSH
        CALL print_string, 1
        DATA R0, buf
        STK PUSH
        DATA R0, abcdef
        STK PUSH
        CALL str_copy, 2
        DATA R0, buf + 2
        STK PUSH
        DATA R0, buf
        STK PUSH
        DATA R0, 4
        STK PUSH
        CALL mem_move, 3
        DATA R0, buf
        STK PUSH
        CALL print_string, 1
        CALL space
        DATA R0, buf
        STK PUSH
        DATA R0, buf + 1
        STK PUSH
        DATA R0, 5
        STK PUSH
        CALL mem_move, 3
        DATA R0, buf
        STK PUSH
        CALL print_string, 1
        CALL print_newline

; ---- malloc / free: addresses as decimal (98305 = 0x18001)
        DATA R0, t_malloc
        STK PUSH
        CALL print_string, 1
        DATA R0, 4                  ; p1 = malloc(4)  -> 0x18001
        STK PUSH
        CALL malloc, 1
        DATA R1, p1
        ST R1, R0
        STK PUSH
        CALL say, 1
        DATA R0, 10                 ; p2 = malloc(10) -> 0x18006
        STK PUSH
        CALL malloc, 1
        DATA R1, p2
        ST R1, R0
        STK PUSH
        CALL say, 1
        DATA R1, p1                 ; free(p1)
        LD R1, R0
        STK PUSH
        CALL free, 1
        DATA R0, 3                  ; p3 = malloc(3): fits where p1 was
        STK PUSH
        CALL malloc, 1
        DATA R1, p3
        ST R1, R0
        STK PUSH
        CALL say, 1
        DATA R1, p2                 ; free(p2), free(p3)
        LD R1, R0
        STK PUSH
        CALL free, 1
        DATA R1, p3
        LD R1, R0
        STK PUSH
        CALL free, 1
        DATA R0, 12                 ; malloc(12): the freed blocks are joined
        STK PUSH
        CALL malloc, 1
        STK PUSH
        CALL say, 1
        DATA R0, 0                  ; malloc(0) -> 0
        STK PUSH
        CALL malloc, 1
        STK PUSH
        CALL print_int, 1
        CALL print_newline

; ---- rand: seed 1 gives the same numbers as C's classic rand()
        DATA R0, t_rand
        STK PUSH
        CALL print_string, 1
        DATA R0, 1
        STK PUSH
        CALL srand, 1
        CALL rand
        STK PUSH
        CALL say, 1
        CALL rand
        STK PUSH
        CALL say, 1
        CALL rand
        STK PUSH
        CALL print_int, 1
        CALL print_newline

; ---- strings
        DATA R0, t_string
        STK PUSH
        CALL print_string, 1
        DATA R0, apple              ; str_cmp("apple", "apricot") -> -1
        STK PUSH
        DATA R0, apricot
        STK PUSH
        CALL str_cmp, 2
        STK PUSH
        CALL say, 1
        DATA R0, s_b                ; str_cmp("b", "a") -> 1
        STK PUSH
        DATA R0, s_a
        STK PUSH
        CALL str_cmp, 2
        STK PUSH
        CALL say, 1
        DATA R0, s_hi               ; str_cmp("hi", "hi") -> 0
        STK PUSH
        DATA R0, s_hi
        STK PUSH
        CALL str_cmp, 2
        STK PUSH
        CALL say, 1
        DATA R0, s_hi               ; str_cmp("hi", "high") -> -1
        STK PUSH
        DATA R0, s_high
        STK PUSH
        CALL str_cmp, 2
        STK PUSH
        CALL say, 1
        DATA R0, buf                ; buf = "foo"; str_cat(buf, "bar") -> 6
        STK PUSH
        DATA R0, s_foo
        STK PUSH
        CALL str_copy, 2
        DATA R0, buf
        STK PUSH
        DATA R0, s_bar
        STK PUSH
        CALL str_cat, 2
        STK PUSH
        CALL say, 1
        DATA R0, buf
        STK PUSH
        CALL print_string, 1
        CALL space
        DATA R0, abcdef             ; str_chr("abcdef", 'c') -> 2
        STK PUSH
        DATA R0, 'c'
        STK PUSH
        CALL str_chr, 2
        STK PUSH
        CALL say, 1
        DATA R0, abcdef             ; str_chr("abcdef", 'z') -> -1
        STK PUSH
        DATA R0, 'z'
        STK PUSH
        CALL str_chr, 2
        STK PUSH
        CALL print_int, 1
        CALL print_newline

; ---- characters
        DATA R0, t_chars
        STK PUSH
        CALL print_string, 1
        DATA R0, 'q'
        STK PUSH
        CALL to_upper, 1
        STK PUSH
        CALL sayc, 1
        DATA R0, 'Q'
        STK PUSH
        CALL to_lower, 1
        STK PUSH
        CALL sayc, 1
        DATA R0, '5'
        STK PUSH
        CALL to_upper, 1
        STK PUSH
        CALL sayc, 1
        DATA R0, '7'
        STK PUSH
        CALL is_digit, 1
        STK PUSH
        CALL say, 1
        DATA R0, 'x'
        STK PUSH
        CALL is_digit, 1
        STK PUSH
        CALL say, 1
        DATA R0, 'G'
        STK PUSH
        CALL is_alpha, 1
        STK PUSH
        CALL say, 1
        DATA R0, '@'
        STK PUSH
        CALL is_alpha, 1
        STK PUSH
        CALL print_int, 1
        CALL print_newline

; ---- float
        DATA R0, t_float
        STK PUSH
        CALL print_string, 1
        DATA R0, 2.0
        STK PUSH
        CALL fsqrt, 1
        STK PUSH
        CALL sayf, 1
        DATA R0, 144.0
        STK PUSH
        CALL fsqrt, 1
        STK PUSH
        CALL sayf, 1
        DATA R0, 0.5
        STK PUSH
        CALL fsqrt, 1
        STK PUSH
        CALL sayf, 1
        DATA R0, -4.0
        STK PUSH
        CALL fsqrt, 1
        STK PUSH
        CALL sayf, 1
        DATA R0, 2.7
        STK PUSH
        CALL ffloor, 1
        STK PUSH
        CALL sayf, 1
        DATA R0, -2.3
        STK PUSH
        CALL ffloor, 1
        STK PUSH
        CALL sayf, 1
        DATA R0, -0.5
        STK PUSH
        CALL ffloor, 1
        STK PUSH
        CALL sayf, 1
        DATA R0, 5.0
        STK PUSH
        CALL ffloor, 1
        STK PUSH
        CALL print_float, 1
        CALL print_newline
        HALT

; local helpers, not from the stdlib
; say(n): print n and a space
say:
        DATA R1, -2
        STK GET, R1
        STK PUSH
        CALL print_int, 1
        CALL space
        RET

; sayc(c): print a character and a space
sayc:
        DATA R1, -2
        STK GET, R1
        STK PUSH
        CALL print_char, 1
        CALL space
        RET

; sayf(f): print a float and a space
sayf:
        DATA R1, -2
        STK GET, R1
        STK PUSH
        CALL print_float, 1
        CALL space
        RET

; space(): print one space
space:
        DATA R0, ' '
        STK PUSH
        CALL print_char, 1
        RET

t_move:     .string "move:   "
t_malloc:   .string "malloc: "
t_rand:     .string "rand:   "
t_string:   .string "string: "
t_chars:    .string "chars:  "
t_float:    .string "float:  "
abcdef:     .string "abcdef"
apple:      .string "apple"
apricot:    .string "apricot"
s_a:        .string "a"
s_b:        .string "b"
s_hi:       .string "hi"
s_high:     .string "high"
s_foo:      .string "foo"
s_bar:      .string "bar"
