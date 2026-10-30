/* atoi, atol, strtol, strtoul */
#include <stdlib.h>
#include <limits.h>
#include <errno.h>

static int is_space(int c)
{
    return c == ' ' || (c >= '\t' && c <= '\r');
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

/* the common part: returns the magnitude, sets *neg and *overflow */
static unsigned long parse(const char *s, char **end, int base, int *neg, int *overflow)
{
    const char *p = s;
    unsigned long v = 0, limit, last;
    int digits = 0;
    *neg = 0;
    *overflow = 0;
    while (is_space(*p))
        p++;
    if (*p == '-' || *p == '+') {
        *neg = *p == '-';
        p++;
    }
    if ((base == 0 || base == 16) && p[0] == '0' && (p[1] == 'x' || p[1] == 'X') &&
        digit_value(p[2]) < 16) {
        p += 2;
        base = 16;
    } else if (base == 0) {
        base = p[0] == '0' ? 8 : 10;
    }
    limit = ULONG_MAX / base;                   /* v * base + d overflows when v > limit, */
    last = ULONG_MAX - limit * base;            /* or v == limit and d > last */
    while (digit_value(*p) < base) {
        unsigned long d = digit_value(*p);
        if (v > limit || (v == limit && d > last))
            *overflow = 1;
        v = v * base + d;
        digits++;
        p++;
    }
    if (end)
        *end = (char *)(digits ? p : s);
    return v;
}

long strtol(const char *s, char **end, int base)
{
    int neg, overflow;
    unsigned long v = parse(s, end, base, &neg, &overflow);
    if (neg) {
        if (overflow || v > (unsigned long)LONG_MAX + 1) {
            errno = ERANGE;
            return LONG_MIN;
        }
        return -(long)v;
    }
    if (overflow || v > LONG_MAX) {
        errno = ERANGE;
        return LONG_MAX;
    }
    return v;
}

unsigned long strtoul(const char *s, char **end, int base)
{
    int neg, overflow;
    unsigned long v = parse(s, end, base, &neg, &overflow);
    if (overflow) {
        errno = ERANGE;
        return ULONG_MAX;
    }
    return neg ? -v : v;
}

int atoi(const char *s)
{
    return (int)strtol(s, 0, 10);
}

long atol(const char *s)
{
    return strtol(s, 0, 10);
}
