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
; BUILD (from the project root; the ROM lands in compiler/ROM/yourprog.rom)
;   python compiler/src/asm build yourprog.asm compiler/examples/stdlib/stdlib.asm
;
; FUNCTIONS                                   returns
;   output
;     print_char(c)                           -
;     print_string(addr)                      -
;     print_int(n)                            -
;     print_newline()                         -
;     print_float(f)          4 decimals      -
;     print_hex(v)            0x + 8 digits   -
;     show_hex(v)             on the 8-digit display at 0x3C (leaves it
;                             selected: the print_ functions reselect the TTY)
;   input
;     read_char()             no echo         the key
;     read_line(buf, max)     echoes, backspace   length (max-1 chars at most)
;     read_int()              echoes, backspace   the number
;     read_float()            echoes, backspace   the float
;     try_read_char()         no wait, no echo    the key, or 0 if none
;   strings (0-terminated, one character per word)
;     str_len(addr)                           length
;     str_copy(dst, src)                      length
;     str_eq(a, b)                            1 same / 0 different
;     str_cmp(a, b)                           -1 a<b / 0 same / 1 a>b
;     str_cat(dst, src)       append src      new length of dst
;     str_chr(addr, c)                        index of c, or -1
;   characters
;     to_upper(c)  to_lower(c)                the character
;     is_digit(c)  is_alpha(c)                1 / 0
;   memory
;     mem_copy(dst, src, n)   n words         -
;     mem_set(dst, value, n)  n words         -
;     mem_move(dst, src, n)   n words, overlap-safe   -
;     malloc(n)               n words         address, or 0 if no room
;     free(addr)              addr from malloc (0 is ignored)   -
;   random
;     srand(seed)                             -
;     rand()                                  0 .. 32767
;     srand_key()             waits for a key, seeds from the wait   the key
;   int math
;     abs(n)  min(a, b)  max(a, b)  pow(base, exp)    (exp < 0 gives 0)
;   float math
;     fabs(f)  fmin(a, b)  fmax(a, b)
;     ffloor(f)               largest whole float <= f
;     fsqrt(f)                Newton's method; f <= 0 gives 0.0
;   conversion
;     int_to_str(n, buf)      buf: 12 words   length
;     str_to_int(addr)        [-]digits       the number
;
; HEAP
;   malloc hands out RAM from HEAP_START (0x18000) to the end of RAM
;   (0x1FFFF), 32K words. Program RAM (.ram, from 0x14000) must stay below
;   HEAP_START: 16K words. Each block has one header word before it:
;   its size with the header, positive = free, negative = in use.
;   Neighbouring free blocks are joined the next time malloc passes them.
; ==================================================================

        .equ DISPLAY, 0x5C
        .equ KEYBOARD, 0xF0
        .equ BACKSPACE, 0x08
        .equ IN_SIZE, 32            ; line buffer for read_int / read_float
        .equ HEX_DISPLAY, 0x3C
        .equ HEAP_START, 0x18000    ; malloc's RAM: HEAP_START .. end of RAM
        .equ HEAP_END, 0x20000      ; one past the last word of RAM

        .global print_char, print_string, print_int, print_newline
        .global print_float, print_hex, show_hex
        .global read_char, read_line, read_int, read_float, try_read_char
        .global str_len, str_copy, str_eq, str_cmp, str_cat, str_chr
        .global to_upper, to_lower, is_digit, is_alpha
        .global mem_copy, mem_set, mem_move, malloc, free
        .global srand, rand, srand_key
        .global abs, min, max, pow
        .global fabs, fmin, fmax, ffloor, fsqrt
        .global int_to_str, str_to_int

        .ram
num_buf:    .space 12               ; print_int's digits
in_buf:     .space IN_SIZE          ; read_int / read_float's typed line
rand_state: .space 1                ; rand's LCG state

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

; show_hex(v): show v on the 8-digit hex display. That display stays the
; selected output device; every print_ function selects the TTY again.
show_hex:
        DATA R1, -2
        STK GET, R1                 ; R0 = v
        DATA R1, HEX_DISPLAY
        COMM OUTADDR, R1
        COMM OUTDATA, R0
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

; try_read_char(): one look at the keyboard: the key, or 0 if nothing was
; typed. No waiting, no echo - for loops that keep running between keys.
try_read_char:
        DATA R1, KEYBOARD
        COMM INADDR, R1
        COMM INDATA, R0             ; 0 = nothing typed
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

; str_cmp(a, b): -1 if a sorts before b, 0 if the same, 1 if after.
; Compares character codes, so 'Z' < 'a', and a prefix sorts first.
str_cmp:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = a
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = b
        DATA R3, 0                  ; R3 = index
scmp_loop:
        ALD R1, R3
        CPY R0, R4                  ; R4 = a[i]
        ALD R2, R3
        CPY R0, R5                  ; R5 = b[i]
        CMP R4, R5
        RJF A, scmp_after           ; a[i] > b[i]
        RJNF Z, scmp_before         ; a[i] < b[i]
        TEST R4
        RJF Z, scmp_same            ; both ended
        ++ R3
        CPY R0, R3
        RJMP scmp_loop
scmp_before:
        DATA R0, -1
        RET
scmp_after:
        DATA R0, 1
        RET
scmp_same:
        DATA R0, 0
        RET

; str_cat(dst, src): append src to the end of dst, return dst's new length.
; dst needs room for both and the 0.
str_cat:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = dst
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = src
        DATA R3, 0                  ; R3 = index in dst
scat_find:                          ; find dst's 0
        ALD R1, R3
        TEST R0
        RJF Z, scat_copy
        ++ R3
        CPY R0, R3
        RJMP scat_find
scat_copy:
        DATA R4, 0                  ; R4 = index in src
scat_loop:
        ALD R2, R4
        AST R1, R3
        TEST R0
        RJF Z, scat_done            ; the 0 is copied too
        ++ R3
        CPY R0, R3
        ++ R4
        CPY R0, R4
        RJMP scat_loop
scat_done:
        CPY R3, R0
        RET

; str_chr(addr, c): index of the first c in the string, or -1.
; Looking for 0 finds the end, i.e. returns the length.
str_chr:
        DATA R1, -3
        STK GET, R1
        CPY R0, R1                  ; R1 = address
        DATA R2, -2
        STK GET, R2
        CPY R0, R2                  ; R2 = c
        DATA R3, 0                  ; R3 = index
schr_loop:
        ALD R1, R3
        CPY R0, R4                  ; R4 = character
        CMP R4, R2
        RJF Z, schr_found
        TEST R4
        RJF Z, schr_none            ; end of string
        ++ R3
        CPY R0, R3
        RJMP schr_loop
schr_found:
        CPY R3, R0
        RET
schr_none:
        DATA R0, -1
        RET

; ------------------------------------------------------------------
; CHARACTERS
; ------------------------------------------------------------------

; to_upper(c): 'a'..'z' become 'A'..'Z', anything else is returned as is
to_upper:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = c
        CMP R1, #'a'
        RJF N, tu_same              ; below 'a'
        CMP R1, #'z'
        RJF A, tu_same              ; above 'z'
        SUB R1, #32
        RET
tu_same:
        CPY R1, R0
        RET

; to_lower(c): 'A'..'Z' become 'a'..'z', anything else is returned as is
to_lower:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = c
        CMP R1, #'A'
        RJF N, tl_same              ; below 'A'
        CMP R1, #'Z'
        RJF A, tl_same              ; above 'Z'
        ADD R1, #32
        RET
tl_same:
        CPY R1, R0
        RET

; is_digit(c): 1 for '0'..'9', else 0
is_digit:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = c
        CMP R1, #'0'
        RJF N, isd_no
        CMP R1, #'9'
        RJF A, isd_no
        DATA R0, 1
        RET
isd_no:
        DATA R0, 0
        RET

; is_alpha(c): 1 for 'a'..'z' and 'A'..'Z', else 0
is_alpha:
        DATA R1, -2
        STK GET, R1
        OR R0, #32                  ; a letter becomes lower case
        CPY R0, R1
        CMP R1, #'a'
        RJF N, isa_no
        CMP R1, #'z'
        RJF A, isa_no
        DATA R0, 1
        RET
isa_no:
        DATA R0, 0
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

; mem_move(dst, src, n): copy n words, correct even when the two overlap.
; Copies back to front when dst is after src, front to back otherwise.
mem_move:
        DATA R1, -4
        STK GET, R1
        CPY R0, R1                  ; R1 = dst
        DATA R2, -3
        STK GET, R2
        CPY R0, R2                  ; R2 = src
        DATA R3, -2
        STK GET, R3
        CPY R0, R3                  ; R3 = n
        CMP R1, R2
        RJF A, mm_back              ; dst > src
        DATA R4, 0                  ; R4 = index, counting up
mm_fwd:
        CMP R4, R3
        RJF AZ, mm_done             ; index >= n
        ALD R2, R4
        AST R1, R4
        ++ R4
        CPY R0, R4
        RJMP mm_fwd
mm_back:
        CPY R3, R4                  ; R4 = index, counting down from n
mm_bloop:
        TEST R4
        RJF NZ, mm_done             ; index <= 0
        -- R4
        CPY R0, R4
        ALD R2, R4
        AST R1, R4
        RJMP mm_bloop
mm_done:
        RET

; malloc(n): reserve n words of RAM, return their address (0 if n <= 0 or
; there is no room). The words are not cleared. First fit: the first free
; block big enough is used, and split when at least 2 words are left over.
malloc:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = n
        TEST R1
        RJF NZ, ma_fail             ; n <= 0
        ++ R1
        CPY R0, R1                  ; R1 = n + 1, with the header
        DATA R2, HEAP_START         ; R2 = current block
        DATA R6, HEAP_END
        LD R2, R3
        TEST R3
        RJNF Z, ma_walk
        DATA R3, HEAP_END - HEAP_START  ; first use: RAM holds 0, no header yet,
        ST R2, R3                   ; so make the whole heap one free block
ma_walk:
        CMP R2, R6
        RJF AZ, ma_fail             ; reached the end: nothing fits
        LD R2, R3                   ; R3 = header
        TEST R3
        RJF N, ma_skip_used
ma_join:                            ; join the free blocks right after this one
        ADD R2, R3
        CPY R0, R4                  ; R4 = next block
        CMP R4, R6
        RJF AZ, ma_fit              ; this block reaches the end
        LD R4, R5
        TEST R5
        RJF N, ma_fit               ; next block is in use
        ADD R3, R5
        CPY R0, R3
        ST R2, R3                   ; one bigger free block
        RJMP ma_join
ma_fit:
        CMP R3, R1
        RJF N, ma_skip_free         ; too small
        SUB R3, R1
        CPY R0, R5                  ; R5 = words left over
        CMP R5, #2
        RJF N, ma_take              ; 0 or 1 left: take the whole block
        ADD R2, R1
        CPY R0, R4                  ; R4 = the leftover block
        ST R4, R5                   ; its header: free, R5 words
        CPY R1, R3                  ; this block shrinks to n + 1
ma_take:
        NEG R3
        ST R2, R0                   ; header: in use
        ++ R2                       ; the words after the header
        RET
ma_skip_free:
        ADD R2, R3
        CPY R0, R2
        RJMP ma_walk
ma_skip_used:
        SUB R2, R3                  ; the header is -size
        CPY R0, R2
        RJMP ma_walk
ma_fail:
        DATA R0, 0
        RET

; free(addr): give back a block from malloc. 0, an address outside the
; heap and a block already freed are ignored.
free:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = addr
        DATA R2, HEAP_START
        CMP R1, R2
        RJF NZ, fr_done             ; addr <= HEAP_START (0 included)
        DATA R2, HEAP_END
        CMP R1, R2
        RJNF N, fr_done             ; addr >= HEAP_END
        -- R1
        CPY R0, R1                  ; R1 = the header
        LD R1, R2
        TEST R2
        RJNF N, fr_done             ; already free
        NEG R2
        ST R1, R0                   ; header: free
fr_done:
        RET

; ------------------------------------------------------------------
; RANDOM
; ------------------------------------------------------------------

; srand(seed): start rand's sequence from seed. The same seed gives the
; same numbers. Without srand the seed is 0.
srand:
        DATA R1, -2
        STK GET, R1                 ; R0 = seed
        DATA R1, rand_state
        ST R1, R0
        RET

; rand(): next number from 0 to 32767.
; state = state * 1103515245 + 12345 (low 32 bits); returns bits 16..30.
rand:
        DATA R1, rand_state
        LD R1, R2
        MULT R2, #1103515245
        ADD R0, #12345
        ST R1, R0
        AND R0, #0x7FFF0000
        DIV R0, #65536
        RET

; srand_key(): wait for a key, counting how many times the keyboard was
; checked, and seed rand with that count. The CPU has no clock, so how
; long a person takes to press a key is the randomness. Returns the key
; (no echo).
srand_key:
        DATA R1, KEYBOARD
        COMM INADDR, R1
        DATA R2, 0                  ; R2 = checks so far
sk_wait:
        ++ R2
        CPY R0, R2
        COMM INDATA, R3
        TEST R3
        RJF Z, sk_wait
        DATA R1, rand_state
        ST R1, R2
        CPY R3, R0
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

; ffloor(f): the largest whole number <= f, as a float (-2.3 gives -3.0)
ffloor:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = f
        AND R1, #0x7FFFFFFF         ; R0 = bits of |f|
        TEST R0
        RJF Z, ff_same              ; 0.0 or -0.0
        CMP R0, #0x4B000000         ; |f| >= 2^23: already whole
        RJNF N, ff_same             ; (also too big for INT)
        INT R1
        FLOAT R0
        CPY R0, R2                  ; R2 = f with the fraction cut off
        FCMP R1, R2
        RJNF N, ff_done             ; f >= that: it is the floor
        FSUB R2, #1.0               ; negative with a fraction: one lower
        RET
ff_done:
        CPY R2, R0
        RET
ff_same:
        CPY R1, R0
        RET

; fsqrt(f): square root by Newton's method, x = (x + f/x) / 2.
; The first guess halves f's exponent (shift its bits right), so 5 steps
; reach full float precision. f <= 0 gives 0.0.
fsqrt:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1                  ; R1 = f
        TEST R1
        RJF NZ, fsq_zero            ; sign bit set, or 0
        SHR R1
        ADD R0, #0x1FBD1DF5
        CPY R0, R2                  ; R2 = first guess
        DATA R3, 5                  ; R3 = steps left
fsq_loop:
        FDIV R1, R2
        FADD R0, R2
        FMULT R0, #0.5
        CPY R0, R2                  ; x = (f / x + x) / 2
        -- R3
        CPY R0, R3
        RJNF Z, fsq_loop
        CPY R2, R0
        RET
fsq_zero:
        DATA R0, 0.0
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