/* towers of Hanoi */
#include <stdio.h>

static int moves;

static void hanoi(int n, char from, char to, char via)
{
    if (n == 0)
        return;
    hanoi(n - 1, from, via, to);
    moves++;
    if (n == 4)
        printf("move the biggest disc from %c to %c\n", from, to);
    hanoi(n - 1, via, to, from);
}

int main(void)
{
    hanoi(4, 'A', 'C', 'B');
    printf("%d moves\n", moves);
    hanoi(8, 'A', 'C', 'B');
    printf("%d moves in all\n", moves);
    return 0;
}
