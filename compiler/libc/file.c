/* FILE: stdin is the keyboard, stdout and stderr are the display.
 * There is no disk: fopen always fails. */
#include <stdio.h>
#include "local.h"


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

