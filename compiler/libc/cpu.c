/* cpu.h: the hex display, direct keyboard access and waiting. A program for
 * Tynix gets compiler/libc/tynix/cpu.c instead (the keys and the waiting go
 * through the kernel). */
#include <cpu.h>
#include <gfx.h>
#include "local.h"

void (*_gfx_hold)(void);        /* gfx.h: 0 here (nothing to wait for) */

int gfx_lost(void)
{
    return 0;
}

/* getchar's key: wait for one, no echo (local.h) */
int _read_key(void)
{
    int c;
    do
        c = __builtin_in(_KEYBOARD);
    while (c == 0);
    return c;
}

void show_hex(unsigned int value)
{
    __builtin_out(HEX_DEVICE, value);
}

int key_pressed(void)
{
    return __builtin_in(KEYBOARD_DEVICE);
}

int wait_key(void)
{
    int c;
    do
        c = __builtin_in(KEYBOARD_DEVICE);
    while (c == 0);
    return c;
}

void wait_ms(unsigned int ms)
{
    unsigned int start = __builtin_in(TIMER_DEVICE);
    while ((unsigned int)__builtin_in(TIMER_DEVICE) - start < ms)
        ;
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
