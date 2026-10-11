/* atof, strtod, strtof: text to float.
 *
 * Up to 9 significant digits are kept exactly; when there are at most 8
 * (so the value is exact in a float) and the decimal exponent is between
 * -10 and 10, the result is correctly rounded (one exact power of ten). Other
 * numbers can be off in the last bit.
 */
#include <stdlib.h>
#include <errno.h>

static const float tens[] = {
    1e0f, 1e1f, 1e2f, 1e3f, 1e4f, 1e5f, 1e6f, 1e7f, 1e8f, 1e9f, 1e10f
};

static int is_space(int c)
{
    return c == ' ' || (c >= '\t' && c <= '\r');
}

static int lower(int c)
{
    return c >= 'A' && c <= 'Z' ? c + 32 : c;
}

static int match(const char *p, const char *word)
{
    int i = 0;
    while (word[i]) {
        if (lower(p[i]) != word[i])
            return 0;
        i++;
    }
    return i;
}

static float scale(float v, int exp10)
{
    /* v * 10^exp10, in as few roundings as the range allows */
    while (exp10 > 10) {
        v *= 1e10f;
        exp10 -= 10;
    }
    while (exp10 < -10) {
        v /= 1e10f;
        exp10 += 10;
    }
    if (exp10 >= 0)
        return v * tens[exp10];
    return v / tens[-exp10];
}

double strtod(const char *s, char **end)
{
    const char *p = s;
    unsigned mant = 0;
    int ndigits = 0, dropped = 0, exp10 = 0, neg = 0, any = 0, n;
    float v;
    while (is_space(*p))
        p++;
    if (*p == '-' || *p == '+') {
        neg = *p == '-';
        p++;
    }
    if ((n = match(p, "infinity")) || (n = match(p, "inf"))) {
        if (end)
            *end = (char *)(p + n);
        v = 1.0f / 0.0f;
        return neg ? -v : v;
    }
    if ((n = match(p, "nan"))) {
        if (end)
            *end = (char *)(p + n);
        return 0.0f / 0.0f;
    }
    while (*p >= '0' && *p <= '9') {
        any = 1;
        if (ndigits < 9) {
            if (mant || *p != '0') {
                mant = mant * 10 + (*p - '0');
                ndigits++;
            }
        } else {
            dropped++;
        }
        p++;
    }
    if (*p == '.') {
        p++;
        while (*p >= '0' && *p <= '9') {
            any = 1;
            if (ndigits < 9) {
                if (mant || *p != '0') {
                    mant = mant * 10 + (*p - '0');
                    ndigits++;
                }
                exp10--;
            }
            p++;
        }
    }
    if (!any) {
        if (end)
            *end = (char *)s;
        return 0.0f;
    }
    exp10 += dropped;
    if (*p == 'e' || *p == 'E') {
        const char *q = p + 1;
        int eneg = 0, e = 0;
        if (*q == '-' || *q == '+') {
            eneg = *q == '-';
            q++;
        }
        if (*q >= '0' && *q <= '9') {
            while (*q >= '0' && *q <= '9') {
                if (e < 10000)
                    e = e * 10 + (*q - '0');
                q++;
            }
            exp10 += eneg ? -e : e;
            p = q;
        }
    }
    if (end)
        *end = (char *)p;
    if (mant == 0)
        return neg ? -0.0f : 0.0f;
    if (exp10 > 50) {
        errno = ERANGE;
        v = 1.0f / 0.0f;
    } else if (exp10 < -60) {
        errno = ERANGE;
        v = 0.0f;
    } else {
        v = scale((float)mant, exp10);
    }
    return neg ? -v : v;
}

float strtof(const char *s, char **end)
{
    return strtod(s, end);
}

double atof(const char *s)
{
    return strtod(s, 0);
}
