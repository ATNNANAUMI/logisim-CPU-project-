/* time, clock: clock() reads the timer, in milliseconds since reset (it
 * wraps after about 25 days of running as a long); there is no calendar, so
 * time() says "not available" (-1) */
#include <cpu.h>
#include <time.h>

time_t time(time_t *t)
{
    if (t)
        *t = -1;
    return -1;
}

clock_t clock(void)
{
    return device_in(TIMER_DEVICE);
}
