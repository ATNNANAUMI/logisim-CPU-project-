; ==================================================================
; stdlib.asm - standard library for the logic-gate CPU
;
; HOW TO CALL
;   push the arguments in order (first argument first), then
;   CALL name, N        ; N = number of arguments, dropped after return
;   the result (if any) comes back in R0.
;
;       DATA R0, -42
;       STK PUSH
;       CALL print_int, 1
;
; REGISTERS
;   R0, R14, R15   always changed by a call
;   R1 - R13       may be changed by any call: SAVE / RESTORE what you need
;
; INSIDE A FUNCTION with N arguments
;   first argument at ebp-(N+1) ... last argument at ebp-2
;   (ebp-1 = return address, ebp+0 = old ebp)
;
; BUILD (from the project root)
;   python compiler/src/asm build yourprog.asm
;          compiler/src/asm/examples/stdlib/stdlib.asm -o yourprog.rom
;
; FUNCTIONS                                   returns
;   output
;     print_char(c)                           -
;     print_string(addr)                      -
;     print_int(n)                            -
;     print_newline()                         -
;     print_float(f)          4 decimals      -
;     print_hex(v)            0x + 8 digits   -
;   input
;     read_char()             no echo         the key
;     read_line(buf, max)     echoes, backspace   length (max-1 chars at most)
;     read_int()              echoes, backspace   the number
;     read_float()            echoes, backspace   the float
;   strings (0-terminated, one character per word)
;     str_len(addr)                           length
;     str_copy(dst, src)                      length
;     str_eq(a, b)                            1 same / 0 different
;   memory
;     mem_copy(dst, src, n)   n words         -
;     mem_set(dst, value, n)  n words         -
;   int math
;     abs(n)  min(a, b)  max(a, b)  pow(base, exp)    (exp < 0 gives 0)
;   float math
;     fabs(f)  fmin(a, b)  fmax(a, b)
;   conversion
;     int_to_str(n, buf)      buf: 12 words   length
;     str_to_int(addr)        [-]digits       the number
; ==================================================================

        .equ DISPLAY, 0x5C
        .equ KEYBOARD, 0xF0
        .equ BACKSPACE, 0x08
        .equ IN_SIZE, 32            ; line buffer for read_int / read_float

        .global print_char, print_string, print_int, print_newline
        .global print_float, print_hex
        .global read_char, read_line, read_int, read_float
        .global str_len, str_copy, str_eq
        .global mem_copy, mem_set
        .global abs, min, max, pow
        .global fabs, fmin, fmax
        .global int_to_str, str_to_int

        .ram
num_buf:    .space 12               ; print_int's digits
in_buf:     .space IN_SIZE          ; read_int / read_float's typed line

        .rom

; ------------------------------------------------------------------
; OUTPUT
; ------------------------------------------------------------------

; print_char(c): print one character
print_char:
        DATA R1, -2
        STK GET, R1                 ; R0 = c
        DATA R1, DISPLAY
        COMM OUTADDR, R1
        COMM OUTDATA, R0
        RET

; print_string(addr): print a 0-terminated string
print_string:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = address
        DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R2, 0                  ; R2 = index
ps_loop:
        ALD R1, R2                  ; R0 = next character
        TEST R0
        RJF Z, ps_done
        COMM OUTDATA, R0
        ++ R2
        CPY R0, R2
        RJMP ps_loop
ps_done:
        RET

; print_int(n): print a signed decimal number
print_int:
        DATA R1, -2
        STK GET, R1
        STK PUSH                    ; int_to_str(n, num_buf)
        DATA R0, num_buf
        STK PUSH
        CALL int_to_str, 2
        DATA R0, num_buf            ; print_string(num_buf)
        STK PUSH
        CALL print_string, 1
        RET

; print_newline(): print a line break
print_newline:
        DATA R1, DISPLAY
        COMM OUTADDR, R1
        DATA R1, '\n'
        COMM OUTDATA, R1
        RET

; print_float(f): print a float with 4 decimals, e.g. -3.1416
; (the whole part must fit in an int)
print_float:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = f
        DATA R2, DISPLAY
        COMM OUTADDR, R2
        TEST R1                     ; sign bit set = negative
        RJNF N, pf_pos
        DATA R2, '-'
        COMM OUTDATA, R2
        FNEG R1
        CPY R0, R1                  ; R1 = -f
pf_pos:
        FADD R1, #0.00005           ; round to 4 decimals
        CPY R0, R1
        SAVE R1                     ; whole part = floor_pos(R1)
        CPY R1, R0
        STK PUSH
        CALL floor_pos, 1
        RESTORE R1
        CPY R0, R2                  ; R2 = whole part
        FLOAT R2
        CPY R0, R3
        FSUB R1, R3
        CPY R0, R1                  ; R1 = fraction, 0 <= R1 < 1
        SAVE R1                     ; print_int(whole part)
        CPY R2, R0
        STK PUSH
        CALL print_int, 1
        RESTORE R1
        DATA R2, '.'
        COMM OUTDATA, R2
        DATA R4, 4                  ; R4 = digits left
pf_digit:
        FMULT R1, #10.0
        CPY R0, R1
        SAVE R1, R4                 ; digit = floor_pos(R1)
        CPY R1, R0
        STK PUSH
        CALL floor_pos, 1
        RESTORE R1, R4
        CPY R0, R2                  ; R2 = digit
        FLOAT R2
        CPY R0, R3
        FSUB R1, R3
        CPY R0, R1                  ; take the digit out of the fraction
        ADD R2, #'0'
        COMM OUTDATA, R0
        -- R4
        CPY R0, R4
        RJNF Z, pf_digit
        RET

; floor_pos(f): whole part of a float >= 0, as an int (private helper)
; INT truncates toward zero (on the circuit and in the simulator), so for
; f >= 0 it already is the floor.
floor_pos:
        DATA R1, -2
        STK GET, R1                 ; R0 = f
        INT R0
        RET

; print_hex(v): print 0x and 8 hex digits
print_hex:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = value
        DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R2, '0'
        COMM OUTDATA, R2
        DATA R2, 'x'
        COMM OUTDATA, R2
        DATA R3, 8                  ; 8 digits, lowest first, onto the stack
ph_split:
        AND R1, #0xF
        CPY R0, R2                  ; R2 = lowest 4 bits
        CMP R2, #9
        RJF A, ph_letter
        ADD R2, #'0'
        RJMP ph_push
ph_letter:
        ADD R2, #'A' - 10
ph_push:
        STK PUSH
        SHR R1
        SHR R0
        SHR R0
        SHR R0
        CPY R0, R1                  ; value >>= 4
        -- R3
        CPY R0, R3
        RJNF Z, ph_split
        DATA R3, 8                  ; pop them back, highest first
ph_print:
        STK POP
        COMM OUTDATA, R0
        -- R3
        CPY R0, R3
        RJNF Z, ph_print
        RET

; ------------------------------------------------------------------
; INPUT
; ------------------------------------------------------------------

; read_char(): wait for a key and return it. No echo: the caller decides
; whether the key is shown (print_char), e.g. not for a menu choice.
read_char:
        DATA R1, KEYBOARD
        COMM INADDR, R1
rc_wait:
        COMM INDATA, R0
        TEST R0
        RJF Z, rc_wait              ; 0 = nothing typed yet
        RET

; read_line(buf, max): read keys into buf until Enter, echoing them.
; Keeps at most max-1 characters (extra keys are ignored), adds a 0.
; Backspace removes the last character kept, from buf and from the display;
; with nothing kept it does nothing (so it can't eat the prompt).
; Returns the length.
read_line:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = buf
        DATA R2, -2
        STK GET, R2
        -- R0
        CPY R0, R4                  ; R4 = max - 1
        DATA R3, 0                  ; R3 = length
        DATA R2, KEYBOARD
        COMM INADDR, R2
        DATA R2, DISPLAY
        COMM OUTADDR, R2
rl_wait:
        COMM INDATA, R5
        TEST R5
        RJF Z, rl_wait              ; nothing typed yet
        CMP R5, #'\n'
        RJF Z, rl_done
        CMP R5, #'\r'
        RJF Z, rl_done
        CMP R5, #BACKSPACE
        RJF Z, rl_back
        CMP R3, R4
        RJF AZ, rl_wait             ; full: ignore the key
        CPY R5, R0
        AST R1, R3                  ; buf[length] = key
        COMM OUTDATA, R5            ; echo
        ++ R3
        CPY R0, R3
        RJMP rl_wait
rl_back:
        TEST R3
        RJF Z, rl_wait              ; nothing kept: ignore it
        -- R3
        CPY R0, R3                  ; length - 1: the next key or the 0 overwrites it
        COMM OUTDATA, R5            ; echo the backspace: the display deletes it too
        RJMP rl_wait
rl_done:
        DATA R2, '\n'
        COMM OUTDATA, R2
        DATA R0, 0
        AST R1, R3                  ; end marker
        CPY R3, R0
        RET

; read_int(): read a line and return it as an int
read_int:
        DATA R0, in_buf
        STK PUSH
        DATA R0, IN_SIZE
        STK PUSH
        CALL read_line, 2
        DATA R0, in_buf
        STK PUSH
        CALL str_to_int, 1
        RET

; read_float(): read a line like -12.75 and return it as a float
read_float:
        DATA R0, in_buf
        STK PUSH
        DATA R0, IN_SIZE
        STK PUSH
        CALL read_line, 2
        DATA R1, in_buf             ; R1 = text
        DATA R2, 0                  ; R2 = index
        DATA R3, 0.0                ; R3 = value
        DATA R4, 0                  ; R4 = 1 if negative
        ALD R1, R2
        CMP R0, #'-'
        RJNF Z, rf_whole
        DATA R4, 1
        DATA R2, 1
rf_whole:                           ; digits before the '.'
        ALD R1, R2
        CPY R0, R6
        CMP R6, #'.'
        RJF Z, rf_dot
        SUB R6, #'0'
        RJF N, rf_end               ; below '0'
        CPY R0, R6
        CMP R6, #9
        RJF A, rf_end               ; above '9'
        FLOAT R6
        CPY R0, R6                  ; R6 = digit as a float
        FMULT R3, #10.0
        FADD R0, R6
        CPY R0, R3                  ; value = value * 10 + digit
        ++ R2
        CPY R0, R2
        RJMP rf_whole
rf_dot:
        ++ R2
        CPY R0, R2
        DATA R5, 1.0                ; R5 = place value
rf_frac:                            ; digits after the '.'
        ALD R1, R2
        SUB R0, #'0'
        RJF N, rf_end
        CPY R0, R6
        CMP R6, #9
        RJF A, rf_end
        FLOAT R6
        CPY R0, R6                  ; R6 = digit as a float
        FDIV R5, #10.0
        CPY R0, R5                  ; place value / 10
        FMULT R6, R5
        FADD R0, R3
        CPY R0, R3                  ; value = value + digit * place
        ++ R2
        CPY R0, R2
        RJMP rf_frac
rf_end:
        TEST R4
        RJF Z, rf_pos
        FNEG R3
        RET
rf_pos:
        CPY R3, R0
        RET

; ------------------------------------------------------------------
; STRINGS
; ------------------------------------------------------------------

; str_len(addr): number of characters before the 0
str_len:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = address
        DATA R2, 0                  ; R2 = length
sl_loop:
        ALD R1, R2
        TEST R0
        RJF Z, sl_done
        ++ R2
        CPY R0, R2
        RJMP sl_loop
sl_done:
        CPY R2, R0
        RET

; str_copy(dst, src): copy src and its 0 to dst, return the length
str_copy:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = dst
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = src
        DATA R3, 0                  ; R3 = index
sc_loop:
        ALD R2, R3
        AST R1, R3
        TEST R0
        RJF Z, sc_done              ; the 0 is copied too
        ++ R3
        CPY R0, R3
        RJMP sc_loop
sc_done:
        CPY R3, R0
        RET

; str_eq(a, b): 1 if the strings are the same, 0 if not
str_eq:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = a
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = b
        DATA R3, 0                  ; R3 = index
se_loop:
        ALD R1, R3
        CPY R0, R4                  ; R4 = a[i]
        ALD R2, R3                  ; R0 = b[i]
        CMP R0, R4
        RJNF Z, se_diff
        TEST R4
        RJF Z, se_same              ; both ended at the same place
        ++ R3
        CPY R0, R3
        RJMP se_loop
se_diff:
        DATA R0, 0
        RET
se_same:
        DATA R0, 1
        RET

; ------------------------------------------------------------------
; MEMORY
; ------------------------------------------------------------------

; mem_copy(dst, src, n): copy n words from src to dst (front to back)
mem_copy:
        DATA R1, -4
        STK GET, R1
        CPY R0, R1                  ; R1 = dst
        DATA R2, -3
        STK GET, R2
        CPY R0, R2                  ; R2 = src
        DATA R3, -2
        STK GET, R3
        CPY R0, R3                  ; R3 = n
        DATA R4, 0                  ; R4 = index
mc_loop:
        CMP R4, R3
        RJF AZ, mc_done             ; index >= n
        ALD R2, R4
        AST R1, R4
        ++ R4
        CPY R0, R4
        RJMP mc_loop
mc_done:
        RET

; mem_set(dst, value, n): set n words at dst to value
mem_set:
        DATA R1, -4
        STK GET, R1
        CPY R0, R1                  ; R1 = dst
        DATA R2, -3
        STK GET, R2
        CPY R0, R2                  ; R2 = value
        DATA R3, -2
        STK GET, R3
        CPY R0, R3                  ; R3 = n
        DATA R4, 0                  ; R4 = index
ms_loop:
        CMP R4, R3
        RJF AZ, ms_done             ; index >= n
        CPY R2, R0
        AST R1, R4
        ++ R4
        CPY R0, R4
        RJMP ms_loop
ms_done:
        RET

; ------------------------------------------------------------------
; INT MATH
; ------------------------------------------------------------------

; abs(n)
abs:
        DATA R1, -2
        STK GET, R1                 ; R0 = n
        TEST R0
        RJNF N, abs_done
        NEG R0
abs_done:
        RET

; min(a, b)
min:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = a
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = b
        CMP R1, R2
        RJF A, min_b                ; a > b
        CPY R1, R0
        RET
min_b:
        CPY R2, R0
        RET

; max(a, b)
max:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = a
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = b
        CMP R1, R2
        RJF A, max_a                ; a > b
        CPY R2, R0
        RET
max_a:
        CPY R1, R0
        RET

; pow(base, exp): base multiplied by itself exp times (exp < 0 gives 0)
pow:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = base
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = exp
        DATA R3, 1                  ; R3 = result
        TEST R2
        RJF N, pow_neg
pow_loop:
        TEST R2
        RJF Z, pow_done
        MULT R3, R1
        CPY R0, R3
        -- R2
        CPY R0, R2
        RJMP pow_loop
pow_done:
        CPY R3, R0
        RET
pow_neg:
        DATA R0, 0
        RET

; ------------------------------------------------------------------
; FLOAT MATH
; ------------------------------------------------------------------

; fabs(f): clear the sign bit
fabs:
        DATA R1, -2
        STK GET, R1
        AND R0, #0x7FFFFFFF
        RET

; fmin(a, b)
fmin:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = a
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = b
        FCMP R1, R2
        RJF N, fmin_a               ; a < b
        CPY R2, R0
        RET
fmin_a:
        CPY R1, R0
        RET

; fmax(a, b)
fmax:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = a
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = b
        FCMP R1, R2
        RJF N, fmax_b               ; a < b
        CPY R1, R0
        RET
fmax_b:
        CPY R2, R0
        RET

; ------------------------------------------------------------------
; CONVERSION
; ------------------------------------------------------------------

; int_to_str(n, buf): write n in decimal into buf, 0-terminated.
; buf needs 12 words. Returns the length.
int_to_str:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = n
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = buf
        DATA R3, 0                  ; R3 = length so far
        TEST R1
        RJNF N, its_pos
        DATA R0, '-'
        AST R2, R3
        DATA R3, 1
        RJMP its_start
its_pos:
        NEG R1
        CPY R0, R1                  ; work with -n: the lowest int fits too
its_start:
        CPY R3, R4                  ; R4 = where the digits start
its_loop:                           ; digits come out lowest first
        MOD R1, #10                 ; 0 .. -9
        NEG R0
        ADD R0, #'0'
        AST R2, R3
        ++ R3
        CPY R0, R3
        DIV R1, #10
        CPY R0, R1
        RJNF Z, its_loop
        DATA R0, 0
        AST R2, R3                  ; end marker
        CPY R3, R5                  ; R5 = length, returned
        -- R3
        CPY R0, R3                  ; R3 = last digit
its_rev:                            ; swap the digits end to end
        CMP R4, R3
        RJF AZ, its_done            ; start >= end
        ALD R2, R4
        CPY R0, R6
        ALD R2, R3
        AST R2, R4
        CPY R6, R0
        AST R2, R3
        ++ R4
        CPY R0, R4
        -- R3
        CPY R0, R3
        RJMP its_rev
its_done:
        CPY R5, R0
        RET

; str_to_int(addr): read an optional '-' and digits from a string,
; stopping at the first other character
str_to_int:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = text
        DATA R2, 0                  ; R2 = index
        DATA R3, 0                  ; R3 = value
        DATA R4, 0                  ; R4 = 1 if negative
        ALD R1, R2
        CMP R0, #'-'
        RJNF Z, sti_loop
        DATA R4, 1
        DATA R2, 1
sti_loop:
        ALD R1, R2
        SUB R0, #'0'
        RJF N, sti_end              ; below '0'
        CPY R0, R5                  ; R5 = digit
        CMP R5, #9
        RJF A, sti_end              ; above '9'
        MULT R3, #10
        ADD R0, R5
        CPY R0, R3                  ; value = value * 10 + digit
        ++ R2
        CPY R0, R2
        RJMP sti_loop
sti_end:
        TEST R4
        RJF Z, sti_pos
        NEG R3
        RET
sti_pos:
        CPY R3, R0
        RET
