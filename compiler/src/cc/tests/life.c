/* Conway's game of life: a glider and a blinker on a 12x12 torus */
#include <stdio.h>

#define W 12
#define H 12

static int grid[H][W], next[H][W];

static int neighbours(int y, int x)
{
    int dy, dx, n = 0;
    for (dy = -1; dy <= 1; dy++)
        for (dx = -1; dx <= 1; dx++)
            if (dy || dx)
                n += grid[(y + dy + H) % H][(x + dx + W) % W];
    return n;
}

static void show(int gen)
{
    int y, x;
    printf("generation %d\n", gen);
    for (y = 0; y < H; y++) {
        for (x = 0; x < W; x++)
            putchar(grid[y][x] ? '#' : '.');
        putchar('\n');
    }
}

int main(void)
{
    int gen, y, x;
    grid[0][1] = grid[1][2] = grid[2][0] = grid[2][1] = grid[2][2] = 1;   /* glider */
    grid[6][6] = grid[6][7] = grid[6][8] = 1;                              /* blinker */
    for (gen = 0; gen < 4; gen++) {
        if (gen == 0 || gen == 3)
            show(gen);
        for (y = 0; y < H; y++)
            for (x = 0; x < W; x++) {
                int n = neighbours(y, x);
                next[y][x] = n == 3 || (n == 2 && grid[y][x]);
            }
        for (y = 0; y < H; y++)
            for (x = 0; x < W; x++)
                grid[y][x] = next[y][x];
    }
    return 0;
}
