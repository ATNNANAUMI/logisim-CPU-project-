; untested.asm - checks the last two stdlib functions not yet run on the circuit:
; show_hex and try_read_char
;
; python compiler/src/asm build compiler/examples/programs/untested.asm compiler/examples/stdlib/stdlib.asm
;
; Type two keys, e.g. "ab" (no Enter). Expected:
;   hex display shows CAFE1234
;   TTY:
;     show_hex sent CAFE1234
;     tty still works
;     type 2 keys
;     first: a
;     next:  b after N polls      (N = how long you took; 0 if both were
;                                  already typed, as in a headless run)
;     empty: 0
;
; Line 2 checks the TTY can be selected again after show_hex selected the
; hex display. "empty: 0" checks try_read_char returns 0 with nothing typed.

        .extern print_string, print_char, print_int, print_newline
        .extern show_hex, read_char, try_read_char
        .global start

        .rom
start:
; ---- show_hex
        DATA R0, 0xCAFE1234
        STK PUSH
        CALL show_hex, 1            ; hex display is now the selected output
        DATA R0, t_sent             ; print_string selects the TTY again
        STK PUSH
        CALL print_string, 1

; ---- try_read_char
        DATA R0, t_type
        STK PUSH
        CALL print_string, 1
        CALL read_char              ; waits for the first key
        CPY R0, R10                 ; R10 = first key
        SAVE R10
        DATA R0, t_first
        STK PUSH
        CALL print_string, 1
        RESTORE R10
        CPY R10, R0
        STK PUSH
        CALL print_char, 1
        CALL print_newline

        DATA R11, 0                 ; R11 = polls that found nothing
poll:
        SAVE R11
        CALL try_read_char
        RESTORE R11
        TEST R0
        RJNF Z, got
        ++ R11
        CPY R0, R11
        RJMP poll
got:
        CPY R0, R10                 ; R10 = second key
        SAVE R10, R11
        DATA R0, t_next
        STK PUSH
        CALL print_string, 1
        RESTORE R10, R11
        SAVE R11
        CPY R10, R0
        STK PUSH
        CALL print_char, 1
        DATA R0, t_after
        STK PUSH
        CALL print_string, 1
        RESTORE R11
        CPY R11, R0
        STK PUSH
        CALL print_int, 1
        DATA R0, t_polls
        STK PUSH
        CALL print_string, 1

        CALL try_read_char          ; nothing left: must be 0
        CPY R0, R10
        SAVE R10
        DATA R0, t_empty
        STK PUSH
        CALL print_string, 1
        RESTORE R10
        CPY R10, R0
        STK PUSH
        CALL print_int, 1
        CALL print_newline
        HALT

t_sent:     .string "show_hex sent CAFE1234\ntty still works\n"
t_type:     .string "type 2 keys\n"
t_first:    .string "first: "
t_next:     .string "next:  "
t_after:    .string " after "
t_polls:    .string " polls\n"
t_empty:    .string "empty: "
