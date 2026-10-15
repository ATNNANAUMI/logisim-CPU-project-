/* exit, atexit */
#include <stdlib.h>

#define MAX_HANDLERS 32

static void (*handlers[MAX_HANDLERS])(void);
static int count;

int atexit(void (*func)(void))
{
    if (count == MAX_HANDLERS)
        return -1;
    handlers[count++] = func;
    return 0;
}

void exit(int status)
{
    while (count > 0)
        handlers[--count]();
    _Exit(status);
}
