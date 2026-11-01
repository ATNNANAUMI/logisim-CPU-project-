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
; ==================================================================

        .global _nmi, _irq, _trap, _fault
        .global set_interrupt_handler, interrupts_on, interrupts_off
        .global wait_for_interrupt, software_interrupt, set_stack_limit, stack_pointer

        .ram
int_slots:  .space 4                ; the handlers: NMI, IRQ, TRAP, FAULT

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

; NMI vector
_nmi:
        SAVE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        DATA R1, int_slots + 0
        LD R1, R1                   ; R1 = the C handler (0: none)
        TEST R1
        RJF Z, _nmi_none
        DATA R0, _nmi_back        ; call it: the return address, a frame, the jump
        STK PUSH
        STK CALL
        JMRB R1
_nmi_back:
        RJMP int_finish             ; R0 = its value
_nmi_none:
        DATA R0, 0
        RJMP int_finish

; IRQ vector
_irq:
        SAVE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        DATA R1, int_slots + 1
        LD R1, R1                   ; R1 = the C handler (0: none)
        TEST R1
        RJF Z, _irq_none
        DATA R0, _irq_back        ; call it: the return address, a frame, the jump
        STK PUSH
        STK CALL
        JMRB R1
_irq_back:
        RJMP int_finish             ; R0 = its value
_irq_none:
        DATA R1, 0xAD               ; no handler: no interrupt sources
        COMM OUTADDR, R1
        DATA R1, 0
        COMM OUTDATA, R1
        DATA R0, 0
        RJMP int_finish

; TRAP vector
_trap:
        SAVE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        DATA R1, int_slots + 2
        LD R1, R1                   ; R1 = the C handler (0: none)
        TEST R1
        RJF Z, _trap_none
        DATA R0, _trap_back        ; call it: the return address, a frame, the jump
        STK PUSH
        STK CALL
        JMRB R1
_trap_back:
        RJMP int_finish             ; R0 = its value
_trap_none:
        DATA R0, 0
        RJMP int_finish

; FAULT vector (a PUSH or CALL past the stack limit)
_fault:
        SAVE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        DATA R1, int_slots + 3
        LD R1, R1                   ; R1 = the C handler (0: none)
        TEST R1
        RJF Z, _fault_none
        DATA R0, _fault_back        ; call it: the return address, a frame, the jump
        STK PUSH
        STK CALL
        JMRB R1
_fault_back:
        RJMP int_finish             ; R0 = its value
_fault_none:
        HALT

; R0 = the handler's value. The hardware word is 17 slots below ESP
; (16 saved registers above it).
int_finish:
        TEST R0
        RJF Z, int_restore
        CPY R0, R9                  ; R9 = the address to return to instead
        GSP R2
        ADD R2, #0xFFFFEF           ; RAM_BASE - 17: R0 = the word's address
        CPY R0, R2
        LD R2, R3                   ; R3 = the word
        AND R3, #0xFE000000         ; keep the flags and the two bits
        OR R0, R9
        ST R2, R0
int_restore:
        RESTORE R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15
        RTI
