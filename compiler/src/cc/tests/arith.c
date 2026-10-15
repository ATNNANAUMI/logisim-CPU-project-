/* integer arithmetic: signed and unsigned, shifts, comparisons, compound assignment */
#include <stdio.h>

static int sdiv(int a, int b) { return a / b; }
static int smod(int a, int b) { return a % b; }
static unsigned udiv(unsigned a, unsigned b) { return a / b; }
static unsigned umod(unsigned a, unsigned b) { return a % b; }

int main(void)
{
    int a = 17, b = -5, i;
    unsigned u = 4000000000u, v = 7;
    int vals[] = { 0, 1, -1, 7, -7, 100, -100, 2147483647, -2147483647 - 1 };
    int n = sizeof vals / sizeof vals[0];

    printf("%d %d %d %d %d\n", a + b, a - b, a * b, a / b, a % b);
    printf("%d %d %d %d\n", -a / 5, -a % 5, a / -5, a % -5);
    printf("%u %u %u %u\n", u / v, u % v, u / 3u, u % 1000u);
    printf("%u %u %u\n", udiv(u, 4000000001u), udiv(4294967295u, 2147483648u), umod(4294967295u, 2147483648u));
    printf("%u %u\n", udiv(3000000000u, 7u), umod(3000000000u, 7u));
    printf("%d %d\n", sdiv(-2147483647, 3), smod(-2147483647, 3));

    /* shifts by constants and by variables */
    for (i = 0; i < 32; i += 5) {
        printf("%d: %x %x %x %d\n", i, 1u << i, 0x80000000u >> i,
               (unsigned)-12345 >> i, -12345 >> i);
    }
    printf("%d %d %d\n", -1 >> 31, (int)(1u << 31) >> 31, (int)(0x40000000u << 1) >> 30);

    /* comparisons */
    for (i = 0; i < n; i++) {
        int x = vals[i];
        printf("%d: %d%d%d%d%d%d ", x, x < 7, x <= 7, x > 7, x >= 7, x == 7, x != 7);
        printf("%d%d%d%d ", x < -100, x > -100, x <= 0, x >= 0);
        printf("%d%d\n", (unsigned)x < 7u, (unsigned)x > 0x80000000u);
    }

    /* bitwise and compound assignment */
    a = 0x0F0F;
    a |= 0xF000;
    a &= 0xFF0F;
    a ^= 0x00FF;
    printf("%x %x %x\n", a, ~a, -a);
    a = 100;
    a += 5; a -= 3; a *= 7; a /= 2; a %= 50; a <<= 3; a >>= 1;
    printf("%d\n", a);
    u = 1;
    u <<= 31; u >>= 4; u += 0xFFFFFFFFu;
    printf("%u\n", u);

    /* increments */
    a = 5;
    b = a++;
    b += ++a;
    printf("%d %d\n", a, b);
    b = a--;
    b -= --a;
    printf("%d %d\n", a, b);

    /* logical operators and short-circuit */
    a = 0;
    if (a != 0 && 10 / a > 1)
        printf("wrong\n");
    if (a == 0 || 10 / a > 1)
        printf("short-circuit ok\n");
    printf("%d %d %d %d\n", !0, !5, 3 && 0, 3 || 0);

    /* conversions */
    {
        char c = 'A';
        short s = -300;
        long l = 123456;
        unsigned char uc = 200;
        printf("%d %d %ld %d %d\n", c + 1, s * 2, l * 10, uc + 100, (int)(unsigned)-1);
    }
    return 0;
}
