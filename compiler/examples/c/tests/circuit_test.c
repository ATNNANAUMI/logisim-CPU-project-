/* circuit_test.c - checks the code the C compiler makes, on the real circuit
 *
 * Build and run (from the project root):
 *   python compiler/src/cc build compiler/examples/c/tests/circuit_test.c
 *   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/circuit_test.rom
 * or in the simulator:
 *   python compiler/src/cc run compiler/examples/c/tests/circuit_test.c
 *
 * Each line names a check and says ok or FAIL; the last line counts the
 * failures. Every line should say ok (gcc's build of this file agrees).
 * It avoids printf, which costs many instructions, so the circuit gets
 * through it in a few minutes.
 */
#include <stdio.h>
#include <string.h>
#include <stdarg.h>

static int failures;

static void check(const char *name, int ok)
{
    fputs(name, stdout);
    puts(ok ? " ok" : " FAIL");
    if (!ok)
        failures++;
}

struct pair { int a, b; };
struct flags { unsigned lo : 3; int mid : 6; unsigned hi : 10; };

static struct pair swap(struct pair p)
{
    struct pair q;
    q.a = p.b;
    q.b = p.a;
    return q;
}

static int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
static int twice(int x) { return 2 * x; }
static int add3(int x) { return x + 3; }

static int sum(int n, ...)
{
    va_list ap;
    int s = 0;
    va_start(ap, n);
    while (n--)
        s += va_arg(ap, int);
    va_end(ap);
    return s;
}

static int kind(int c)
{
    switch (c) {                  /* dense: a jump table */
    case 0: return 10;
    case 1: return 11;
    case 2: return 12;
    case 3: return 13;
    case 4: return 14;
    case 6: return 16;
    }
    return -1;
}

static int big_frame(int k)
{
    int a[24];                    /* more than 15 words: ESP is set directly */
    int i, s = 0;
    for (i = 0; i < 24; i++)
        a[i] = i * k;
    for (i = 0; i < 24; i++)
        s += a[i];
    return s;
}

/* ~ on values held in registers: the circuit's NOT inverted RA, not RB,
   until it was rewired, so the assembler writes NOT Rx with x in both fields */
static int not_in_registers(unsigned a, unsigned b)
{
    int k;
    for (k = 0; k < 3; k++) {     /* used in a loop: a and b stay in registers */
        a += k;
        b ^= k;
    }
    return (~a == 0xF0F0F0EDu) + (~b == 0xFF00FF03u);
}

static int seen[4];
static int note(int v)
{
    seen[v & 3] = v;
    return v;
}

int table[] = { 3, 1, 4, 1, 5 };
const char *word = "logic";

int main(void)
{
    volatile int n = 1000000007, m = -45;   /* volatile: no folding at compile time */
    volatile unsigned u = 4000000000u, d = 7u, big = 3000000000u;
    volatile int s = 5, sh = -1000;
    volatile float f = 2.5f, g = -0.75f;
    int i, arr[5];
    int (*ops[2])(int) = { twice, add3 };
    struct pair p = { 1, 2 }, q;
    struct flags fl;

    check("int mul/div/mod", n / 3 == 333333335 && m / 7 == -6 && m % 7 == -3
          && n * 2 == 2000000014 && m * m * m == -91125);
    check("unsigned div/mod", u / d == 571428571u && u % d == 3u && u / big == 1u
          && u % big == 1000000000u && 100u / d == 14u);
    check("shift by constant", (u >> 4) == 250000000u && (sh >> 3) == -125 && (s << 28) == 1342177280);
    check("shift by variable", (u >> s) == 125000000u && (sh >> s) == -32 && (1u << (s + 26)) == 0x80000000u);
    check("bitwise not of a register", not_in_registers(0x0F0F0F0Fu, 0x00FF00FFu) == 2);
    check("signed compare", m < 0 && m <= -45 && !(m > -45) && n > m && -1 < 1);
    check("unsigned compare", u > d && big < u && !(u < big) && d <= 7u && (unsigned)-1 > 1u);
    check("float math", f * g == -1.875f && f + g == 1.75f && f / 2 == 1.25f && g < f);
    check("float conversion", (int)(f * 3) == 7 && (int)g == 0 && (float)s == 5.0f
          && (unsigned)(float)big == 3000000000u && (float)u == 4000000000.0f);
    {
        volatile float zero = 0.0f;
        float nan = zero / zero;
        check("NaN compares false", !(nan < f) && !(nan <= f) && !(nan > f) && !(nan >= f)
              && !(nan == nan) && nan != nan && !(f <= nan));
    }
    q = swap(p);
    check("struct by value", q.a == 2 && q.b == 1 && p.a == 1);
    check("recursion", fib(10) == 55);
    check("function pointers", ops[0](7) == 14 && ops[1](7) == 10);
    check("variadic", sum(4, 10, 20, 30, 40) == 100 && sum(0) == 0);
    check("switch", kind(0) == 10 && kind(4) == 14 && kind(5) == -1 && kind(6) == 16 && kind(-3) == -1);
    check("big frame", big_frame(2) == 552);
    for (i = 0; i < 5; i++)
        arr[i] = table[i] * 10;
    check("arrays and globals", arr[4] == 50 && table[2] == 4 && word[3] == 'i' && strlen(word) == 5);
    {
        int *p2 = arr + 1;
        p2[1] += 7;
        check("pointers into a local array", arr[2] == 47 && *(p2 + 3) == 50 && p2 - arr == 1);
    }
    fl.lo = 13;
    fl.mid = -20;
    fl.hi = 1000;
    check("bit-fields", fl.lo == 5 && fl.mid == -20 && fl.hi == 1000);
    i = 1;
    note(i++);
    note(i++);
    check("variable changed inside a call's arguments", i == 3 && seen[1] == 1 && seen[2] == 2);

    if (failures == 0)
        puts("all checks passed");
    else
        puts("SOME CHECKS FAILED");
    return failures;
}
