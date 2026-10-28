/* fprintf, vfprintf: formatted output to stdout, stderr (the display) or a file */
#include <stdio.h>
#include "local.h"

int vfprintf(FILE *stream, const char *fmt, va_list ap)
{
    _Sink out;
    if (!stream->output) {
        stream->error = 1;
        return -1;
    }
    out.file = stream->put ? stream : 0;
    out.buf = 0;
    out.size = 0;
    out.len = 0;
    return _format(&out, fmt, ap);
}

int fprintf(FILE *stream, const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vfprintf(stream, fmt, ap);
    va_end(ap);
    return n;
}
