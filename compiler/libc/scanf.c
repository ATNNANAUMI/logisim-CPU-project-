/* scanf, sscanf, fscanf, vscanf, vsscanf, vfscanf: formatted input.
 *
 * Conversions: %d %i %u %o %x %X %c %s %[...] %f %e %g %E %G %n %%,
 * with * (read but don't store), a width, and the length modifiers
 * hh h l ll j z t L (all ints are 32 bits; float and double are the same).
 */
#include <stdio.h>
#include <stdlib.h>
#include "local.h"

typedef struct {
    const char *s;          /* a string to read, or 0 for a stream */
    FILE *f;                /* the stream: stdin or a file */
    int count;              /* characters read so far */
} In;

static int get(In *in)
{
    int c;
    if (in->s) {
        c = *in->s;
        if (c == 0)
            return EOF;
        in->s++;
    } else {
        c = in->f == stdin ? getchar() : fgetc(in->f);
        if (c == EOF)
            return EOF;
    }
    in->count++;
    return c;
}

static void unget(In *in, int c)
{
    if (c == EOF)
        return;
    in->count--;
    if (in->s)
        in->s--;
    else
        ungetc(c, in->f);
}

static int is_space(int c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f';
}

static int skip_space(In *in)
{
    int c;
    do
        c = get(in);
    while (is_space(c));
    unget(in, c);
    return c;
}

static int digit_value(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'z')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'Z')
        return c - 'A' + 10;
    return 99;
}

/* an integer in base (0: decimal, octal with 0, hex with 0x); 1 if read */
static int scan_int(In *in, int base, int width, unsigned *out)
{
    unsigned v = 0;
    int neg = 0, n = 0, c, digits = 0;
    if (width <= 0)
        width = 1 << 30;
    c = get(in);
    if ((c == '-' || c == '+') && n < width) {
        neg = c == '-';
        n++;
        c = get(in);
    }
    if ((base == 0 || base == 16) && c == '0' && n < width) {
        n++;
        digits = 1;
        c = get(in);
        if ((c == 'x' || c == 'X') && n < width) {
            int d = get(in);
            unget(in, d);
            if (digit_value(d) < 16) {
                base = 16;
                n++;
                c = get(in);
            } else if (base == 0) {
                base = 8;
            }
        } else if (base == 0) {
            base = 8;
        }
    }
    if (base == 0)
        base = 10;
    while (n < width && digit_value(c) < base) {
        v = v * base + digit_value(c);
        digits++;
        n++;
        c = get(in);
    }
    unget(in, c);
    if (!digits)
        return 0;
    *out = neg ? -v : v;
    return 1;
}

/* a floating number: collect its text, then strtod */
static int scan_float(In *in, int width, float *out)
{
    char buf[64];
    int n = 0, c, digits = 0;
    if (width <= 0 || width > 63)
        width = 63;
    c = get(in);
    if ((c == '-' || c == '+') && n < width) {
        buf[n++] = c;
        c = get(in);
    }
    while (c >= '0' && c <= '9' && n < width) {
        buf[n++] = c;
        digits++;
        c = get(in);
    }
    if (c == '.' && n < width) {
        buf[n++] = c;
        c = get(in);
        while (c >= '0' && c <= '9' && n < width) {
            buf[n++] = c;
            digits++;
            c = get(in);
        }
    }
    if (digits && (c == 'e' || c == 'E') && n < width) {
        int save = n;
        buf[n++] = c;
        c = get(in);
        if ((c == '-' || c == '+') && n < width) {
            buf[n++] = c;
            c = get(in);
        }
        if (c >= '0' && c <= '9') {
            while (c >= '0' && c <= '9' && n < width) {
                buf[n++] = c;
                c = get(in);
            }
        } else {
            n = save;       /* "1e" is just 1 (the 'e' can't be put back) */
        }
    }
    unget(in, c);
    if (!digits)
        return 0;
    buf[n] = 0;
    *out = strtod(buf, 0);
    return 1;
}

static int scan(In *in, const char *fmt, va_list ap)
{
    int assigned = 0;
    int conversions = 0;
    while (*fmt) {
        int c = *fmt++;
        int suppress = 0, width = 0, conv;
        if (is_space(c)) {
            skip_space(in);
            continue;
        }
        if (c != '%' || *fmt == '%') {
            int got;
            if (c == '%') {
                fmt++;
                skip_space(in);
            }
            got = get(in);
            if (got != c) {
                unget(in, got);
                return (got == EOF && conversions == 0) ? EOF : assigned;
            }
            continue;
        }
        if (*fmt == '*') {
            suppress = 1;
            fmt++;
        }
        while (*fmt >= '0' && *fmt <= '9')
            width = width * 10 + (*fmt++ - '0');
        while (*fmt == 'h' || *fmt == 'l' || *fmt == 'L' || *fmt == 'j' ||
               *fmt == 'z' || *fmt == 't' || *fmt == 'q')
            fmt++;
        conv = *fmt++;
        if (conv == 0)
            break;
        if (conv == 'n') {
            if (!suppress)
                *va_arg(ap, int *) = in->count;
            continue;
        }
        if (conv != 'c' && conv != '[') {
            if (skip_space(in) == EOF)
                return conversions == 0 ? EOF : assigned;
        }
        switch (conv) {
        case 'd': case 'i': case 'u': case 'o': case 'x': case 'X': {
            unsigned v;
            int base = conv == 'd' || conv == 'u' ? 10 : conv == 'o' ? 8 :
                       conv == 'i' ? 0 : 16;
            if (!scan_int(in, base, width, &v))
                return assigned;
            if (!suppress) {
                *va_arg(ap, unsigned *) = v;
                assigned++;
            }
            break;
        }
        case 'f': case 'e': case 'g': case 'E': case 'G': case 'a': case 'F': {
            float v;
            if (!scan_float(in, width, &v))
                return assigned;
            if (!suppress) {
                *va_arg(ap, float *) = v;
                assigned++;
            }
            break;
        }
        case 'c': {
            char *p = suppress ? 0 : va_arg(ap, char *);
            int i;
            if (width <= 0)
                width = 1;
            for (i = 0; i < width; i++) {
                int ch = get(in);
                if (ch == EOF)
                    return (i == 0 && conversions == 0) ? EOF : assigned;
                if (p)
                    p[i] = ch;
            }
            if (p)
                assigned++;
            break;
        }
        case 's': {
            char *p = suppress ? 0 : va_arg(ap, char *);
            int i = 0, ch;
            if (width <= 0)
                width = 1 << 30;
            ch = get(in);
            while (ch != EOF && !is_space(ch) && i < width) {
                if (p)
                    p[i] = ch;
                i++;
                ch = get(in);
            }
            unget(in, ch);
            if (p) {
                p[i] = 0;
                assigned++;
            }
            break;
        }
        case '[': {
            char *p = suppress ? 0 : va_arg(ap, char *);
            const char *set = fmt;
            int negate = 0, i = 0, ch;
            if (*set == '^') {
                negate = 1;
                set++;
            }
            fmt = set;
            if (*fmt == ']')
                fmt++;
            while (*fmt && *fmt != ']')
                fmt++;
            if (width <= 0)
                width = 1 << 30;
            ch = get(in);
            while (ch != EOF && i < width) {
                const char *q = set;
                int in_set = 0;
                if (*q == ']') {
                    in_set = ch == ']';
                    q++;
                }
                while (!in_set && q < fmt) {
                    if (q[1] == '-' && q + 2 < fmt) {
                        if (ch >= q[0] && ch <= q[2])
                            in_set = 1;
                        q += 3;
                    } else {
                        if (ch == *q)
                            in_set = 1;
                        q++;
                    }
                }
                if (in_set == negate)
                    break;
                if (p)
                    p[i] = ch;
                i++;
                ch = get(in);
            }
            unget(in, ch);
            if (*fmt == ']')
                fmt++;
            if (i == 0)
                return assigned;
            if (p) {
                p[i] = 0;
                assigned++;
            }
            break;
        }
        default:
            return assigned;
        }
        conversions++;
    }
    return assigned;
}

int vscanf(const char *fmt, va_list ap)
{
    return vfscanf(stdin, fmt, ap);
}

int vfscanf(FILE *stream, const char *fmt, va_list ap)
{
    In in;
    in.s = 0;
    in.f = stream;
    in.count = 0;
    return scan(&in, fmt, ap);
}

int vsscanf(const char *s, const char *fmt, va_list ap)
{
    In in;
    in.s = s;
    in.f = 0;
    in.count = 0;
    return scan(&in, fmt, ap);
}

int scanf(const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vscanf(fmt, ap);
    va_end(ap);
    return n;
}

int sscanf(const char *s, const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsscanf(s, fmt, ap);
    va_end(ap);
    return n;
}

int fscanf(FILE *stream, const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vfscanf(stream, fmt, ap);
    va_end(ap);
    return n;
}
