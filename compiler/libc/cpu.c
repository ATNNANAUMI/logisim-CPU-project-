/* cpu.h: the hex display, direct keyboard access and waiting */
#include <cpu.h>

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
