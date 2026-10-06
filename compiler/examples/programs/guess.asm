; guess.asm - guess the number (1 to 100)
;
; python compiler/src/asm build compiler/examples/programs/guess.asm compiler/examples/stdlib/stdlib.asm
;
; Press any key to start: how long you wait seeds the random number.
; Then type guesses and Enter; the game says higher / lower until you get it.
;
;   guess the number (1-100)
;   press a key to start
;   guess: 50
;   higher
;   guess: 75
;   lower
;   ...
;   got it in 6 tries

        .extern print_string, print_int, print_newline
        .extern read_int, srand_key, rand
        .global start

        .rom
start:
        DATA R0, t_title
        STK PUSH
        CALL print_string, 1
        CALL srand_key              ; waits for the key, seeds rand
        CALL rand
        MOD R0, #100
        ADD R0, #1
        CPY R0, R10                 ; R10 = secret, 1..100
        DATA R11, 0                 ; R11 = tries

ask:
        SAVE R10, R11               ; SAVE before pushing arguments
        DATA R0, t_guess
        STK PUSH
        CALL print_string, 1
        CALL read_int               ; echoes what you type
        RESTORE R10, R11
        CPY R0, R12                 ; R12 = the guess
        ++ R11
        CPY R0, R11
        CMP R12, R10
        RJF Z, won
        RJF A, too_high             ; guess > secret
        DATA R1, t_higher
        RJMP say
too_high:
        DATA R1, t_lower
say:
        SAVE R10, R11
        CPY R1, R0
        STK PUSH
        CALL print_string, 1
        RESTORE R10, R11
        RJMP ask

won:
        SAVE R11
        DATA R0, t_won
        STK PUSH
        CALL print_string, 1
        RESTORE R11
        CPY R11, R0
        STK PUSH
        CALL print_int, 1
        DATA R0, t_tries
        STK PUSH
        CALL print_string, 1
        HALT

t_title:    .string "guess the number (1-100)\npress a key to start\n"
t_guess:    .string "guess: "
t_higher:   .string "higher\n"
t_lower:    .string "lower\n"
t_won:      .string "got it in "
t_tries:    .string " tries\n"
