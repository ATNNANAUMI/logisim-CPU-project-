/* global and static variables, initializers, const tables */
#include <stdio.h>

int counter;
int primes[] = { 2, 3, 5, 7, 11, 13 };
const int squares[5] = { 0, 1, 4, 9, 16 };
char greeting[] = "hi there";
const char *message = "a message";
int *second = &primes[1];
struct entry { const char *key; int value; } table[] = {
    { "one", 1 }, { "two", 2 }, { "three", 3 },
};
static int hidden = 77;
float ratio = 0.75f;
int matrix[2][3] = { { 1, 2, 3 }, { 4, 5, 6 } };
int partial[6] = { 1, 2 };
int designated[5] = { [1] = 10, [3] = 30 };
struct point { int x, y; } origin = { .y = 9 }, corner = { 4, 5 };
int (*fp)(const char *, ...) = printf;
const char letters[] = { 'a', 'b', 'c', 0 };

static void bump(void)
{
    static int calls = 100;
    calls++;
    counter += calls;
}

int main(void)
{
    int i, s = 0;
    bump();
    bump();
    printf("%d\n", counter);
    for (i = 0; i < 6; i++)
        s += primes[i];
    printf("%d %d %d\n", s, squares[4], *second);
    printf("%s|%s\n", greeting, message);
    greeting[0] = 'H';
    printf("%s\n", greeting);
    for (i = 0; i < 3; i++)
        printf("%s=%d ", table[i].key, table[i].value);
    printf("\n");
    printf("%d %.2f %d %d\n", hidden, ratio, matrix[1][2], matrix[0][1]);
    printf("%d %d %d %d\n", partial[1], partial[5], designated[1], designated[4]);
    printf("%d %d %d %d\n", origin.x, origin.y, corner.x, corner.y);
    fp("%s %c\n", "via pointer", letters[2]);
    *second = 33;
    printf("%d\n", primes[1]);
    return 0;
}
