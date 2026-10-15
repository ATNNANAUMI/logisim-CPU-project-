/* arrays and pointers */
#include <stdio.h>

static int grid[4][5];

static int total(const int *p, int n)
{
    int s = 0;
    while (n--)
        s += *p++;
    return s;
}

static void reverse(char *s)
{
    char *e = s;
    while (*e)
        e++;
    while (s < --e) {
        char t = *s;
        *s++ = *e;
        *e = t;
    }
}

int main(void)
{
    int a[10];
    int i, j;
    int *p, *q;
    char word[] = "pointers";
    int local[3][3] = { { 1, 2, 3 }, { 4, 5, 6 }, { 7, 8, 9 } };

    for (i = 0; i < 10; i++)
        a[i] = i * i;
    printf("%d %d\n", total(a, 10), total(a + 5, 5));

    p = &a[2];
    q = a + 7;
    printf("%d %d %d %d\n", *p, *q, (int)(q - p), p[3]);
    printf("%d %d %d\n", p < q, p == q - 5, *(a + 9));

    for (i = 0; i < 4; i++)
        for (j = 0; j < 5; j++)
            grid[i][j] = i * 10 + j;
    printf("%d %d %d\n", grid[2][3], grid[3][4], total(grid[1], 5));
    printf("%d %d\n", (int)(sizeof grid / sizeof grid[0]), (int)(sizeof grid[0] / sizeof grid[0][0]));

    printf("%d %d\n", local[1][1], local[2][0] + local[0][2]);
    {
        int (*row)[3] = local;
        printf("%d %d\n", row[2][2], (*(row + 1))[0]);
    }

    reverse(word);
    printf("%s\n", word);

    {
        const char *names[] = { "ab", "cde", "f" };
        int len = 0;
        for (i = 0; i < 3; i++) {
            const char *s = names[i];
            while (*s++)
                len++;
        }
        printf("%d %c %c\n", len, names[1][2], *names[2]);
    }

    {
        int buf[5] = { 5, 4, 3, 2, 1 };
        int *end = buf + 5;
        int swapped = 1;
        while (swapped) {
            swapped = 0;
            for (p = buf; p + 1 < end; p++)
                if (p[0] > p[1]) {
                    int t = p[0];
                    p[0] = p[1];
                    p[1] = t;
                    swapped = 1;
                }
        }
        for (p = buf; p < end; p++)
            printf("%d ", *p);
        printf("\n");
    }
    return 0;
}
