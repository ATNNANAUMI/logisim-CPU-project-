; ==================================================================
; interrupt.asm - interrupt entry and the small CPU instructions
; (cpu.h), part of the C library
;
; The linker points the CPU's vectors (0 reset, 2 NMI, 4 IRQ, 6 TRAP, 8 FAULT)
; at the ROM labels _nmi, _irq, _trap and _fault when a file has them
; .global. They are here, and a program gets them by calling
; set_interrupt_handler(which, handler), which also keeps them linked.
;
; Entering an interrupt the CPU has pushed two words (the selected devices,
; then the address to return to, the flags and the enable bit) and turned
; interrupts off. A stub saves
; all 16 registers on the interrupted program's stack, calls the C function
; in its slot, `unsigned handler(void)`, and goes to int_finish with R0 =
; the function's value. If that is not 0 it replaces the address RTI returns
; to (how the shell's NMI handler kills the program that is running);
; otherwise the program goes on where it was. Registers and flags come back
; as they were; the handler runs with interrupts off (it can call
; interrupts_on() if it wants to be interrupted).
;
; With no handler: an NMI and a TRAP are ignored, an IRQ switches off every
; interrupt source (nobody could acknowledge it), a FAULT (the stack limit)
; stops the CPU.
;
; A kernel (tynix/kernel.c) uses five more words. _int_kstack: when not 0,
; the RAM index of a stack of its own: the outermost entry saves the
; interrupted ESP and EBP into the record _int_cur points to ({esp, ebp,
; limit}), runs the handler on that stack with the limit _int_klimit, and
; on the way out loads ESP, EBP and the limit from the record again; if the
; handler put a record's address in _int_next, that one becomes _int_cur
; first: the switch from one program to another. An entry inside another
; (an NMI during a handler) stays on the stack it found. _int_frame is the
; RAM address of the outermost entry's saved word (its devices word is the
; one before, R0 ... R15 the 16 after it); _int_depth counts the entries
; in progress. With _int_kstack = 0 (every program but a kernel) nothing
; changes stacks.
; ==================================================================

        .global _nmi, _irq, _trap, _fault
        .global set_interrupt_handler, interrupts_on, interrupts_off
        .global wait_for_interrupt, software_interrupt, set_stack_limit, stack_pointer
        .global _int_kstack, _int_klimit, _int_cur, _int_next, _int_frame, _int_depth

        .ram
int_slots:  .space 4                ; the handlers: NMI, IRQ, TRAP, FAULT
_int_kstack: .space 1               ; a kernel's stack (RAM index), 0: none
_int_klimit: .space 1               ; its limit (RAM index)
_int_cur:   .space 1                ; the record {esp, ebp, limit} of what runs
_int_next:  .space 1                ; a record to switch to on the way out, 0: none
_int_frame: .space 1                ; the outermost entry's saved word (RAM address)
_int_depth: .space 1                ; entries in progress

        .rom
; void set_interrupt_handler(int which, unsigned (*handler)(void))
set_interrupt_handler:
        DATA R1, -3
        STK GET, R1
        CPY R0, R2                  ; R2 = which (0 NMI, 1 IRQ, 2 TRAP, 3 FAULT)
        DATA R1, -2
        STK GET, R1
        CPY R0, R3                  ; R3 = the function
        DATA R1, int_slots
        ADD R1, R2
        CPY R0, R1
        ST R1, R3                   ; int_slots[which] = handler
        DATA R4, _nmi               ; (these name the stubs, so the linker keeps them)
        DATA R4, _irq
        DATA R4, _trap
        DATA R4, _fault
        DATA R0, 0
        RET

interrupts_on:
        EI
        RET

interrupts_off:
        DI
        RET

wait_for_interrupt:
        WAIT
        RET

software_interrupt:
        TRAP
        RET

; void set_stack_limit(unsigned address): the limit as a RAM address
set_stack_limit:
        DATA R1, -2
        STK GET, R1
        CPY R0, R1
        SUB R1, #0x1000000          ; address - RAM_BASE: the register holds an index
        CPY R0, R1
        SLIM R1
        DATA R0, 0
        RET

; unsigned stack_pointer(void): ESP as a RAM address
stack_pointer:
        GSP R1
        ADD R1, #0x1000000
        RET

; The vectors: save every register, then int_enter with R1 = which
_nmi:
        SAVE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        DATA R1, 0
        RJMP int_enter
_irq:
        SAVE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        DATA R1, 1
        RJMP int_enter
_trap:
        SAVE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        DATA R1, 2
        RJMP int_enter
_fault:
        SAVE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        DATA R1, 3

; R1 = 0 NMI, 1 IRQ, 2 TRAP, 3 FAULT; every register is saved
int_enter:
        CPY R1, R13                 ; R13 = which
        DATA R3, _int_depth
        LD R3, R4                   ; R4 = entries in progress before this one
        ADD R4, #1
        ST R3, R0
        TEST R4
        RJNF Z, int_call            ; inside another: stay on this stack
        GSP R2
        ADD R2, #0xFFFFEF           ; RAM_BASE - 17: the saved word's address
        DATA R5, _int_frame
        ST R5, R0
        DATA R5, _int_kstack
        LD R5, R6
        TEST R6
        RJF Z, int_call             ; no kernel stack
        DATA R5, _int_cur
        LD R5, R7                   ; R7 = the record of what was running
        ST R7, R2                   ; its esp
        GBP R2
        ADD R7, #1
        ST R0, R2                   ; its ebp
        SSP R6                      ; the kernel's stack
        SBP R6
        DATA R5, _int_klimit
        LD R5, R6
        SLIM R6
int_call:
        DATA R1, int_slots
        ADD R1, R13
        LD R0, R1                   ; R1 = the C handler (0: none)
        TEST R1
        RJF Z, int_none
        DATA R0, int_back           ; call it: the return address, a frame, the jump
        STK PUSH
        STK CALL
        JMRB R1
int_none:
        DATA R0, 0
        TEST R13
        RJF Z, int_back             ; NMI: ignored
        SUB R13, #2
        RJF Z, int_back             ; TRAP: ignored
        TEST R0
        RJNF N, int_halt            ; FAULT (3): stop
        DATA R1, 0xAD               ; IRQ: no interrupt sources (nobody acknowledges them)
        COMM OUTADDR, R1
        DATA R1, 0
        COMM OUTDATA, R1
        DATA R0, 0
        RJMP int_back
int_halt:
        HALT
        RJMP int_halt

; R0 = the handler's value: if not 0, the address to return to instead
int_back:
        CPY R0, R9
        DATA R3, _int_depth
        LD R3, R4
        SUB R4, #1
        ST R3, R0
        CPY R0, R4                  ; R4 = entries still in progress
        TEST R9
        RJF Z, int_switch
        TEST R4
        RJNF Z, int_inner
        DATA R2, _int_frame
        LD R2, R2                   ; the outermost entry's saved word
        RJMP int_patch
int_inner:
        GSP R2                      ; an inner entry's frame is just below
        ADD R2, #0xFFFFEF
        CPY R0, R2
int_patch:
        LD R2, R3                   ; R3 = the word
        AND R3, #0xFE000000         ; keep the flags and the two bits
        OR R0, R9
        ST R2, R0
int_switch:
        TEST R4
        RJNF Z, int_restore
        DATA R5, _int_kstack
        LD R5, R6
        TEST R6
        RJF Z, int_restore
        DATA R5, _int_next
        LD R5, R7
        TEST R7
        RJF Z, int_same
        DATA R6, _int_cur
        ST R6, R7                   ; _int_cur = _int_next
        DATA R6, 0
        ST R5, R6                   ; _int_next = 0
int_same:
        DATA R5, _int_cur
        LD R5, R7                   ; R7 = the record of what runs now
        LD R7, R6
        SSP R6
        ADD R7, #1
        LD R0, R6
        SBP R6
        ADD R7, #2
        LD R0, R6
        SLIM R6
int_restore:
        RESTORE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        RTI
