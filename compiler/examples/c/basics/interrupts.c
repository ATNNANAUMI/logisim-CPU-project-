/* interrupts.c - the CPU's interrupts (Phase 6): the main program sleeps
 * while a timer tick and the keyboard are handled in the background.
 *
 *   python compiler/src/cc run compiler/examples/c/basics/interrupts.c --keys abc
 *
 * Expected output (the simulator only so far; the timer is real time, so
 * this takes half a second):
 *   keys typed before the first tick: abc
 *   tick 1
 *   tick 2
 *   tick 3
 *   tick 4
 *   tick 5
 *   5 ticks, stack pointer back where it was: yes
 *
 * The handler is an ordinary C function that returns 0 ("go back where the
 * program was"). It runs with interrupts off, and it acknowledges what it
 * served: the request stays until it does.
 */
#include <stdio.h>
#include <cpu.h>

#define TICKS 5

static int ticks;
static int nkeys;
static char typed[16];

static unsigned on_irq(void)
{
    unsigned pending = irq_pending();
    int c;
    if (pending & IRQ_KEYBOARD) {
        while ((c = key_pressed()) != 0 && nkeys < 15)
            typed[nkeys++] = c;
        irq_ack(IRQ_KEYBOARD);
    }
    if (pending & IRQ_TIMER) {
        ticks++;
        irq_ack(IRQ_TIMER);
    }
    return 0;
}

int main(void)
{
    int shown = 0;
    unsigned sp = stack_pointer(), after;
    set_interrupt_handler(INT_IRQ, on_irq);
    irq_enable(IRQ_TIMER | IRQ_KEYBOARD);
    timer_interrupt_every(100);
    interrupts_on();
    while (ticks < TICKS) {
        wait_for_interrupt();           /* asleep until the next interrupt */
        interrupts_off();               /* look at what the handler left */
        if (shown == 0 && nkeys > 0)
            printf("keys typed before the first tick: %s\n", typed);
        while (shown < ticks)
            printf("tick %d\n", ++shown);
        interrupts_on();
    }
    interrupts_off();
    after = stack_pointer();            /* (printf's arguments are on the stack too) */
    printf("%d ticks, stack pointer back where it was: %s\n", ticks,
           after == sp ? "yes" : "no");
    return 0;
}
