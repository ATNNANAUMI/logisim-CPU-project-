/* putchar: one character to the text display */
#include <stdio.h>

int putchar(int c)
{
    __builtin_out(0x5C, c);
    return c;
}
