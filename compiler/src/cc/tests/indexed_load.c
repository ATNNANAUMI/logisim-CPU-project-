/* p[i] reads through a pointer in a register: index kinds, order of evaluation */
#include <stdio.h>

static int calls;
static int next(void) { return ++calls; }
static int idx(int i) { calls++; return i; }

static int sum(int *p, int n)
{
    int s = 0, i;
    for (i = 0; i < n; i++)
        s += p[i];
    return s;
}

static int pick(int *p, int *q, int i)
{
    return p[q[i]] + p[q[i] + 1] * 2 + p[i * 2] - p[i + i];
}

static int back(int *end, int k)
{
    return end[-k] * 10 + *(end - k - 1);     /* negative index and p - n */
}

int main(void)
{
    int a[8] = {10, 20, 30, 40, 50, 60, 70, 80};
    int q[4] = {3, 0, 2, 1};
    int *p = a + 2;
    int i = 1;
    printf("%d\n", sum(a, 8));
    printf("%d\n", pick(a, q, 2));
    printf("%d %d\n", p[0], p[-2]);
    printf("%d\n", back(a + 6, 1));
    printf("%d %d\n", a[idx(3)], p[idx(4)]);          /* a call in the index */
    printf("%d\n", p[next()]);                        /* calls: 1, then 2 */
    printf("%d\n", p[next()] * 100);
    printf("%d\n", p[i++] * 3);
    printf("%d\n", (p + 1)[(i - 1) * 2]);
    printf("%d %d\n", i, calls);
    return 0;
}
