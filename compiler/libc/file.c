/* FILE: stdin is the keyboard, stdout and stderr are the display. Files on
 * the disk (fs.c) carry their own get/put/flush, which these call. */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "local.h"


static struct _FILE in_file = { 0, 0, 0 };
static struct _FILE out_file = { 1, 0, 0 };
static struct _FILE err_file = { 1, 0, 0 };

FILE *stdin = &in_file;
FILE *stdout = &out_file;
FILE *stderr = &err_file;

int fputc(int c, FILE *stream)
{
    if (stream->put)
        return stream->put(c, stream);
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
    if (stream->put) {
        while (*s)
            if (stream->put(*s++, stream) == EOF)
                return EOF;
        return 0;
    }
    if (!stream->output) {
        stream->error = 1;
        return EOF;
    }
    while (*s)
        __builtin_out(_DISPLAY, *s++);
    return 0;
}

/* fflush(0) does nothing: open files are saved at exit anyway */
int fflush(FILE *stream)
{
    if (stream && stream->flush)
        return stream->flush(stream);
    return 0;
}

size_t fwrite(const void *ptr, size_t size, size_t count, FILE *stream)
{
    const char *p = ptr;
    size_t i, n = size * count;
    if (stream->put) {
        for (i = 0; i < n; i++)
            if (stream->put(p[i], stream) == EOF)
                break;
        return size ? i / size : 0;
    }
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

void perror(const char *s)
{
    if (s && *s) {
        fputs(s, stderr);
        fputs(": ", stderr);
    }
    fputs(strerror(errno), stderr);
    fputs("\n", stderr);
}

