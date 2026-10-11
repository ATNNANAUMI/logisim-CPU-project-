/* float arithmetic, conversions and comparisons (float only: double is
 * 32 bits on the CPU, so the tests use float and f literals) */
#include <stdio.h>

static float poly(float x) { return ((2.5f * x - 1.0f) * x + 0.25f) * x - 3.0f; }

int main(void)
{
    float a = 1.5f, b = -0.25f, c;
    int i;
    unsigned u;
    float vals[] = { 0.0f, -0.0f, 1.0f, -1.0f, 0.5f, 2.5f, -2.5f, 1e10f, 3.7f, -3.7f };

    printf("%f %f %f %f\n", a + b, a - b, a * b, a / b);
    printf("%.6f %.6f\n", poly(2.0f), poly(-1.5f));

    for (i = 0; i < 10; i++) {
        float x = vals[i];
        printf("%g: %d %d %d %d %d %d | %d\n", x, x < 0.5f, x <= 0.5f, x > 0.5f, x >= 0.5f,
               x == 0.5f, x != 0.5f, x < 2e9f ? (int)x : -1);
    }

    c = 0.0f;
    for (i = 0; i < 10; i++)
        c += 0.1f;
    printf("%.7f %d\n", c, c == 1.0f);

    u = 3000000000u;
    printf("%.1f %.1f\n", (float)u, (float)(int)-7);
    c = 3000000000.0f;
    printf("%u %d %d\n", (unsigned)c, (int)2.9f, (int)-2.9f);

    printf("%f %f\n", (float)(1 << 24) + 1.0f, 16777217.0f);
    printf("%e %e\n", 1.0f / 3.0f, 2.0f / 3.0f);
    printf("%.10f\n", 0.1f);
    printf("%g %g %g\n", 1.0f / 0.0f, -1.0f / 0.0f, 123456789.0f);

    a = 2.0f;
    a *= 3.0f;
    a -= 0.5f;
    a /= 2.0f;
    printf("%f\n", a);
    i = 7;
    a = i / 2;
    b = i / 2.0f;
    printf("%f %f\n", a, b);
    a = 10.0f;
    a += i;
    i += 2.75f;
    printf("%f %d\n", a, i);
    if (a)
        printf("nonzero\n");
    if (!0.0f)
        printf("zero is false\n");
    return 0;
}
