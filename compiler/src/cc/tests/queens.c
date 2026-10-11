/* the eight queens puzzle: count the solutions, print the first */
#include <stdio.h>

static int col[8];
static int solutions;
static int first[8];

static int safe(int row, int c)
{
    int r;
    for (r = 0; r < row; r++) {
        int d = col[r] - c;
        if (d == 0 || d == row - r || d == r - row)
            return 0;
    }
    return 1;
}

static void place(int row)
{
    int c;
    if (row == 8) {
        if (solutions++ == 0)
            for (c = 0; c < 8; c++)
                first[c] = col[c];
        return;
    }
    for (c = 0; c < 8; c++)
        if (safe(row, c)) {
            col[row] = c;
            place(row + 1);
        }
}

int main(void)
{
    int r, c;
    place(0);
    printf("%d solutions\n", solutions);
    for (r = 0; r < 8; r++) {
        for (c = 0; c < 8; c++)
            putchar(first[r] == c ? 'Q' : '.');
        putchar('\n');
    }
    return 0;
}
