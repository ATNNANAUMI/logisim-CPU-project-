/* math.h on the CPU's 32-bit floats.
 *
 * The float unit adds, subtracts, multiplies and divides (correctly
 * rounded). Everything else is built here:
 *   - exact: fabs, copysign, floor, ceil, trunc, round, rint, fmod, frexp,
 *     ldexp, modf, fmin, fmax, sqrt (correctly rounded, bit by bit)
 *   - about 1-2 units in the last place: exp, log, sin, cos, tan, atan,
 *     asin, acos, atan2, sinh, cosh, tanh, cbrt, hypot
 *   - pow: exact for an integer exponent (when the result fits); otherwise
 *     exp(y * log(x)), a few units in the last place
 * sin/cos/tan reduce any argument exactly (Payne-Hanek above 100).
 */
#include <math.h>
#include <errno.h>

typedef union { float f; unsigned u; int i; } Bits;

static float from_bits(unsigned u)
{
    Bits b;
    b.u = u;
    return b.f;
}

static unsigned to_bits(float f)
{
    Bits b;
    b.f = f;
    return b.u;
}

int __fpclassify(double x)
{
    unsigned u = to_bits(x) & 0x7FFFFFFF;
    if (u == 0)
        return FP_ZERO;
    if (u < 0x00800000)
        return FP_SUBNORMAL;
    if (u < 0x7F800000)
        return FP_NORMAL;
    return u == 0x7F800000 ? FP_INFINITE : FP_NAN;
}

int __signbit(double x)
{
    return to_bits(x) >> 31;
}

double fabs(double x)
{
    return from_bits(to_bits(x) & 0x7FFFFFFF);
}

double copysign(double x, double y)
{
    return from_bits((to_bits(x) & 0x7FFFFFFF) | (to_bits(y) & 0x80000000));
}

/* ---------------------------------------------------------------- rounding */

double trunc(double x)
{
    unsigned u = to_bits(x);
    if ((u & 0x7FFFFFFF) >= 0x4B000000)      /* |x| >= 2^23 (or inf/nan): whole */
        return x;
    return copysign((float)(int)x, x);       /* keeps -0.0 for -0.5 */
}

double floor(double x)
{
    float t = trunc(x);
    return t > x ? t - 1.0f : t;
}

double ceil(double x)
{
    float t = trunc(x);
    return t < x ? t + 1.0f : t;
}

double round(double x)
{
    float t = trunc(x);
    float d = x - t;                         /* exact */
    if (d >= 0.5f)
        return t + 1.0f;
    if (d <= -0.5f)
        return t - 1.0f;
    return t;
}

double rint(double x)                        /* ties to even, like the FPU's rounding */
{
    float t = trunc(x);
    float d = x - t;
    float half = fabs(d);
    if (half > 0.5f || (half == 0.5f && fmod(t, 2.0f) != 0.0f))
        return d > 0 ? t + 1.0f : t - 1.0f;
    return t;
}

double nearbyint(double x)
{
    return rint(x);
}

long lround(double x)
{
    return (long)round(x);
}

long lrint(double x)
{
    return (long)rint(x);
}

double modf(double x, double *ip)
{
    float t = trunc(x);
    *ip = t;
    if (__fpclassify(x) == FP_INFINITE)
        return copysign(0.0f, x);
    return copysign(x - t, x);
}

double fmin(double x, double y)
{
    if (x != x)
        return y;
    if (y != y)
        return x;
    return x < y ? x : y;
}

double fmax(double x, double y)
{
    if (x != x)
        return y;
    if (y != y)
        return x;
    return x > y ? x : y;
}

double fdim(double x, double y)
{
    return x > y ? x - y : 0.0f;
}

double fma(double x, double y, double z)
{
    return x * y + z;                        /* not fused: two roundings */
}

/* ---------------------------------------------------------------- exponent fields */

double ldexp(double x, int n)
{
    unsigned u = to_bits(x);
    int e = (u >> 23) & 0xFF;
    if (e == 0xFF || (u & 0x7FFFFFFF) == 0)
        return x;
    /* scale in steps the float can represent exactly */
    while (n > 127) {
        x *= 1.7014118e38f;                  /* 2^127 */
        n -= 127;
        if (__fpclassify(x) == FP_INFINITE)
            return x;
    }
    while (n < -126) {
        x *= 1.1754944e-38f;                 /* 2^-126 */
        n += 126;
        if (x == 0.0f)
            return x;
    }
    return x * from_bits((unsigned)(n + 127) << 23);
}

double scalbn(double x, int n)
{
    return ldexp(x, n);
}

double frexp(double x, int *exp)
{
    unsigned u = to_bits(x);
    int e = (u >> 23) & 0xFF;
    if ((u & 0x7FFFFFFF) == 0 || e == 0xFF) {
        *exp = 0;
        return x;
    }
    if (e == 0) {                            /* subnormal: normalise first */
        x *= 16777216.0f;                    /* 2^24 */
        u = to_bits(x);
        e = ((u >> 23) & 0xFF) - 24;
    }
    *exp = e - 126;
    return from_bits((u & 0x807FFFFF) | 0x3F000000);   /* in [0.5, 1) */
}

int ilogb(double x)
{
    int e;
    if (x == 0.0f)
        return -2147483647 - 1;
    frexp(x, &e);
    return e - 1;
}

double logb(double x)
{
    if (x == 0.0f)
        return -1.0f / 0.0f;
    return (float)ilogb(x);
}

double nextafter(double x, double y)
{
    unsigned u;
    if (x != x || y != y)
        return x + y;
    if (x == y)
        return y;
    if (x == 0.0f)
        return copysign(from_bits(1), y);
    u = to_bits(x);
    if ((x < y) == (x > 0.0f))
        u++;
    else
        u--;
    return from_bits(u);
}

/* ---------------------------------------------------------------- fmod: exact */

double fmod(double x, double y)
{
    unsigned ux = to_bits(x), uy = to_bits(y);
    unsigned sx = ux & 0x80000000;
    int ex = (ux >> 23) & 0xFF, ey = (uy >> 23) & 0xFF;
    unsigned mx, my, i;
    ux &= 0x7FFFFFFF;
    uy &= 0x7FFFFFFF;
    if (uy == 0 || uy > 0x7F800000 || ex == 0xFF)
        return (x * y) / (x * y);            /* NaN */
    if (ux <= uy)
        return ux == uy ? from_bits(sx) : x;
    /* mantissas with the hidden bit; subnormals normalised */
    if (ex == 0) {
        for (i = ux << 9; !(i >> 31); i <<= 1)
            ex--;
        mx = ux << (1 - ex);
    } else {
        mx = (ux & 0x7FFFFF) | 0x800000;
    }
    if (ey == 0) {
        for (i = uy << 9; !(i >> 31); i <<= 1)
            ey--;
        my = uy << (1 - ey);
    } else {
        my = (uy & 0x7FFFFF) | 0x800000;
    }
    /* long division, keeping only the remainder */
    for (; ex > ey; ex--) {
        if (mx >= my) {
            mx -= my;
            if (mx == 0)
                return from_bits(sx);
        }
        mx <<= 1;
    }
    if (mx >= my) {
        mx -= my;
        if (mx == 0)
            return from_bits(sx);
    }
    while (!(mx >> 23)) {
        mx <<= 1;
        ex--;
    }
    if (ex > 0)
        mx = (mx - 0x800000) | ((unsigned)ex << 23);
    else
        mx >>= 1 - ex;
    return from_bits(mx | sx);
}

double remainder(double x, double y)
{
    float r = fmod(x, y);
    float ay = fabs(y);
    if (fabs(r) * 2.0f > ay || (fabs(r) * 2.0f == ay && fmod((x - r) / y, 2.0f) != 0.0f))
        r = r > 0 ? r - ay : r + ay;
    return r;
}

/* ---------------------------------------------------------------- sqrt: exact */

double sqrt(double x)
{
    unsigned ix = to_bits(x);
    unsigned q, s, r, t;
    int m;
    if ((ix & 0x7FFFFFFF) == 0)
        return x;                            /* +-0 */
    if (ix & 0x80000000) {
        errno = EDOM;
        return 0.0f / 0.0f;                  /* negative: NaN */
    }
    if (ix >= 0x7F800000)
        return x;                            /* inf, NaN */
    m = ix >> 23;
    if (m == 0) {                            /* subnormal: normalise */
        while (!(ix & 0x800000)) {
            ix <<= 1;
            m--;
        }
        m++;
    }
    m -= 127;
    ix = (ix & 0x7FFFFF) | 0x800000;
    if (m & 1)
        ix += ix;                            /* odd exponent: double the mantissa */
    m = (m - (m & 1)) / 2;
    /* the root, one bit at a time (with one extra bit for rounding) */
    ix += ix;
    q = s = 0;
    r = 0x1000000;
    while (r) {
        t = s + r;
        if (t <= ix) {
            s = t + r;
            ix -= t;
            q += r;
        }
        ix += ix;
        r >>= 1;
    }
    if (ix)
        q += q & 1;                          /* round to nearest */
    ix = (q >> 1) + 0x3F000000;
    ix += (unsigned)m << 23;
    return from_bits(ix);
}

double hypot(double x, double y)
{
    float a = fabs(x), b = fabs(y), t;
    if (__fpclassify(a) == FP_INFINITE || __fpclassify(b) == FP_INFINITE)
        return 1.0f / 0.0f;
    if (a < b) {
        t = a;
        a = b;
        b = t;
    }
    if (a == 0.0f)
        return 0.0f;
    t = b / a;
    return a * sqrt(1.0f + t * t);
}

double cbrt(double x)
{
    float a = fabs(x), y;
    int e, i;
    if (a == 0.0f || __fpclassify(a) == FP_INFINITE || x != x)
        return x;
    /* first guess from the exponent, then Newton steps */
    a = frexp(a, &e);                        /* a in [0.5, 1) */
    while (e % 3) {
        a *= 2.0f;
        e--;
    }
    y = 0.6f + 0.4f * a;
    for (i = 0; i < 5; i++)
        y = y - (y * y * y - a) / (3.0f * y * y);
    y = ldexp(y, e / 3);
    return x < 0 ? -y : y;
}

/* ---------------------------------------------------------------- exp, log */

#define LN2_HI 6.9314575195e-01f            /* ln 2 split so k * LN2_HI is exact */
#define LN2_LO 1.4286067653e-06f
#define INV_LN2 1.4426950216e+00f

/* exp(r) for |r| <= ln2/2 */
static float exp_small(float r)
{
    return 1.0f + r * (1.0f + r * (0.5f + r * (1.6666667163e-01f + r * (4.1666667908e-02f +
           r * (8.3333337680e-03f + r * (1.3888889225e-03f + r * 1.9841270114e-04f))))));
}

double exp(double x)
{
    float k, r;
    if (x != x)
        return x;
    if (x > 88.7228f) {
        errno = ERANGE;
        return 1.0f / 0.0f;
    }
    if (x < -103.972f)
        return 0.0f;
    k = floor(x * INV_LN2 + 0.5f);
    r = (x - k * LN2_HI) - k * LN2_LO;
    return ldexp(exp_small(r), (int)k);
}

double exp2(double x)
{
    float k, r;
    if (x != x)
        return x;
    if (x >= 128.0f)
        return 1.0f / 0.0f;
    if (x < -150.0f)
        return 0.0f;
    k = floor(x + 0.5f);
    r = (x - k) * M_LN2;
    return ldexp(exp_small(r), (int)k);
}

double expm1(double x)
{
    if (fabs(x) < 0.3465736f) {              /* small: avoid the cancellation */
        float r = x;
        return r * (1.0f + r * (0.5f + r * (1.6666667163e-01f + r * (4.1666667908e-02f +
               r * (8.3333337680e-03f + r * (1.3888889225e-03f + r * 1.9841270114e-04f))))));
    }
    return exp(x) - 1.0f;
}

/* log(1 + f) for f in [sqrt(2)/2 - 1, sqrt(2) - 1], with s = f / (2 + f) */
static float log_small(float f)
{
    float s = f / (2.0f + f);
    float z = s * s;
    return 2.0f * s * (1.0f + z * (3.3333334327e-01f + z * (2.0000000298e-01f +
           z * (1.4285714924e-01f + z * (1.1111111194e-01f + z * 9.0909093618e-02f)))));
}

double log(double x)
{
    int e;
    float m, f;
    if (x != x)
        return x;
    if (x < 0.0f) {
        errno = EDOM;
        return 0.0f / 0.0f;
    }
    if (x == 0.0f) {
        errno = ERANGE;
        return -1.0f / 0.0f;
    }
    if (__fpclassify(x) == FP_INFINITE)
        return x;
    m = frexp(x, &e);                        /* x = m * 2^e, m in [0.5, 1) */
    if (m < 0.70710678f) {
        m *= 2.0f;
        e--;
    }
    f = m - 1.0f;
    return e * LN2_HI + (log_small(f) + e * LN2_LO);
}

double log2(double x)
{
    int e;
    float m;
    if (x <= 0.0f || x != x || __fpclassify(x) == FP_INFINITE)
        return log(x);
    m = frexp(x, &e);
    if (m == 0.5f)
        return (float)(e - 1);              /* powers of two: exact */
    if (m < 0.70710678f) {
        m *= 2.0f;
        e--;
    }
    return e + log_small(m - 1.0f) * M_LOG2E;
}

double log10(double x)
{
    float r = log(x) * M_LOG10E;
    /* powers of ten come out exact */
    float n = round(r);
    if (fabs(r - n) < 1e-5f && n >= 0.0f && n <= 10.0f) {
        float p = 1.0f;
        int i;
        for (i = 0; i < (int)n; i++)
            p *= 10.0f;
        if (p == x)
            return n;
    }
    return r;
}

double log1p(double x)
{
    if (fabs(x) < 0.29f)
        return log_small(x);
    return log(1.0f + x);
}

/* integer powers by squaring; exact while the result fits */
static float ipow(float x, unsigned n)
{
    float r = 1.0f;
    while (n) {
        if (n & 1)
            r *= x;
        x *= x;
        n >>= 1;
    }
    return r;
}

double pow(double x, double y)
{
    float r;
    int neg = 0;
    if (y == 0.0f || x == 1.0f)
        return 1.0f;
    if (x != x || y != y)
        return x + y;
    if (y == trunc(y) && fabs(y) < 16777216.0f) {
        int n = (int)y;
        if (n >= 0)
            return ipow(x, n);
        return 1.0f / ipow(x, -n);
    }
    if (x < 0.0f) {
        errno = EDOM;
        return 0.0f / 0.0f;                  /* negative base, fractional power */
    }
    if (x == 0.0f)
        return y > 0 ? 0.0f : 1.0f / 0.0f;
    r = exp(y * log(x));
    (void)neg;
    return r;
}

/* ---------------------------------------------------------------- trigonometry */

#define PIO2_1 1.5707855225e+00f             /* pi/2 in three parts, 17 bits each: */
#define PIO2_2 1.0804273188e-05f             /* k * PIO2_1 and k * PIO2_2 are exact */
#define PIO2_3 6.0771006283e-11f             /* for k < 128 */
#define TWO_OVER_PI 6.3661974669e-01f
#define PI_OVER_2 1.5707963705e+00f

static float sin_small(float x)              /* |x| <= pi/4 */
{
    float z = x * x;
    return x + x * z * (-1.6666667163e-01f + z * (8.3333337680e-03f + z * (-1.9841270114e-04f +
           z * (2.7557318845e-06f - z * 2.5052108385e-08f))));
}

static float cos_small(float x)              /* |x| <= pi/4 */
{
    float z = x * x;
    return 1.0f + z * (-0.5f + z * (4.1666667908e-02f + z * (-1.3888889225e-03f +
           z * (2.4801587642e-05f + z * (-2.7557319807e-07f + z * 2.0876756988e-09f)))));
}

/* the bits of 2/pi after the point, 32 per word */
static const unsigned two_over_pi[] = {
    0xA2F9836E, 0x4E441529, 0xFC2757D1, 0xF534DDC0, 0xDB629599, 0x3C439041,
    0xFE5163AB, 0xDEBBC561, 0xB7246E3A, 0x424DD2E0, 0x06492EEA, 0x09D1921C,
};

/* 16 bits of 2/pi starting at bit j (bit 0 is worth 1/2) */
static unsigned window16(int j)
{
    int w = j >> 5, b = j & 31;
    unsigned hi = two_over_pi[w], lo = two_over_pi[w + 1];
    unsigned v = b ? (hi << b) | (lo >> (32 - b)) : hi;
    return v >> 16;
}

/* bits [lo, lo + n) of a little-endian byte array, n <= 32 */
static unsigned field(const unsigned *byte, int lo, int n)
{
    unsigned v = 0;
    int i;
    for (i = n - 1; i >= 0; i--) {
        int b = lo + i;
        v = (v << 1) | (b < 0 ? 0 : (byte[b >> 3] >> (b & 7)) & 1);
    }
    return v;
}

/* Payne-Hanek: x = k * pi/2 + r for any finite x >= 1, exactly from the
   bits of 2/pi: x * 2/pi = M * 2^E * 2/pi, of which only the bits from
   2^1 down matter (k mod 4 and the fraction). */
static int reduce_big(float x, float *r)
{
    unsigned u = to_bits(x);
    unsigned m = (u & 0x7FFFFF) | 0x800000;
    int e = (int)(u >> 23) - 150;           /* x = m * 2^e */
    int j0 = e - 2 > 0 ? e - 2 : 0;          /* first bit of 2/pi that matters */
    unsigned w[6], mb[3], acc[16];
    unsigned hi, lo, q;
    int i, j, s;
    float f;
    for (j = 0; j < 6; j++)                  /* w[0] lowest: bits j0+80 .. j0+95 */
        w[j] = window16(j0 + 80 - 16 * j);
    mb[0] = m & 0xFF;
    mb[1] = (m >> 8) & 0xFF;
    mb[2] = m >> 16;
    for (i = 0; i < 16; i++)
        acc[i] = 0;
    for (i = 0; i < 3; i++)
        for (j = 0; j < 6; j++)
            acc[i + 2 * j] += mb[i] * w[j];
    for (i = 0; i < 15; i++) {               /* bytes */
        acc[i + 1] += acc[i] >> 8;
        acc[i] &= 0xFF;
    }
    s = j0 + 96 - e;                         /* bit s of the product is worth 1 */
    q = field(acc, s, 2);
    hi = field(acc, s - 32, 32);
    lo = field(acc, s - 64, 32);
    if (hi >> 31) {                          /* fraction >= 1/2: use k + 1 */
        q = (q + 1) & 3;
        lo = -lo;
        hi = ~hi + (lo == 0);
        f = -((float)hi * 2.3283064e-10f + (float)lo * 5.4210109e-20f);
    } else {
        f = (float)hi * 2.3283064e-10f + (float)lo * 5.4210109e-20f;
    }
    *r = f * PI_OVER_2;
    return q;
}

/* x = k * pi/2 + r, |r| <= pi/4; returns k mod 4 */
static int reduce(float x, float *r)
{
    float a = fabs(x);
    int q;
    if (a < 100.0f) {
        float k = round(a * TWO_OVER_PI);
        *r = ((a - k * PIO2_1) - k * PIO2_2) - k * PIO2_3;
        q = (int)k & 3;
    } else {
        q = reduce_big(a, r);
    }
    if (x < 0) {
        *r = -*r;
        q = (4 - q) & 3;
    }
    return q;
}

double sin(double x)
{
    float r;
    int q;
    if (x != x || __fpclassify(x) == FP_INFINITE)
        return 0.0f / 0.0f;
    if (fabs(x) < 0.7853982f)
        return sin_small(x);
    q = reduce(x, &r);
    switch (q) {
    case 0: return sin_small(r);
    case 1: return cos_small(r);
    case 2: return -sin_small(r);
    default: return -cos_small(r);
    }
}

double cos(double x)
{
    float r;
    int q;
    if (x != x || __fpclassify(x) == FP_INFINITE)
        return 0.0f / 0.0f;
    if (fabs(x) < 0.7853982f)
        return cos_small(x);
    q = reduce(x, &r);
    switch (q) {
    case 0: return cos_small(r);
    case 1: return -sin_small(r);
    case 2: return -cos_small(r);
    default: return sin_small(r);
    }
}

double tan(double x)
{
    float r;
    int q;
    if (x != x || __fpclassify(x) == FP_INFINITE)
        return 0.0f / 0.0f;
    q = reduce(x, &r);
    if (q & 1)
        return -cos_small(r) / sin_small(r);
    return sin_small(r) / cos_small(r);
}

/* atan for |x| <= tan(pi/8) */
static float atan_small(float x)
{
    float z = x * x;
    return ((((8.05374449538e-2f * z - 1.38776856032e-1f) * z + 1.99777106478e-1f) * z
             - 3.33329491539e-1f) * z * x) + x;
}

double atan(double x)
{
    float a = fabs(x), r;
    if (x != x)
        return x;
    if (a > 2.414213562f)                    /* tan(3pi/8) */
        r = M_PI_2 - atan_small(1.0f / a);
    else if (a > 0.4142135623f)              /* tan(pi/8) */
        r = M_PI_4 + atan_small((a - 1.0f) / (a + 1.0f));
    else
        r = atan_small(a);
    return x < 0 ? -r : r;
}

double atan2(double y, double x)
{
    float r;
    if (x != x || y != y)
        return x + y;
    if (x == 0.0f) {
        if (y == 0.0f)
            return __signbit(x) ? copysign(M_PI, y) : copysign(0.0f, y);
        return y > 0 ? M_PI_2 : -M_PI_2;
    }
    r = atan(y / x);
    if (x > 0)
        return r;
    return __signbit(y) ? r - M_PI : r + M_PI;
}

double asin(double x)
{
    float a = fabs(x);
    if (a > 1.0f) {
        errno = EDOM;
        return 0.0f / 0.0f;
    }
    if (a == 1.0f)
        return copysign(M_PI_2, x);
    return atan(x / sqrt((1.0f - x) * (1.0f + x)));
}

double acos(double x)
{
    if (fabs(x) > 1.0f) {
        errno = EDOM;
        return 0.0f / 0.0f;
    }
    if (x == -1.0f)
        return M_PI;
    return 2.0f * atan(sqrt((1.0f - x) / (1.0f + x)));
}

/* ---------------------------------------------------------------- hyperbolic */

double sinh(double x)
{
    float a = fabs(x), e;
    if (a < 0.5f) {
        float z = x * x;
        return x + x * z * (1.6666667163e-01f + z * (8.3333337680e-03f + z * 1.9841270114e-04f));
    }
    e = exp(a);
    e = 0.5f * (e - 1.0f / e);
    return x < 0 ? -e : e;
}

double cosh(double x)
{
    float e = exp(fabs(x));
    return 0.5f * (e + 1.0f / e);
}

double tanh(double x)
{
    float a = fabs(x), e;
    if (a > 9.0f)
        return x < 0 ? -1.0f : 1.0f;
    if (a < 0.07f) {
        float z = x * x;
        return x + x * z * (-3.3333334327e-01f + z * (1.3333334029e-01f + z * (-5.3968254477e-02f +
               z * 2.1869488060e-02f)));
    }
    e = expm1(2.0f * a);
    e = e / (e + 2.0f);
    return x < 0 ? -e : e;
}
