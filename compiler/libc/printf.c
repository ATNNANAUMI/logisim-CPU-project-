/* printf, vprintf: formatted output to the display */
#include <stdio.h>
#include "local.h"

int vprintf(const char *fmt, va_list ap)
{
    _Sink out;
    out.buf = 0;
    out.size = 0;
    out.len = 0;
    return _format(&out, fmt, ap);
}

int printf(const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vprintf(fmt, ap);
    va_end(ap);
    return n;
}
