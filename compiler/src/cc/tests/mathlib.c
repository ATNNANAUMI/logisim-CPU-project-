/* math.h (float functions; printed with few digits, so last-bit
 * differences between this library and glibc's don't show) */
#include <stdio.h>
#include <math.h>

int main(void)
{
    float x;
    int e;
    for (x = -2.0f; x <= 2.0f; x += 0.5f)
        printf("%5.2f: sin %.5f cos %.5f atan %.5f exp %.4g\n", x, sinf(x), cosf(x), atanf(x), expf(x));
    for (x = 0.25f; x < 100.0f; x *= 3.5f)     /* (x 3.0 hits log10(20.25) = 1.3064250..., a rounding tie at 5 places) */
        printf("%7.3f: log %.5f log10 %.5f sqrt %.5f cbrt %.5f\n", x, logf(x), log10f(x), sqrtf(x), cbrtf(x));
    printf("pow %.3f %.3f %.5f %.1f\n", powf(2.0f, 10.0f), powf(2.0f, 0.5f), powf(10.0f, -2.0f), powf(-3.0f, 3.0f));
    printf("floor %.1f %.1f ceil %.1f %.1f\n", floorf(2.7f), floorf(-2.7f), ceilf(2.2f), ceilf(-2.2f));
    printf("round %.1f %.1f %.1f trunc %.1f %.1f\n", roundf(2.5f), roundf(-2.5f), roundf(0.49999997f), truncf(-3.9f), truncf(3.9f));
    printf("fmod %.4f %.4f %.4f\n", fmodf(10.0f, 3.0f), fmodf(-7.5f, 2.0f), fmodf(5.25f, 0.5f));
    printf("fabs %.2f hypot %.4f atan2 %.4f %.4f\n", fabsf(-4.25f), hypotf(3.0f, 4.0f), atan2f(1.0f, -1.0f), atan2f(-1.0f, -1.0f));
    printf("asin %.5f acos %.5f tan %.5f\n", asinf(0.5f), acosf(0.5f), tanf(0.75f));
    printf("sinh %.5f cosh %.5f tanh %.5f\n", sinhf(1.0f), coshf(1.0f), tanhf(0.5f));
    printf("frexp %.3f ", frexpf(48.0f, &e));
    printf("%d ldexp %.1f modf ", e, ldexpf(3.0f, 4));
    {
        float ip;
        float fr = modff(-3.75f, &ip);
        printf("%.2f %.2f\n", ip, fr);
    }
    printf("big sin %.5f %.5f cos %.5f\n", sinf(1000.0f), sinf(123456.0f), cosf(1e20f));
    printf("classify %d %d %d %d\n", isnan(sqrtf(-1.0f)) != 0, isinf(1.0f / 0.0f) != 0,
           isfinite(2.0f) != 0, signbit(-0.0f) != 0);
    return 0;
}
