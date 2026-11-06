/* stack_test.c - the stack registers on the real circuit, from C
 *
 * Build and run (from the project root):
 *   python compiler/src/cc build logisim/tests/stack_test.c
 *   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/stack_test.rom
 * or in the simulator:  python compiler/src/cc run logisim/tests/stack_test.c
 *
 * Deep recursion (hundreds of frames),
 * many arguments, big frames, structures passed by value, function pointers,
 * and setjmp/longjmp, which put ESP and EBP back with SSP and SBP. One line per
 * group, ok or FAIL, and a last line. No printf; gcc's build agrees. About
 * 66 000 instructions, two minutes on the circuit.
 */
#include <stdio.h>
#include <setjmp.h>

static int failures;

static void check(const char *name, int ok)
{
    fputs(name, stdout);
    puts(ok ? " ok" : " FAIL");
    if (!ok)
        failures++;
}

static int depth_sum(int n) { return n == 0 ? 0 : n + depth_sum(n - 1); }

static int is_odd(int n);
static int is_even(int n) { return n == 0 ? 1 : is_odd(n - 1); }
static int is_odd(int n) { return n == 0 ? 0 : is_even(n - 1); }

static int ack(int m, int n)
{
    if (m == 0)
        return n + 1;
    if (n == 0)
        return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}

static int weighted(int a, int b, int c, int d, int e, int f, int g, int h, int i, int j)
{
    return a + 2 * b + 3 * c + 4 * d + 5 * e + 6 * f + 7 * g + 8 * h + 9 * i + 10 * j;
}

static int big_frame(int seed)
{
    int a[150];
    int i, s = 0;
    for (i = 0; i < 150; i++)
        a[i] = seed + i;
    for (i = 0; i < 150; i++)
        s += a[i] - seed;
    return s;
}

static int nested_big(int n)
{
    int a[40];
    int i, s = 0;
    for (i = 0; i < 40; i++)
        a[i] = n;
    if (n > 0)
        s = nested_big(n - 1);
    for (i = 0; i < 40; i++)
        s += a[i];
    return s;
}

struct three { int a, b, c; };

static struct three rotate(struct three t)
{
    struct three r;
    r.a = t.b;
    r.b = t.c;
    r.c = t.a;
    return r;
}

static struct three rotate3(struct three t) { return rotate(rotate(rotate(t))); }

static int add1(int x) { return x + 1; }
static int dbl(int x) { return 2 * x; }
static int neg(int x) { return -x; }

static int apply_all(int (*fs[])(int), int n, int x)
{
    int i;
    for (i = 0; i < n; i++)
        x = fs[i](x);
    return x;
}

static jmp_buf jb;

static void unwind(int n)
{
    if (n == 0)
        longjmp(jb, 7);
    unwind(n - 1);
}

int main(void)
{
    int ok, i, r;

    check("recursion 400 deep", depth_sum(400) == 80200);
    check("mutual recursion 200 deep", is_even(200) == 1 && is_odd(200) == 0 && is_odd(199) == 1);
    check("ackermann(2, 3)", ack(2, 3) == 9);

    check("ten arguments", weighted(1, 2, 3, 4, 5, 6, 7, 8, 9, 10) == 385);

    ok = 1;
    for (i = 0; i < 3; i++)
        if (big_frame(i * 1000) != 11175)
            ok = 0;
    check("a 150-word frame", ok);

    check("40-word frames 20 deep", nested_big(20) == 40 * 210);

    {
        struct three t, u;
        t.a = 1; t.b = 2; t.c = 3;
        u = rotate3(t);
        check("structures by value", u.a == 1 && u.b == 2 && u.c == 3);
        u = rotate(t);
        check("structure result", u.a == 2 && u.b == 3 && u.c == 1);
    }

    {
        int (*fs[4])(int);
        fs[0] = add1; fs[1] = dbl; fs[2] = neg; fs[3] = add1;
        check("function pointers", apply_all(fs, 4, 5) == -11);
    }

    r = setjmp(jb);
    if (r == 0)
        unwind(30);
    check("setjmp and longjmp 30 frames", r == 7);
    check("stack intact after longjmp", depth_sum(100) == 5050);

    puts(failures ? "SOME CHECKS FAILED" : "all checks passed");
    return failures != 0;
}
