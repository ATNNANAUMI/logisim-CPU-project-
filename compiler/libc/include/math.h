/* math.h - mathematics on the CPU's 32-bit floats
 *
 * double is the same 32-bit float as float, so sqrt and sqrtf (and every
 * other f/l pair) are the same function. Results are float precision:
 * about 7 significant digits.
 */
#ifndef _MATH_H
#define _MATH_H

#define HUGE_VAL (1.0f / 0.0f)
#define HUGE_VALF HUGE_VAL
#define HUGE_VALL HUGE_VAL
#define INFINITY HUGE_VAL
#define NAN (0.0f / 0.0f)

#define FP_NAN 0
#define FP_INFINITE 1
#define FP_ZERO 2
#define FP_SUBNORMAL 3
#define FP_NORMAL 4

#define M_E 2.71828182845904523536
#define M_LOG2E 1.44269504088896340736
#define M_LOG10E 0.434294481903251827651
#define M_LN2 0.693147180559945309417
#define M_LN10 2.30258509299404568402
#define M_PI 3.14159265358979323846
#define M_PI_2 1.57079632679489661923
#define M_PI_4 0.785398163397448309616
#define M_1_PI 0.318309886183790671538
#define M_2_PI 0.636619772367581343076
#define M_2_SQRTPI 1.12837916709551257390
#define M_SQRT2 1.41421356237309504880
#define M_SQRT1_2 0.707106781186547524401

double fabs(double x);
double floor(double x);
double ceil(double x);
double round(double x);
double trunc(double x);
double rint(double x);
double nearbyint(double x);
long lround(double x);
long lrint(double x);
double fmod(double x, double y);
double remainder(double x, double y);
double fmin(double x, double y);
double fmax(double x, double y);
double fdim(double x, double y);
double fma(double x, double y, double z);
double copysign(double x, double y);
double sqrt(double x);
double cbrt(double x);
double hypot(double x, double y);
double pow(double x, double y);
double exp(double x);
double exp2(double x);
double expm1(double x);
double log(double x);
double log2(double x);
double log10(double x);
double log1p(double x);
double sin(double x);
double cos(double x);
double tan(double x);
double asin(double x);
double acos(double x);
double atan(double x);
double atan2(double y, double x);
double sinh(double x);
double cosh(double x);
double tanh(double x);
double frexp(double x, int *exp);
double ldexp(double x, int exp);
double scalbn(double x, int n);
int ilogb(double x);
double logb(double x);
double modf(double x, double *ip);
double nextafter(double x, double y);

int __fpclassify(double x);
int __signbit(double x);
#define fpclassify(x) __fpclassify(x)
#define isnan(x) (fpclassify(x) == FP_NAN)
#define isinf(x) (fpclassify(x) == FP_INFINITE)
#define isfinite(x) (fpclassify(x) > FP_INFINITE)
#define isnormal(x) (fpclassify(x) == FP_NORMAL)
#define signbit(x) __signbit(x)
#define isgreater(x, y) ((x) > (y))
#define isgreaterequal(x, y) ((x) >= (y))
#define isless(x, y) ((x) < (y))
#define islessequal(x, y) ((x) <= (y))
#define islessgreater(x, y) ((x) < (y) || (x) > (y))
#define isunordered(x, y) (isnan(x) || isnan(y))

/* the float and long double names are the same functions */
#define fabsf fabs
#define floorf floor
#define ceilf ceil
#define roundf round
#define truncf trunc
#define rintf rint
#define lroundf lround
#define fmodf fmod
#define fminf fmin
#define fmaxf fmax
#define copysignf copysign
#define sqrtf sqrt
#define cbrtf cbrt
#define hypotf hypot
#define powf pow
#define expf exp
#define exp2f exp2
#define logf log
#define log2f log2
#define log10f log10
#define sinf sin
#define cosf cos
#define tanf tan
#define asinf asin
#define acosf acos
#define atanf atan
#define atan2f atan2
#define sinhf sinh
#define coshf cosh
#define tanhf tanh
#define frexpf frexp
#define ldexpf ldexp
#define modff modf
#define fabsl fabs
#define floorl floor
#define ceill ceil
#define sqrtl sqrt
#define powl pow
#define expl exp
#define logl log
#define sinl sin
#define cosl cos

#endif
