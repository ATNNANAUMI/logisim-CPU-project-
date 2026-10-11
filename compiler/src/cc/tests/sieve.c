/* primes below 2000 with the sieve of Eratosthenes */
#include <stdio.h>
#include <string.h>

#define N 2000

static char composite[N];

int main(void)
{
    int i, j, count = 0, last = 0;
    memset(composite, 0, sizeof composite);
    for (i = 2; i * i < N; i++)
        if (!composite[i])
            for (j = i * i; j < N; j += i)
                composite[j] = 1;
    for (i = 2; i < N; i++)
        if (!composite[i]) {
            count++;
            last = i;
            if (count <= 10)
                printf("%d ", i);
        }
    printf("\n%d primes, the last is %d\n", count, last);
    return 0;
}
