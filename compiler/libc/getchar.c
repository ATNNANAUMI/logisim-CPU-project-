/* getchar, ungetc: keyboard input, one line at a time.
 *
 * Like a terminal: the keys are shown as they are typed, backspace removes
 * the last one, and the program gets the line (with its '\n') after Enter.
 * Ctrl-D (0x04) at the start of a line is end of file.
 */
#include <stdio.h>
#include "local.h"

#define LINE_MAX 256
#define CTRL_D 4

static char line[LINE_MAX];
static int len;
static int pos;
static int at_eof;
static int pushed = EOF;

int _read_key(void)
{
    int c;
    do
        c = __builtin_in(_KEYBOARD);
    while (c == 0);
    return c;
}

static void read_line(void)
{
    len = pos = 0;
    for (;;) {
        int c = _read_key();
        if (c == CTRL_D) {
            if (len == 0) {
                at_eof = 1;
                return;
            }
            continue;
        }
        if (c == '\r')
            c = '\n';
        if (c == '\b' || c == 127) {
            if (len > 0) {
                len--;
                __builtin_out(_DISPLAY, '\b');
            }
            continue;
        }
        if (c == '\n') {
            __builtin_out(_DISPLAY, '\n');
            line[len++] = '\n';
            return;
        }
        if (len < LINE_MAX - 1) {
            line[len++] = c;
            __builtin_out(_DISPLAY, c);
        }
    }
}

int getchar(void)
{
    int c;
    if (pushed != EOF) {
        c = pushed;
        pushed = EOF;
        return c;
    }
    if (pos >= len) {
        if (at_eof)
            return EOF;
        read_line();
        if (len == 0)
            return EOF;
    }
    return (unsigned char)line[pos++];
}

int ungetc(int c, FILE *stream)
{
    (void)stream;
    if (c == EOF)
        return EOF;
    pushed = c;
    return c;
}

int _stdin_eof(void)
{
    return at_eof && pos >= len && pushed == EOF;
}

void _stdin_clear(void)
{
    at_eof = 0;
}

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
