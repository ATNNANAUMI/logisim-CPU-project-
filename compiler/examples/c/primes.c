/* primes.c - the primes below 200 (sieve of Eratosthenes), and the hex display
 *
 *   python compiler/src/cc run compiler/examples/c/primes.c
 *
 * prints the 46 primes below 200, ten per line, then "46 primes"; the last
 * prime (199 = 0x000000C7) is left on the 8-digit hex display.
 */
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <cpu.h>

#define N 2000

int main(void)
{
    bool composite[N];
    int i, j, count = 0, last = 0;

    memset(composite, 0, sizeof composite);
    for (i = 2; i < N; i++) {
        if (composite[i])
            continue;
        for (j = i * i; j < N; j += i)
            composite[j] = true;
        printf("%5d", i);
        if (++count % 10 == 0)
            printf("\n");
        last = i;
    }
    printf("\n%d primes\n", count);
    show_hex(last);
    return 0;
}
