/* _float_digits: the exact decimal digits of a float.
 *
 * A float is m * 2^e with m < 2^24. The integer part is converted exactly
 * (base-10000 arithmetic when it is above 2^32), and the fraction, which is
 * at most 149 binary places long, is held exactly as a 160-bit binary
 * fraction in ten 16-bit pieces; multiplying it by 10 gives the next digit.
 * Rounding is to nearest with ties to even, on the exact value, like glibc.
 */
#include "local.h"

#define LIMBS 12                 /* 10 used: bits 0..159; 2 spare */

typedef struct {
    char ip[48];                 /* integer part, most significant digit first */
    int ni;                      /* how many integer digits (0 when it is 0) */
    int next_ip;                 /* the next integer digit to hand out */
    unsigned frac[LIMBS];        /* fraction * 2^160, 16 bits per word, frac[0] lowest */
    int low;                     /* frac[0 .. low-1] are known to be 0 */
} Source;

/* integer part: digits of m * 2^e (e >= 0) or m >> -e */
static void integer_part(Source *s, unsigned m, int e)
{
    char tmp[48];
    int n = 0, i;
    if (e < 0) {
        unsigned v = -e >= 24 ? 0 : m >> -e;
        while (v) {
            tmp[n++] = '0' + v % 10;
            v /= 10;
        }
    } else {
        /* base-10000 pieces, lowest first */
        unsigned piece[12];
        int np = 0;
        unsigned v = m;
        while (v) {
            piece[np++] = v % 10000;
            v /= 10000;
        }
        while (e > 0) {
            int step = e > 13 ? 13 : e;
            unsigned mul = 1u << step;
            unsigned carry = 0;
            for (i = 0; i < np; i++) {
                unsigned t = piece[i] * mul + carry;
                piece[i] = t % 10000;
                carry = t / 10000;
            }
            while (carry) {
                piece[np++] = carry % 10000;
                carry /= 10000;
            }
            e -= step;
        }
        for (i = 0; i < np; i++) {
            unsigned p = piece[i];
            int k;
            for (k = 0; k < 4; k++) {
                tmp[n++] = '0' + p % 10;
                p /= 10;
            }
        }
        while (n > 0 && tmp[n - 1] == '0')
            n--;
    }
    s->ni = n;
    for (i = 0; i < n; i++)
        s->ip[i] = tmp[n - 1 - i];
    s->next_ip = 0;
}

/* fraction part: (m mod 2^k) / 2^k with k = -e, stored as fraction * 2^160 */
static void fraction_part(Source *s, unsigned m, int e)
{
    int i;
    for (i = 0; i < LIMBS; i++)
        s->frac[i] = 0;
    s->low = LIMBS;
    if (e >= 0)
        return;
    {
        int k = -e;
        unsigned f = k >= 24 ? m : m & ((1u << k) - 1);
        int shift = 160 - k;         /* f << shift */
        int li = shift / 16;
        int bo = shift % 16;
        unsigned lo = (f & 0xFFFF) << bo;
        unsigned hi = (f >> 16) << bo;
        s->frac[li] += lo & 0xFFFF;
        s->frac[li + 1] += (lo >> 16) + (hi & 0xFFFF);
        s->frac[li + 2] += hi >> 16;
        for (i = li; i < LIMBS - 1; i++) {        /* carry */
            s->frac[i + 1] += s->frac[i] >> 16;
            s->frac[i] &= 0xFFFF;
        }
        s->low = li;
    }
}

static int fraction_digit(Source *s)
{
    unsigned carry = 0;
    int i;
    while (s->low < 10 && s->frac[s->low] == 0)
        s->low++;
    for (i = s->low; i < 10; i++) {
        unsigned t = s->frac[i] * 10 + carry;
        s->frac[i] = t & 0xFFFF;
        carry = t >> 16;
    }
    return carry;
}

static int next_digit(Source *s)
{
    if (s->next_ip < s->ni)
        return s->ip[s->next_ip++] - '0';
    return fraction_digit(s);
}

static int rest_nonzero(Source *s)
{
    int i;
    for (i = s->next_ip; i < s->ni; i++)
        if (s->ip[i] != '0')
            return 1;
    for (i = 0; i < 10; i++)
        if (s->frac[i])
            return 1;
    return 0;
}

int _float_digits(float x, char *digits, int max, int *point, int mode, int prec)
{
    union { float f; unsigned u; } b;
    Source s;
    unsigned m, E;
    int e, n, want, guard, sticky, i, up;

    b.f = x;
    b.u &= 0x7FFFFFFF;
    E = b.u >> 23;
    m = b.u & 0x7FFFFF;
    if (E == 0) {
        if (m == 0) {
            *point = 1;
            return 0;
        }
        e = -149;
    } else {
        m |= 0x800000;
        e = E - 150;
    }
    integer_part(&s, m, e);
    fraction_part(&s, m, e);

    if (mode == _FIXED) {
        /* the integer digits, then prec fraction digits */
        *point = s.ni;
        want = s.ni + prec;
    } else {
        /* from the first non-zero digit: prec + 1 of them */
        if (s.ni > 0) {
            *point = s.ni;
        } else {
            int zeros = 0;
            int d = fraction_digit(&s);
            while (d == 0) {
                zeros++;
                d = fraction_digit(&s);
            }
            *point = -zeros;
            digits[0] = '0' + d;
        }
        want = prec + 1;
    }
    if (want > max - 1)
        want = max - 1;
    n = 0;
    if (mode != _FIXED && s.ni == 0)
        n = 1;                       /* the first digit is already there */
    while (n < want)
        digits[n++] = '0' + next_digit(&s);
    guard = next_digit(&s);
    sticky = rest_nonzero(&s);

    up = guard > 5 || (guard == 5 && (sticky || (n > 0 && (digits[n - 1] - '0') % 2)));
    if (up) {
        i = n - 1;
        while (i >= 0 && digits[i] == '9') {
            digits[i] = '0';
            i--;
        }
        if (i >= 0) {
            digits[i]++;
        } else {
            /* carried out of the first digit: 999 -> 1000 */
            for (i = n; i > 0; i--)
                digits[i] = digits[i - 1];
            digits[0] = '1';
            *point += 1;
            if (mode == _FIXED)
                n++;
        }
    }
    return n;
}
