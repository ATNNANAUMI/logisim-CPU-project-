/* FILE: stdin is the keyboard, stdout and stderr are the display.
 * There is no disk: fopen always fails. */
#include <stdio.h>
#include "local.h"

struct _FILE {
    int output;          /* 1 for stdout/stderr */
    int eof;
    int error;
};

static struct _FILE in_file = { 0, 0, 0 };
static struct _FILE out_file = { 1, 0, 0 };
static struct _FILE err_file = { 1, 0, 0 };

FILE *stdin = &in_file;
FILE *stdout = &out_file;
FILE *stderr = &err_file;

int fputc(int c, FILE *stream)
{
    if (!stream->output) {
        stream->error = 1;
        return EOF;
    }
    __builtin_out(_DISPLAY, c);
    return c;
}

int putc(int c, FILE *stream)
{
    return fputc(c, stream);
}

int fputs(const char *s, FILE *stream)
{
    if (!stream->output) {
        stream->error = 1;
        return EOF;
    }
    while (*s)
        __builtin_out(_DISPLAY, *s++);
    return 0;
}

int vfprintf(FILE *stream, const char *fmt, va_list ap)
{
    _Sink out;
    if (!stream->output) {
        stream->error = 1;
        return -1;
    }
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

int fflush(FILE *stream)
{
    (void)stream;
    return 0;
}

size_t fwrite(const void *ptr, size_t size, size_t count, FILE *stream)
{
    const char *p = ptr;
    size_t i, n = size * count;
    if (!stream->output) {
        stream->error = 1;
        return 0;
    }
    for (i = 0; i < n; i++)
        __builtin_out(_DISPLAY, p[i]);
    return count;
}

int feof(FILE *stream)
{
    return stream->eof;
}

int ferror(FILE *stream)
{
    return stream->error;
}

void _stdin_clear(void);

void clearerr(FILE *stream)
{
    stream->eof = 0;
    stream->error = 0;
    if (stream == stdin)
        _stdin_clear();
}

FILE *fopen(const char *path, const char *mode)
{
    (void)path;
    (void)mode;
    return 0;
}

int fclose(FILE *stream)
{
    (void)stream;
    return 0;
}

int remove(const char *path)
{
    (void)path;
    return -1;
}

int rename(const char *from, const char *to)
{
    (void)from;
    (void)to;
    return -1;
}

void perror(const char *s)
{
    if (s && *s) {
        fputs(s, stderr);
        fputs(": ", stderr);
    }
    fputs("error\n", stderr);
}

/* the input side: see getchar.c */
int fgetc(FILE *stream)
{
    int c;
    if (stream->output) {
        stream->error = 1;
        return EOF;
    }
    c = getchar();
    if (c == EOF)
        stream->eof = 1;
    return c;
}

int getc(FILE *stream)
{
    return fgetc(stream);
}

char *fgets(char *buf, int size, FILE *stream)
{
    int n = 0;
    if (size <= 0)
        return 0;
    while (n < size - 1) {
        int c = fgetc(stream);
        if (c == EOF)
            break;
        buf[n++] = c;
        if (c == '\n')
            break;
    }
    if (n == 0)
        return 0;
    buf[n] = 0;
    return buf;
}

size_t fread(void *ptr, size_t size, size_t count, FILE *stream)
{
    char *p = ptr;
    size_t i, n = size * count;
    for (i = 0; i < n; i++) {
        int c = fgetc(stream);
        if (c == EOF)
            break;
        p[i] = c;
    }
    return size ? i / size : 0;
}

int fscanf(FILE *stream, const char *fmt, ...)
{
    va_list ap;
    int n;
    (void)stream;
    va_start(ap, fmt);
    n = vscanf(fmt, ap);
    va_end(ap);
    return n;
}
