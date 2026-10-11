/* functions: recursion, pointers to functions, variadic functions, statics */
#include <stdio.h>
#include <stdarg.h>

static int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }

static int ack(int m, int n)
{
    if (m == 0)
        return n + 1;
    if (n == 0)
        return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}

static int is_even(int n);
static int is_odd(int n) { return n == 0 ? 0 : is_even(n - 1); }
static int is_even(int n) { return n == 0 ? 1 : is_odd(n - 1); }

static int add(int a, int b) { return a + b; }
static int sub(int a, int b) { return a - b; }
static int mul(int a, int b) { return a * b; }

static int apply(int (*f)(int, int), int a, int b) { return f(a, b); }

static int sum(int count, ...)
{
    va_list ap;
    int total = 0;
    va_start(ap, count);
    while (count-- > 0)
        total += va_arg(ap, int);
    va_end(ap);
    return total;
}

static double average(int count, ...)
{
    va_list ap;
    double total = 0;
    int i;
    va_start(ap, count);
    for (i = 0; i < count; i++)
        total += va_arg(ap, double);
    va_end(ap);
    return total / count;
}

static void show(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    printf("[");
    vprintf(fmt, ap);
    printf("]\n");
    va_end(ap);
}

static int counter(void)
{
    static int calls;
    return ++calls;
}

static int many(int a, int b, int c, int d, int e, int f, int g, int h)
{
    return a - b + c - d + e - f + g - h;
}

int main(void)
{
    int (*ops[3])(int, int) = { add, sub, mul };
    int i;
    printf("fib: %d %d %d\n", fib(10), fib(15), fib(20));
    printf("ack: %d %d\n", ack(2, 3), ack(3, 3));
    printf("even/odd: %d %d %d\n", is_even(10), is_odd(7), is_even(7));
    for (i = 0; i < 3; i++)
        printf("op%d: %d\n", i, apply(ops[i], 7, 3));
    printf("sum: %d %d %d\n", sum(0), sum(3, 1, 2, 3), sum(5, 10, 20, 30, 40, 50));
    printf("average: %.3f\n", average(4, 1.0, 2.0, 3.5, 4.0));
    show("%d-%s-%c", 42, "x", 'y');
    counter();
    counter();
    printf("counter: %d\n", counter());
    printf("many: %d\n", many(1, 2, 3, 4, 5, 6, 7, 8));
    printf("nested calls: %d\n", add(mul(2, 3), sub(add(1, 2), mul(fib(5), 2))));
    return 0;
}
