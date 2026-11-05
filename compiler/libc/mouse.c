/* mouse_state, mouse_event: the mouse device (cpu.h, config.py in the
 * simulator): a word with x in bits 31-24, y in 23-16, the kind in 15-8
 * (events only) and the buttons in 2-0 (the state also has 8 when the
 * pointer is over the screen) */
#include <cpu.h>

int mouse_state(int *x, int *y)
{
    unsigned w = device_in(MOUSE_STATE_DEVICE);
    *x = w >> 24;
    *y = (w >> 16) & 0xFF;
    return w & 0xF;
}

int mouse_event(int *x, int *y, int *buttons)
{
    unsigned w = device_in(MOUSE_EVENT_DEVICE);
    *x = w >> 24;
    *y = (w >> 16) & 0xFF;
    *buttons = w & 7;
    return (w >> 8) & 0xFF;
}
