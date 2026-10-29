/* putchar: one character to stdout (the text display, or the file a shell's
   `>` gave a program: file.c's fputc follows stdout's put) */
#include <stdio.h>

int putchar(int c)
{
    return fputc(c, stdout);
}
