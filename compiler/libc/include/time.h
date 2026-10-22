/* time.h - clock() reads the timer (device 0x7C): milliseconds since reset.
 * There is no calendar, so time() reports "not available". */
#ifndef _TIME_H
#define _TIME_H

#include <stddef.h>

typedef long time_t;
typedef long clock_t;
#define CLOCKS_PER_SEC 1000L

time_t time(time_t *t);
clock_t clock(void);

#endif
