/* time.h - the CPU has no clock: time() and clock() report "not available" */
#ifndef _TIME_H
#define _TIME_H

#include <stddef.h>

typedef long time_t;
typedef long clock_t;
#define CLOCKS_PER_SEC 1000000L

time_t time(time_t *t);
clock_t clock(void);

#endif
