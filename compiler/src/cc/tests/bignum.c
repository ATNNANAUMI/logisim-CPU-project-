/* factorials with an array of decimal digits */
#include <stdio.h>

#define DIGITS 80

static void factorial(int n)
{
    int d[DIGITS] = { 1 };
    int len = 1, i, k;
    for (k = 2; k <= n; k++) {
        int carry = 0;
        for (i = 0; i < len; i++) {
            int t = d[i] * k + carry;
            d[i] = t % 10;
            carry = t / 10;
        }
        while (carry) {
            d[len++] = carry % 10;
            carry /= 10;
        }
    }
    printf("%d! = ", n);
    for (i = len - 1; i >= 0; i--)
        putchar('0' + d[i]);
    putchar('\n');
}

int main(void)
{
    factorial(10);
    factorial(25);
    factorial(40);
    return 0;
}
