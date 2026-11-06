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
 *
 * Claude (simulator only, Phase 8; tynix/bin/claude.c is the program that uses
 * it): device_out(CLAUDE_DEVICE, c) adds a char to the message, CLAUDE_SEND
 * (0) sends it, CLAUDE_NEW starts a new conversation, CLAUDE_STOP stops the
 * reply, CLAUDE_HELLO says a program starts using the device.
 * device_in(CLAUDE_DEVICE) is the next char of the reply: 0 none yet,
 * CLAUDE_END the turn is over, CLAUDE_TOOL a tool for the CPU follows (a
 * letter, fields split by CLAUDE_FIELD, then CLAUDE_STOP; answer with the
 * result's chars and CLAUDE_SEND). TECHNICAL 1.7 and 11.5.
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
#define CLAUDE_DEVICE 0x9C
#define MOUSE_STATE_DEVICE 0xBC
#define MOUSE_EVENT_DEVICE 0xBD

#define CLAUDE_SEND 0           /* the Claude device's control chars */
#define CLAUDE_TOOL 2
#define CLAUDE_STOP 3
#define CLAUDE_END 4
#define CLAUDE_HELLO 0x16
#define CLAUDE_NEW 0x18
#define CLAUDE_FIELD 0x1F

#define INT_NMI 0
#define INT_IRQ 1
#define INT_TRAP 2
#define INT_FAULT 3
#define IRQ_TIMER 1             /* bit masks of the controller's sources */
#define IRQ_KEYBOARD 2
#define IRQ_MOUSE 4

/* mouse_event()'s kinds; the buttons are 1 left, 2 right, 4 middle */
#define MOUSE_PRESS 1
#define MOUSE_RELEASE 2
#define MOUSE_WHEEL_UP 3
#define MOUSE_WHEEL_DOWN 4

/* what key_pressed() and wait_key() return besides printable ASCII, '\n'
   (Enter), '\b' (Backspace) and '\t' (Tab): the arrows, and Ctrl-A ...
   Ctrl-Z as 1 ... 26 (Ctrl-D is 4). Simulator only so far; getchar and scanf
   ignore them (and Tab). */
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

/* the mouse over the RGB screen (simulator only): mouse_state() gives the
   buttons (bit 3 set when the pointer is over the screen) and fills *x, *y
   (0-255); mouse_event() takes the next press, release or wheel step off a
   queue of 64 and returns its kind, 0 when empty, with the position in *x, *y
   and the buttons after it in *buttons */
int mouse_state(int *x, int *y);
int mouse_event(int *x, int *y, int *buttons);

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
