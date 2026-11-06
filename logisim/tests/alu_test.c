/* alu_test.c - the integer and float units on the real circuit, by identities
 *
 * Build and run (from the project root):
 *   python compiler/src/cc build logisim/tests/alu_test.c
 *   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/alu_test.rom
 * or in the simulator:  python compiler/src/cc run logisim/tests/alu_test.c
 *
 * No expected numbers: every check is an identity that holds for any correct
 * ALU (a + b - b == a, a / b * b + a % b == a, a shift and its inverse, ...),
 * run over values chosen to hit the edges (0, 1, the byte, half-word and word
 * boundaries, the sign bit). One line per group, ok or FAIL, and a last line.
 * It avoids printf (many instructions on the circuit) and undefined behaviour,
 * so gcc's build agrees: about 105 000 instructions, three minutes on the circuit.
 */
#include <stdio.h>

static int failures;

static void check(const char *name, int ok)
{
    fputs(name, stdout);
    puts(ok ? " ok" : " FAIL");
    if (!ok)
        failures++;
}

#define N 8
static const unsigned V[N] = {0u, 1u, 3u, 0x80u, 0xFFFFu, 0x12345678u, 0x80000000u, 0xFFFFFFFFu};

static unsigned popcount_loop(unsigned x)
{
    unsigned n = 0;
    while (x) {
        n += x & 1u;
        x >>= 1;
    }
    return n;
}

static unsigned popcount_swar(unsigned x)
{
    x = x - ((x >> 1) & 0x55555555u);
    x = (x & 0x33333333u) + ((x >> 2) & 0x33333333u);
    x = (x + (x >> 4)) & 0x0F0F0F0Fu;
    return (x * 0x01010101u) >> 24;
}

static unsigned mul_shift_add(unsigned a, unsigned b)
{
    unsigned r = 0;
    int i;
    for (i = 0; i < 32; i++)
        if ((b >> i) & 1u)
            r += a << i;
    return r;
}

int main(void)
{
    int i, j, k, ok;

    ok = 1;
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            unsigned a = V[i], b = V[j];
            if ((a + b) - b != a || (a - b) + b != a || a + b != b + a)
                ok = 0;
            if (a + b != (a ^ b) + ((a & b) << 1))          /* the adder's carries */
                ok = 0;
        }
    check("add and subtract", ok);

    ok = 1;
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            unsigned a = V[i], b = V[j];
            if ((a ^ b ^ b) != a || ((a & b) | (a & ~b)) != a || ~(a | b) != (~a & ~b)
                || ~(a & b) != (~a | ~b) || (a | b) != ((a ^ b) | (a & b)))
                ok = 0;
        }
    check("bitwise", ok);

    ok = 1;
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            unsigned a = V[i], b = V[j];
            int sa = (int)a, sb = (int)b;
            if ((a < b) != (b > a) || (a <= b) != !(a > b) || (a == b) != !(a != b))
                ok = 0;
            if ((sa < sb) != ((a ^ 0x80000000u) < (b ^ 0x80000000u)))   /* signed = flipped sign bit */
                ok = 0;
        }
    check("compares", ok);

    ok = 1;
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            unsigned a = V[i], b = V[j];
            if (mul_shift_add(a, b) != a * b || a * b != b * a)
                ok = 0;
        }
    check("multiply", ok);

    ok = 1;
    for (i = 0; i < N; i++)
        for (j = 1; j < N; j++) {                    /* V[0] = 0 is never the divisor */
            unsigned a = V[i], b = V[j];
            if ((a / b) * b + a % b != a || a % b >= b)
                ok = 0;
        }
    check("unsigned divide and modulo", ok);

    ok = 1;
    {
        static const int S[8] = {-100, -7, -1, 1, 3, 100, 12345, -12345};
        for (i = 0; i < 8; i++)
            for (j = 0; j < 8; j++) {
                int a = S[i], b = S[j];
                if ((a * b) / b != a || (a / b) * b + a % b != a)
                    ok = 0;
                if ((a < 0) != (a / 1 < 0) || (a + b) - b != a)
                    ok = 0;
            }
    }
    check("signed multiply, divide and modulo", ok);

    ok = 1;
    for (i = 0; i < N; i++)
        for (k = 0; k < 32; k++) {                   /* the shift count is a register */
            unsigned x = V[i];
            if (((x << k) >> k) != (x & (0xFFFFFFFFu >> k)))
                ok = 0;
            if (((x >> k) << k) != (x & ~((k == 0 ? 0u : 0xFFFFFFFFu >> (32 - k)))))
                ok = 0;
        }
    check("shifts by 0 to 31", ok);

    ok = 1;
    for (i = 0; i < N; i++)
        if (popcount_loop(V[i]) != popcount_swar(V[i]))
            ok = 0;
    check("bit counts", ok);

    {
        static const float F[10] = {0.5f, 1.0f, 1.5f, 2.0f, 2.5f, -3.0f, 0.25f, 100.0f, 1024.0f, 0.125f};
        ok = 1;
        for (i = 0; i < 10; i++)
            for (j = 0; j < 10; j++) {
                float a = F[i], b = F[j];
                if ((a + b) - b != a || (a - b) + b != a || a + b != b + a || a * b != b * a)
                    ok = 0;
                if ((a * b) / b != a || a - a != 0.0f)
                    ok = 0;
                if ((a < b) != (b > a) || (a == b) != (b == a))
                    ok = 0;
            }
        check("float add, subtract, multiply, divide, compare", ok);
    }

    ok = 1;
    {
        static const int I[8] = {0, 1, -1, 100, -100, 65535, 16777216, -16777216};
        for (i = 0; i < 8; i++) {
            float f = (float)I[i];
            if ((int)f != I[i])
                ok = 0;
        }
        if ((int)2.9f != 2 || (int)-2.9f != -2 || (int)0.99f != 0 || (int)1024.5f != 1024)
            ok = 0;                                  /* truncates toward zero */
    }
    check("int to float and back", ok);

    puts(failures ? "SOME CHECKS FAILED" : "all checks passed");
    return failures != 0;
}
