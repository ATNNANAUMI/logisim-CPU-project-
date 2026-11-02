/* cpu.c for a program for Tynix: the same functions as compiler/libc/cpu.c,
 * but the keyboard is the kernel's (only the foreground program reads it,
 * and a program that waits for a key sleeps meanwhile), wait_ms() sleeps,
 * and gfx_ calls wait for the foreground. */
#include <cpu.h>
#include <gfx.h>
#include <sys/tynix.h>
#include "../local.h"

extern unsigned *_tx_block;
int _syscall(int n, int a, int b, int c, int d);

/* gfx.h: before each drawing, a program in the background waits */
static void hold(void)
{
    if (*(int *)_tx_block[B_FG] != (int)_tx_block[B_PID])
        _syscall(SYS_WAITFG, 0, 0, 0, 0);
}

void (*_gfx_hold)(void) = hold;

int gfx_lost(void)
{
    if (_tx_block[B_LOST]) {
        _tx_block[B_LOST] = 0;
        return 1;
    }
    return 0;
}

int _read_key(void)
{
    return _syscall(SYS_GETKEY, 1, 0, 0, 0);
}

void show_hex(unsigned int value)
{
    __builtin_out(HEX_DEVICE, value);
}

int key_pressed(void)
{
    return _syscall(SYS_GETKEY, 0, 0, 0, 0);
}

int wait_key(void)
{
    return _syscall(SYS_GETKEY, 1, 0, 0, 0);
}

void wait_ms(unsigned int ms)
{
    _syscall(SYS_SLEEP, ms, 0, 0, 0);
}

void irq_enable(unsigned mask)
{
    __builtin_out(INT_ENABLE_DEVICE, mask);
}

void irq_ack(unsigned mask)
{
    __builtin_out(INT_ACK_DEVICE, mask);
}

unsigned irq_pending(void)
{
    return __builtin_in(INT_ACK_DEVICE) & 0xFF;
}

void timer_interrupt_every(unsigned ms)
{
    __builtin_out(TIMER_DEVICE, ms);
}
