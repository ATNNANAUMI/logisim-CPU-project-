/* _format: the engine behind printf, sprintf and friends.
 *
 * Supports %d %i %u %o %x %X %c %s %p %f %F %e %E %g %G %% and %n, the flags
 * - + space # 0, a width and a precision (numbers or *), and the length
 * modifiers hh h l ll j z t L (all ints are 32 bits, so they change nothing;
 * ll is accepted but the argument is still one 32-bit word).
 */
#include "local.h"

static void put(_Sink *out, int c)
{
    if (out->file)
        out->file->put(c, out->file);
    else if (out->buf == 0)
        __builtin_out(_DISPLAY, c);
    else if (out->len + 1 < out->size)
        out->buf[out->len] = c;
    out->len++;
}

static void pad(_Sink *out, int c, int n)
{
    while (n-- > 0)
        put(out, c);
}

/* prefix, zeros, body, with the field width applied */
static void field(_Sink *out, const char *prefix, int nprefix, int zeros,
                  const char *body, int nbody, int width, int left, int zero_pad)
{
    int total = nprefix + zeros + nbody;
    int i;
    if (zero_pad && !left && width > total) {
        zeros += width - total;
        total = width;
    }
    if (!left)
        pad(out, ' ', width - total);
    for (i = 0; i < nprefix; i++)
        put(out, prefix[i]);
    pad(out, '0', zeros);
    for (i = 0; i < nbody; i++)
        put(out, body[i]);
    if (left)
        pad(out, ' ', width - total);
}

/* the digits of v in a base, written backwards from the end of buf */
static int utoa(unsigned v, unsigned base, int upper, char *end)
{
    const char *digits = upper ? "0123456789ABCDEF" : "0123456789abcdef";
    int n = 0;
    do {
        *--end = digits[v % base];
        v /= base;
        n++;
    } while (v);
    return n;
}

#define F_LEFT 1
#define F_PLUS 2
#define F_SPACE 4
#define F_ALT 8
#define F_ZERO 16

/* %g: drop trailing zeros after the decimal point (and the point itself) */
static int strip_zeros(char *body, int n)
{
    int i, dot = -1;
    for (i = 0; i < n; i++)
        if (body[i] == '.')
            dot = i;
    if (dot < 0)
        return n;
    while (n > dot + 1 && body[n - 1] == '0')
        n--;
    if (n == dot + 1)
        n--;
    return n;
}

static void format_float(_Sink *out, float x, int prec, int conv, int flags, int width)
{
    char digits[160];
    char body[200];
    char prefix[1];
    int nprefix = 0;
    int nbody = 0;
    int upper = conv == 'F' || conv == 'E' || conv == 'G';
    int style = conv | 32;                   /* 'f', 'e' or 'g' */
    int strip = 0;
    union { float f; unsigned u; } bits;
    int point, n, i, e;

    bits.f = x;
    if (bits.u >> 31) {
        prefix[nprefix++] = '-';
        bits.u &= 0x7FFFFFFF;
    } else if (flags & F_PLUS) {
        prefix[nprefix++] = '+';
    } else if (flags & F_SPACE) {
        prefix[nprefix++] = ' ';
    }
    x = bits.f;
    if ((bits.u >> 23) == 255) {             /* infinity or NaN */
        const char *s = (bits.u & 0x7FFFFF) ? (upper ? "NAN" : "nan") : (upper ? "INF" : "inf");
        field(out, prefix, nprefix, 0, s, 3, width, flags & F_LEFT, 0);
        return;
    }
    if (prec < 0)
        prec = 6;
    if (prec > 120)
        prec = 120;

    if (style == 'g') {
        int p = prec ? prec : 1;
        n = _float_digits(x, digits, sizeof digits, &point, _SCIENTIFIC, p - 1);
        e = n ? point - 1 : 0;
        if (e < -4 || e >= p) {
            style = 'e';
            prec = p - 1;
        } else {
            style = 'f';
            prec = p - 1 - e;
            n = _float_digits(x, digits, sizeof digits, &point, _FIXED, prec);
        }
        strip = !(flags & F_ALT);
    } else if (style == 'e') {
        n = _float_digits(x, digits, sizeof digits, &point, _SCIENTIFIC, prec);
    } else {
        n = _float_digits(x, digits, sizeof digits, &point, _FIXED, prec);
    }

    if (style == 'f') {
        if (point <= 0)
            body[nbody++] = '0';
        for (i = 0; i < point; i++)
            body[nbody++] = i < n ? digits[i] : '0';
        if (prec > 0 || (flags & F_ALT)) {
            body[nbody++] = '.';
            for (i = 0; i < prec; i++) {
                int idx = point + i;
                body[nbody++] = (idx >= 0 && idx < n) ? digits[idx] : '0';
            }
        }
        if (strip)
            nbody = strip_zeros(body, nbody);
    } else {
        e = n ? point - 1 : 0;
        body[nbody++] = n ? digits[0] : '0';
        if (prec > 0 || (flags & F_ALT)) {
            body[nbody++] = '.';
            for (i = 1; i <= prec; i++)
                body[nbody++] = i < n ? digits[i] : '0';
        }
        if (strip)
            nbody = strip_zeros(body, nbody);
        body[nbody++] = upper ? 'E' : 'e';
        if (e < 0) {
            body[nbody++] = '-';
            e = -e;
        } else {
            body[nbody++] = '+';
        }
        if (e >= 100) {
            body[nbody++] = '0' + e / 100;
            e %= 100;
        }
        body[nbody++] = '0' + e / 10;
        body[nbody++] = '0' + e % 10;
    }
    field(out, prefix, nprefix, 0, body, nbody, width, flags & F_LEFT, flags & F_ZERO);
}

int _format(_Sink *out, const char *fmt, va_list ap)
{
    char buf[40];
    char prefix[3];
    while (*fmt) {
        int flags = 0, width = 0, prec = -1;
        int c = *fmt++;
        int nprefix = 0;
        if (c != '%') {
            put(out, c);
            continue;
        }
        for (;;) {                            /* flags */
            c = *fmt;
            if (c == '-') flags |= F_LEFT;
            else if (c == '+') flags |= F_PLUS;
            else if (c == ' ') flags |= F_SPACE;
            else if (c == '#') flags |= F_ALT;
            else if (c == '0') flags |= F_ZERO;
            else break;
            fmt++;
        }
        if (*fmt == '*') {                    /* width */
            width = va_arg(ap, int);
            if (width < 0) {
                flags |= F_LEFT;
                width = -width;
            }
            fmt++;
        } else {
            while (*fmt >= '0' && *fmt <= '9')
                width = width * 10 + (*fmt++ - '0');
        }
        if (*fmt == '.') {                    /* precision */
            fmt++;
            prec = 0;
            if (*fmt == '*') {
                prec = va_arg(ap, int);
                fmt++;
            } else {
                while (*fmt >= '0' && *fmt <= '9')
                    prec = prec * 10 + (*fmt++ - '0');
            }
        }
        while (*fmt == 'h' || *fmt == 'l' || *fmt == 'L' || *fmt == 'j' ||
               *fmt == 'z' || *fmt == 't' || *fmt == 'q')
            fmt++;                            /* length: everything is 32 bits */
        c = *fmt++;
        if (c == 0)
            break;
        switch (c) {
        case 'd':
        case 'i':
        case 'u':
        case 'o':
        case 'x':
        case 'X':
        case 'p': {
            unsigned v;
            int n, zeros = 0;
            char *end = buf + sizeof buf;
            if (c == 'p') {
                v = (unsigned)va_arg(ap, void *);
                prefix[nprefix++] = '0';
                prefix[nprefix++] = 'x';
                n = utoa(v, 16, 0, end);
            } else if (c == 'd' || c == 'i') {
                int s = va_arg(ap, int);
                v = s;
                if (s < 0) {
                    prefix[nprefix++] = '-';
                    v = -v;
                } else if (flags & F_PLUS) {
                    prefix[nprefix++] = '+';
                } else if (flags & F_SPACE) {
                    prefix[nprefix++] = ' ';
                }
                n = utoa(v, 10, 0, end);
            } else {
                unsigned base = c == 'u' ? 10 : c == 'o' ? 8 : 16;
                v = va_arg(ap, unsigned);
                n = utoa(v, base, c == 'X', end);
                if ((flags & F_ALT) && v != 0 && base == 16) {
                    prefix[nprefix++] = '0';
                    prefix[nprefix++] = c;
                }
            }
            if (prec >= 0) {
                flags &= ~F_ZERO;
                if (prec == 0 && v == 0 && c != 'p')
                    n = 0;
                if (prec > n)
                    zeros = prec - n;
            }
            if (c == 'o' && (flags & F_ALT) && zeros == 0 && (n == 0 || end[-n] != '0'))
                zeros = 1;
            field(out, prefix, nprefix, zeros, end - n, n, width, flags & F_LEFT,
                  flags & F_ZERO);
            break;
        }
        case 'c':
            buf[0] = va_arg(ap, int);
            field(out, prefix, 0, 0, buf, 1, width, flags & F_LEFT, 0);
            break;
        case 's': {
            const char *s = va_arg(ap, const char *);
            int n = 0;
            if (s == 0)
                s = "(null)";
            while (s[n] && (prec < 0 || n < prec))
                n++;
            field(out, prefix, 0, 0, s, n, width, flags & F_LEFT, 0);
            break;
        }
        case 'f':
        case 'F':
        case 'e':
        case 'E':
        case 'g':
        case 'G':
            format_float(out, va_arg(ap, double), prec, c, flags, width);
            break;
        case 'n':
            *va_arg(ap, int *) = out->len;
            break;
        case '%':
            put(out, '%');
            break;
        default:                              /* unknown: print it as is */
            put(out, '%');
            put(out, c);
            break;
        }
    }
    return out->len;
}
