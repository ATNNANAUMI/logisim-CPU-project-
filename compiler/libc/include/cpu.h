/* cpu.h - things only this CPU has (not standard C)
 *
 *   show_hex(v)        show v on the 8-digit hex display (device 0x3C)
 *   key_pressed()      the next key if one was typed, else 0; no waiting,
 *                      no echo (getchar waits for a whole line)
 *   wait_key()         wait for one key and return it, no echo
 *   device_out(d, v)   send v to output device d (COMM OUTADDR/OUTDATA)
 *   device_in(d)       read one word from input device d (0 if it has none)
 *   wait_ms(ms)        do nothing for ms milliseconds (the timer, device 0x7C;
 *                      clock() in time.h reads it too)
 *   halt()             stop the CPU (RESUME continues after it)
 *
 * Interrupts (Phase 6; the simulator only so far). The CPU takes an interrupt
 * between two instructions, saves where it was and jumps to a vector; a
 * handler is a C function `unsigned handler(void)`, installed with
 * set_interrupt_handler(). It runs with interrupts off and with every
 * register saved; it returns 0 to go back where the program was, or an
 * address to go to instead (how the shell's NMI handler kills a program).
 *
 *   interrupts_on(), interrupts_off()   the enable bit (off at reset; the
 *                      start-up code of a program leaves it as it is)
 *   set_interrupt_handler(which, fn)    which: INT_NMI (the kill switch, not
 *                      masked), INT_IRQ (timer, keyboard: see irq_enable),
 *                      INT_TRAP (software_interrupt()), INT_FAULT (a PUSH or
 *                      CALL past the stack limit, set_stack_limit())
 *   irq_enable(mask), irq_ack(mask), irq_pending()   the interrupt controller
 *                      (device 0xAC/0xAD): sources IRQ_TIMER (bit 0) and
 *                      IRQ_KEYBOARD (bit 1); a handler must acknowledge its
 *                      source, or it is taken again after one instruction
 *   timer_interrupt_every(ms)           the timer raises IRQ_TIMER every ms
 *                      (0 = off)
 *   wait_for_interrupt()                sleep until an interrupt (WAIT); HALT
 *                      is the shutdown, only NMI or a reset wakes it
 *   set_stack_limit(address)            a PUSH/CALL at or past that RAM
 *                      address takes the fault vector (leave a few words
 *                      for the interrupt that tells you)
 *   stack_pointer()                     ESP as a RAM address
 * Programs for the OS (--exe) can't install handlers: the OS owns them.
 *
 * The disk (simulator only, run with --disk FILE): device_out(DISK_SEEK_DEVICE, n)
 * goes to word n; device_in(DISK_SEEK_DEVICE) is the disk's size in words.
 * device_out/device_in on DISK_DATA_DEVICE write/read one word and move on
 * to the next one. Past the end, reads give 0 and writes are dropped.
 * A formatted disk holds a filesystem (stdio.h's fopen, TFS1): raw writes
 * to it can break it.
 */
#ifndef _CPU_H
#define _CPU_H

#define DISPLAY_DEVICE 0x5C
#define HEX_DEVICE 0x3C
#define KEYBOARD_DEVICE 0xF0
#define TIMER_DEVICE 0x7C
#define DISK_SEEK_DEVICE 0x8C
#define DISK_DATA_DEVICE 0x8D
#define INT_ACK_DEVICE 0xAC
#define INT_ENABLE_DEVICE 0xAD

#define INT_NMI 0
#define INT_IRQ 1
#define INT_TRAP 2
#define INT_FAULT 3
#define IRQ_TIMER 1             /* bit masks of the controller's sources */
#define IRQ_KEYBOARD 2

/* what key_pressed() and wait_key() return besides printable ASCII, '\n'
   (Enter) and '\b' (Backspace): the arrows, and Ctrl-A ... Ctrl-Z as 1 ... 26
   (Ctrl-D is 4). Simulator only so far; getchar and scanf ignore them. */
#define KEY_UP 28
#define KEY_DOWN 29
#define KEY_LEFT 30
#define KEY_RIGHT 31
#define KEY_CTRL(letter) ((letter) & 0x1F)      /* KEY_CTRL('s') is 19 */

#define device_out(d, v) __builtin_out((d), (v))
#define device_in(d) __builtin_in(d)
#define halt() __builtin_trap()

void show_hex(unsigned int value);
int key_pressed(void);
int wait_key(void);
void wait_ms(unsigned int ms);

void interrupts_on(void);
void interrupts_off(void);
void set_interrupt_handler(int which, unsigned (*handler)(void));
void wait_for_interrupt(void);
void software_interrupt(void);
void irq_enable(unsigned mask);
void irq_ack(unsigned mask);
unsigned irq_pending(void);
void timer_interrupt_every(unsigned ms);
void set_stack_limit(unsigned address);
unsigned stack_pointer(void);

#endif
