/* benchmark.c - eight ways to take a square root, timed with clock() and
 * checked against sqrt() (math.h, bit by bit): Quake III's inverse square
 * root (original or improved constant, 1 or 2 Newton steps, or 1 step and a
 * residual correction) and Newton's method (from y = x, or from a bit-based
 * first guess).
 *
 * pypy3 compiler/src/cc run compiler/examples/c/benchmark.c --steps 200000000
 *     (about 170 million instructions; -D ONLY_ALGORITHM=n runs only one)
 * pypy3 compiler/src/cc run compiler/examples/c/benchmark.c --stats \
 *     -D COUNT_ONLY -D ONLY_ALGORITHM=n
 *     (only algorithm n's loop, untimed, for its instruction count)
 *
 * The times change from run to run: in the simulator clock() is the
 * computer's real clock. Expected output starts
 *   Reference bit-by-bit sqrt()
 *     Time: 1570 ms
 *     Checksum: 423362.6875
 *     Max absolute error: 0.00000000
 *     Max relative error: 0.00000000
 *     Results differing from reference: 0/20000
 * and the other seven differ from the reference in 19960, 18274, 19960,
 * 18469, 5040, 9780 and 16538 of the 20000 results.
 */
#include <stdio.h>
#include <math.h>
#include <time.h>

#define ITERATIONS 20000

/*
 * Default:
 *   0 = benchmark every algorithm
 *
 * To benchmark one algorithm:
 *   1 = reference bit-by-bit sqrt
 *   2 = Quake III, original constant, 1 iteration
 *   3 = Quake III, original constant, 2 iterations
 *   4 = Quake III, improved constant, 1 iteration
 *   5 = Quake III, improved constant, 2 iterations
 *   6 = Newton sqrt, starting with y = x
 *   7 = Newton sqrt, bit-based initial estimate
 *   8 = Quake III, 1 iteration + residual correction
 */
#ifndef ONLY_ALGORITHM
#define ONLY_ALGORITHM 0
#endif

#define QUAKE_MAGIC_ORIGINAL 0x5F3759DFu
#define QUAKE_MAGIC_IMPROVED 0x5F375A86u

typedef union {
    float f;
    unsigned u;
} FloatBits;

static unsigned float_to_bits(float x)
{
    FloatBits b;
    b.f = x;
    return b.u;
}

static float bits_to_float(unsigned x)
{
    FloatBits b;
    b.u = x;
    return b.f;
}

static float abs_float(float x)
{
    return x < 0.0f ? -x : x;
}

/* ---------------------------------------------------------
 * 1. Reference: your existing bit-by-bit square root
 * --------------------------------------------------------- */

static float reference_sqrt(float x)
{
    return (float)sqrt(x);
}

/* ---------------------------------------------------------
 * 2-5. Quake III inverse-square-root approximation
 *
 * The final multiplication converts the reciprocal square
 * root estimate into a square root estimate.
 * --------------------------------------------------------- */

static float quake_sqrt(float x, unsigned magic, int iterations)
{
    float half = x * 0.5f;
    float y;
    unsigned bits = float_to_bits(x);
    int i;

    bits = magic - (bits >> 1);
    y = bits_to_float(bits);

    for (i = 0; i < iterations; i++) {
        y = y * (1.5f - half * y * y);
    }

    return x * y;
}

static float quake_original_1(float x)
{
    return quake_sqrt(x, QUAKE_MAGIC_ORIGINAL, 1);
}

static float quake_original_2(float x)
{
    return quake_sqrt(x, QUAKE_MAGIC_ORIGINAL, 2);
}

static float quake_improved_1(float x)
{
    return quake_sqrt(x, QUAKE_MAGIC_IMPROVED, 1);
}

static float quake_improved_2(float x)
{
    return quake_sqrt(x, QUAKE_MAGIC_IMPROVED, 2);
}

/* ---------------------------------------------------------
 * 6. Newton's method, starting with y = x
 * --------------------------------------------------------- */

static float newton_sqrt(float x)
{
    float y = x;
    int i;

    for (i = 0; i < 12; i++) {
        y = 0.5f * (y + x / y);
    }

    return y;
}

/* ---------------------------------------------------------
 * 7. Newton's method with a bit-based initial estimate
 *
 * This is an approximate sqrt bit estimate, NOT the Quake
 * inverse-sqrt estimate.
 * --------------------------------------------------------- */

static float newton_seeded_sqrt(float x)
{
    unsigned bits = float_to_bits(x);
    float y;
    int i;

    bits = (bits >> 1) + 0x1FC00000u;
    y = bits_to_float(bits);

    for (i = 0; i < 2; i++) {
        y = 0.5f * (y + x / y);
    }

    return y;
}

/* ---------------------------------------------------------
 * 8. One Quake iteration + residual correction
 *
 * r is the initial sqrt estimate.
 * d = x - r*r measures its squared error.
 * Correct using r + d/(2*r).
 * --------------------------------------------------------- */

static float quake_corrected_sqrt(float x)
{
    float r = quake_sqrt(x, QUAKE_MAGIC_IMPROVED, 1);
    float d = x - r * r;

    return r + d / (2.0f * r);
}

/* ---------------------------------------------------------
 * Input sequence used by every implementation
 * --------------------------------------------------------- */

static float test_input(int i)
{
    return (float)(i % 1024) + 0.25f;
}

/* ---------------------------------------------------------
 * Benchmark
 *
 * The timed loop contains only the algorithm call,
 * checksum accumulation, input generation, and loop.
 *
 * Accuracy is checked separately, so it does not affect
 * the reported elapsed time.
 * --------------------------------------------------------- */

static void benchmark(const char *name, float (*function)(float))
{
    clock_t start;
    clock_t end;

    float checksum = 0.0f;
    float max_abs_error = 0.0f;
    float max_rel_error = 0.0f;

    unsigned different_bits = 0;
    int i;

    start = clock();

    for (i = 0; i < ITERATIONS; i++) {
        float x = test_input(i);
        checksum += function(x);
    }

    end = clock();

    for (i = 0; i < ITERATIONS; i++) {
        float x = test_input(i);
        float expected = reference_sqrt(x);
        float actual = function(x);

        float abs_error = abs_float(actual - expected);
        float rel_error = abs_error / expected;

        if (abs_error > max_abs_error) {
            max_abs_error = abs_error;
        }

        if (rel_error > max_rel_error) {
            max_rel_error = rel_error;
        }

        if (float_to_bits(actual) != float_to_bits(expected)) {
            different_bits++;
        }
    }

    printf("%s\n", name);
    printf("  Time: %d ms\n", (int)(end - start));
    printf("  Checksum: %.4f\n", checksum);
    printf("  Max absolute error: %.8f\n", max_abs_error);
    printf("  Max relative error: %.8f\n", max_rel_error);
    printf("  Results differing from reference: %u/%d\n\n",
           different_bits, ITERATIONS);
}

/* ---------------------------------------------------------
 * Instruction-count mode
 *
 * Compile with -DCOUNT_ONLY and -DONLY_ALGORITHM=N.
 * This runs only one algorithm's workload. Use --stats to
 * obtain the simulator's total instruction count.
 * --------------------------------------------------------- */

#ifdef COUNT_ONLY

static float selected_sqrt(float x)
{
#if ONLY_ALGORITHM == 1
    return reference_sqrt(x);
#elif ONLY_ALGORITHM == 2
    return quake_original_1(x);
#elif ONLY_ALGORITHM == 3
    return quake_original_2(x);
#elif ONLY_ALGORITHM == 4
    return quake_improved_1(x);
#elif ONLY_ALGORITHM == 5
    return quake_improved_2(x);
#elif ONLY_ALGORITHM == 6
    return newton_sqrt(x);
#elif ONLY_ALGORITHM == 7
    return newton_seeded_sqrt(x);
#elif ONLY_ALGORITHM == 8
    return quake_corrected_sqrt(x);
#else
#error "For COUNT_ONLY, set ONLY_ALGORITHM to a value from 1 to 8"
#endif
}

#endif

int main(void)
{
#ifdef COUNT_ONLY

    float checksum = 0.0f;
    int i;

    for (i = 0; i < ITERATIONS; i++) {
        checksum += selected_sqrt(test_input(i));
    }

    printf("Checksum: %.4f\n", checksum);

#else

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 1
    benchmark("Reference bit-by-bit sqrt()", reference_sqrt);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 2
    benchmark("Quake III, original constant, 1 iteration",
              quake_original_1);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 3
    benchmark("Quake III, original constant, 2 iterations",
              quake_original_2);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 4
    benchmark("Quake III, improved constant, 1 iteration",
              quake_improved_1);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 5
    benchmark("Quake III, improved constant, 2 iterations",
              quake_improved_2);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 6
    benchmark("Newton sqrt(), 12 iterations, y = x",
              newton_sqrt);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 7
    benchmark("Newton sqrt(), bit-based seed, 2 iterations",
              newton_seeded_sqrt);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 8
    benchmark("Quake III, 1 iteration + residual correction",
              quake_corrected_sqrt);
#endif

#endif

    return 0;
}