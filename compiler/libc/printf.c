/* printf, vprintf: formatted output to stdout (the display, or the file a
   shell's `>` gave a program: then stdout has a put function) */
#include <stdio.h>
#include "local.h"

int vprintf(const char *fmt, va_list ap)
{
    _Sink out;
    out.file = stdout->put ? stdout : 0;
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
