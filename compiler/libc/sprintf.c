/* sprintf, snprintf, vsprintf, vsnprintf: formatted output into a string */
#include <stdio.h>
#include "local.h"

int vsnprintf(char *buf, size_t size, const char *fmt, va_list ap)
{
    _Sink out;
    int n;
    out.file = 0;
    out.buf = buf;
    out.size = size;
    out.len = 0;
    n = _format(&out, fmt, ap);
    if (size > 0)
        buf[out.len < size ? out.len : size - 1] = 0;
    return n;
}

int vsprintf(char *buf, const char *fmt, va_list ap)
{
    return vsnprintf(buf, (size_t)-1 / 2, fmt, ap);
}

int snprintf(char *buf, size_t size, const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(buf, size, fmt, ap);
    va_end(ap);
    return n;
}

int sprintf(char *buf, const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(buf, (size_t)-1 / 2, fmt, ap);
    va_end(ap);
    return n;
}
