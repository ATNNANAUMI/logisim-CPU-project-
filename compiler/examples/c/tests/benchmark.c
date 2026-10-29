/* benchmark.c - twelve ways to take a square root, timed with clock() and
 * checked against sqrt() (math.h, exact): the old bit-by-bit sqrt as the
 * reference, Quake III's inverse square root (original or improved
 * constant, 1 or 2 Newton steps, or 1 step and a residual correction) and
 * Newton's method (from y = x, or from one of two bit-based first guesses,
 * 1 to 3 steps).
 *
 * pypy3 compiler/src/cc run compiler/examples/c/tests/benchmark.c --steps 600000000
 *     (-D ONLY_ALGORITHM=n runs only one, numbered below)
 * pypy3 compiler/src/cc run compiler/examples/c/tests/benchmark.c --stats \
 *     -D COUNT_ONLY -D ONLY_ALGORITHM=n
 *     (only algorithm n's loop, untimed, for its instruction count)
 *
 * The times change from run to run: in the simulator clock() is the
 * computer's real clock. Expected output starts
 *   Reference bit-by-bit sqrt()
 *     Time: 494 ms
 *     Checksum: 99998552.0000
 *     Max absolute error: 0.00000000
 *     Max relative error: 0.00000000
 *     Results differing from reference: 0/20000
 * and the other eleven differ from the reference in 19958, 17679, 19950,
 * 17631, 19086, 6576, 15470, 18597, 754, 19824 and 4264 of the 20000
 * results.
 */
#include <stdio.h>
#include <math.h>
#include <time.h>

#define ITERATIONS 20000

/*
 * Algorithm selection:
 *
 *   0  = benchmark every algorithm
 *   1  = Reference sqrt
 *   2  = Quake III, original constant, 1 iteration
 *   3  = Quake III, original constant, 2 iterations
 *   4  = Quake III, improved constant, 1 iteration
 *   5  = Quake III, improved constant, 2 iterations
 *   6  = Newton, starting with y = x, 12 iterations
 *   7  = Newton, existing bit-based seed, 2 iterations
 *   8  = Quake III, 1 iteration + residual correction
 *   9  = Newton, existing bit-based seed, 1 iteration
 *   10 = Newton, existing bit-based seed, 3 iterations
 *   11 = Newton, alternative bit-based seed, 1 iteration
 *   12 = Newton, alternative bit-based seed, 2 iterations
 *
 * To select one algorithm, change ONLY_ALGORITHM below.
 *
 * COUNT_ONLY mode runs the workload without accuracy checks,
 * making it suitable for simulator instruction-count tests.
 */

#ifndef ONLY_ALGORITHM
#define ONLY_ALGORITHM 0
#endif

#define QUAKE_MAGIC_ORIGINAL 0x5F3759DFu
#define QUAKE_MAGIC_IMPROVED 0x5F375A86u

/*
 * Alternative square-root seed.
 *
 * This changes the constant used to construct the initial
 * estimate. Its performance and accuracy must be measured.
 */
#define SQRT_SEED_ORIGINAL 0x1FC00000u
#define SQRT_SEED_ALTERNATIVE 0x1FBD1DF5u

typedef union {
    float f;
    unsigned u;
} FloatBits;

/* ---------------------------------------------------------
 * Floating-point bit conversion
 * --------------------------------------------------------- */

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
 * 1. Reference implementation
 *
 * Uses the sqrt() provided by the project's math library.
 * --------------------------------------------------------- */

static float reference_sqrt(float x)
{
    return (float)sqrt(x);
}

/* ---------------------------------------------------------
 * 2-5. Quake III inverse-square-root approximation
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
 * Generic bit-seeded Newton square root
 *
 * Constructs an approximate sqrt(x) from the float bit
 * pattern, then performs the requested Newton iterations.
 *
 * Intended for the positive, finite, normal inputs used
 * by this benchmark.
 * --------------------------------------------------------- */

static float newton_bit_seed_sqrt(float x,
                                  unsigned seed,
                                  int iterations)
{
    unsigned bits = float_to_bits(x);
    float y;
    int i;

    bits = (bits >> 1) + seed;
    y = bits_to_float(bits);

    for (i = 0; i < iterations; i++) {
        y = 0.5f * (y + x / y);
    }

    return y;
}

/* ---------------------------------------------------------
 * 7. Existing bit-based seed, 2 Newton iterations
 * --------------------------------------------------------- */

static float newton_seeded_sqrt(float x)
{
    return newton_bit_seed_sqrt(
        x, SQRT_SEED_ORIGINAL, 2
    );
}

/* ---------------------------------------------------------
 * 8. Quake III, 1 iteration + residual correction
 * --------------------------------------------------------- */

static float quake_corrected_sqrt(float x)
{
    float r = quake_sqrt(x, QUAKE_MAGIC_IMPROVED, 1);
    float d = x - r * r;

    return r + d / (2.0f * r);
}

/* ---------------------------------------------------------
 * 9. Existing bit-based seed, 1 Newton iteration
 * --------------------------------------------------------- */

static float newton_seeded_1(float x)
{
    return newton_bit_seed_sqrt(
        x, SQRT_SEED_ORIGINAL, 1
    );
}

/* ---------------------------------------------------------
 * 10. Existing bit-based seed, 3 Newton iterations
 * --------------------------------------------------------- */

static float newton_seeded_3(float x)
{
    return newton_bit_seed_sqrt(
        x, SQRT_SEED_ORIGINAL, 3
    );
}

/* ---------------------------------------------------------
 * 11. Alternative bit-based seed, 1 Newton iteration
 * --------------------------------------------------------- */

static float newton_alt_seed_1(float x)
{
    return newton_bit_seed_sqrt(
        x, SQRT_SEED_ALTERNATIVE, 1
    );
}

/* ---------------------------------------------------------
 * 12. Alternative bit-based seed, 2 Newton iterations
 * --------------------------------------------------------- */

static float newton_alt_seed_2(float x)
{
    return newton_bit_seed_sqrt(
        x, SQRT_SEED_ALTERNATIVE, 2
    );
}

/* ---------------------------------------------------------
 * Test inputs
 * --------------------------------------------------------- */

static float test_input(int i)
{
    float x = (float)i + 0.001f;
    return x * x / 4.0f;
}
/* ---------------------------------------------------------
 * Benchmark and accuracy measurement
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

    /* Timed section */
    start = clock();

    for (i = 0; i < ITERATIONS; i++) {
        float x = test_input(i);
        checksum += function(x);
    }

    end = clock();

    /* Accuracy section, outside the timed region */
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
 * Selected algorithm for instruction-count testing
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
#elif ONLY_ALGORITHM == 9
    return newton_seeded_1(x);
#elif ONLY_ALGORITHM == 10
    return newton_seeded_3(x);
#elif ONLY_ALGORITHM == 11
    return newton_alt_seed_1(x);
#elif ONLY_ALGORITHM == 12
    return newton_alt_seed_2(x);
#else
#error "For COUNT_ONLY, set ONLY_ALGORITHM to a value from 1 to 12"
#endif
}

#endif

/* ---------------------------------------------------------
 * Main
 * --------------------------------------------------------- */

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
    benchmark("Newton sqrt(), existing bit-based seed, 2 iterations",
              newton_seeded_sqrt);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 8
    benchmark("Quake III, 1 iteration + residual correction",
              quake_corrected_sqrt);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 9
    benchmark("Newton sqrt(), existing bit-based seed, 1 iteration",
              newton_seeded_1);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 10
    benchmark("Newton sqrt(), existing bit-based seed, 3 iterations",
              newton_seeded_3);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 11
    benchmark("Newton sqrt(), alternative bit-based seed, 1 iteration",
              newton_alt_seed_1);
#endif

#if ONLY_ALGORITHM == 0 || ONLY_ALGORITHM == 12
    benchmark("Newton sqrt(), alternative bit-based seed, 2 iterations",
              newton_alt_seed_2);
#endif

#endif

    return 0;
}