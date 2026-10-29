/* puts: a string and a newline to stdout (see putchar.c) */
#include <stdio.h>

int puts(const char *s)
{
    fputs(s, stdout);
    fputc('\n', stdout);
    return 0;
}
