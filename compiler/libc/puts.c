/* puts: a string and a newline to the text display */
#include <stdio.h>

int puts(const char *s)
{
    while (*s)
        __builtin_out(0x5C, *s++);
    __builtin_out(0x5C, '\n');
    return 0;
}
