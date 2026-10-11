/* cpu.h: the hex display and direct keyboard access */
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
