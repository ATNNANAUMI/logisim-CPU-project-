/* time, clock: the CPU has no clock, so both say "not available" (-1) */
#include <time.h>

time_t time(time_t *t)
{
    if (t)
        *t = -1;
    return -1;
}

clock_t clock(void)
{
    return -1;
}
