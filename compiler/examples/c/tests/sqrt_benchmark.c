/* sqrt_benchmark.c - the library's sqrt() (Newton from a bit-based guess,
 * then an exact rounding check) against the bit-by-bit sqrt it replaced
 *
 * pypy3 compiler/src/cc run compiler/examples/c/tests/sqrt_benchmark.c --steps 400000000
 *
 * The reference function below is the original bit-by-bit sqrt, renamed so
 * it can coexist with the library's. Both run over 20000 inputs, 5 times;
 * every result must be the same. Expected output (the times change):
 *   Optimized sqrt() benchmark: 20000 inputs, 5 repetitions
 *   Input: (float)(i*i/4), i = 0..19999
 *
 *   Run 1: 342 ms, ref 562 ms | checksum 99991456.0000 | max abs 0.00000000 | max rel 0.00000000 | differing 0/20000
 *   ... (runs 2-5 the same apart from the times)
 */
#include <stdio.h>
#include <time.h>
#include <math.h>

#define TEST_COUNT 20000
#define REPETITIONS 5

typedef union {
    float f;
    unsigned u;
} FloatBits;

static unsigned to_bits(float x)
{
    FloatBits b;
    b.f = x;
    return b.u;
}

static float from_bits(unsigned x)
{
    FloatBits b;
    b.u = x;
    return b.f;
}

/* Original bit-by-bit implementation, retained as the reference. */
static float reference_sqrt(float x)
{
    unsigned ix = to_bits(x);
    unsigned q, s, r, t;
    int m;

    if ((ix & 0x7FFFFFFF) == 0)
        return x;
    if (ix & 0x80000000)
        return 0.0f / 0.0f;
    if (ix >= 0x7F800000)
        return x;

    m = ix >> 23;
    if (m == 0) {
        while (!(ix & 0x800000)) {
            ix <<= 1;
            m--;
        }
        m++;
    }

    m -= 127;
    ix = (ix & 0x7FFFFF) | 0x800000;
    if (m & 1)
        ix += ix;
    m = (m - (m & 1)) / 2;

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
        q += q & 1;
    ix = (q >> 1) + 0x3F000000;
    ix += (unsigned)m << 23;
    return from_bits(ix);
}

/* Same input expression as the previous benchmark. Since i is an int,
 * adding 0.001f and assigning back to i leaves nonnegative i unchanged. */
static float test_input(int i)
{
    float x = (float)i + 0.001f;
    return (float)(i * i / 4);
}

static float inputs[TEST_COUNT];
static float expected[TEST_COUNT];
int main(void)
{
    int i, rep;

    /* Generate inputs and reference answers outside the timed region. */
    clock_t start, elapsed, timing[REPETITIONS];
    for (i = 0; i < TEST_COUNT; i++) {
        inputs[i] = test_input(i);
    }
    for (rep = 0; rep < REPETITIONS; rep++) {
        float checksum = 0.0f;
        start = clock();
        for (i = 0; i < TEST_COUNT; i++) {
            expected[i] = reference_sqrt(inputs[i]);
            checksum += expected[i];
        }
        elapsed = clock() - start;
        timing[rep] = elapsed;
    }

    printf("Optimized sqrt() benchmark: %d inputs, %d repetitions\n",
           TEST_COUNT, REPETITIONS);
    printf("Input: (float)(i*i/4), i = 0..%d\n\n", TEST_COUNT - 1);

    for (rep = 0; rep < REPETITIONS; rep++) {
        
        float checksum = 0.0f;
        float max_abs_error = 0.0f;
        float max_rel_error = 0.0f;
        int differing = 0;

        start = clock();
        for (i = 0; i < TEST_COUNT; i++) {
            float got = (float)sqrt(inputs[i]);
            checksum += got;
        }
        elapsed = clock() - start;

        for (i = 0; i < TEST_COUNT; i++) {
            float got = (float)sqrt(inputs[i]);
            float want = expected[i];
            float abs_error = got - want;
            float rel_error;

            if (abs_error < 0.0f)
                abs_error = -abs_error;
            if (abs_error > max_abs_error)
                max_abs_error = abs_error;

            rel_error = want == 0.0f ? abs_error : abs_error / want;
            if (rel_error < 0.0f)
                rel_error = -rel_error;
            if (rel_error > max_rel_error)
                max_rel_error = rel_error;

            if (to_bits(got) != to_bits(want))
                differing++;
        }

        printf("Run %d: %lu ms, ref %lu ms | checksum %.4f | max abs %.8f | ",
               rep + 1, (unsigned long)elapsed, (unsigned long)timing[rep], checksum, max_abs_error);
        printf("max rel %.8f | differing %d/%d\n",
               max_rel_error, differing, TEST_COUNT);
    }

    return 0;
}
