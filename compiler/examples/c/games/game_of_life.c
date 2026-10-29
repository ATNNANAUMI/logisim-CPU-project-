/* game_of_life.c - Conway's Game of Life on the RGB screen
 *
 * python compiler/src/cc build compiler/examples/c/games/game_of_life.c, then open
 *     compiler/ROM/game_of_life.rom in the simulator window (the "RGB screen"
 *     tab; "max" speed)
 * pypy3 compiler/src/cc run compiler/examples/c/games/game_of_life.c --steps 20000000 --screen life.png
 *
 * The world is 64 x 64 cells, 2 x 2 pixels each, and wraps around at the
 * edges (a torus: what leaves on the right comes back on the left). A cell
 * with 3 live neighbours is born, one with 2 or 3 survives, the rest die.
 * Only the cells that change are redrawn, and rows with nothing alive near
 * them are skipped.
 *
 * It starts by checking itself on well-known patterns (still lifes stay,
 * oscillators come back after their period, spaceships move, the diehard
 * dies after 130 generations, the glider gun fires every 30), then shows
 * seven scenes, one after the other, round and round:
 *   1  Gosper glider gun, its gliders eaten by an eater: repeats every 30
 *   2  oscillators (pulsar, pentadecathlon, Kok's galaxy, blinker, toad,
 *      beacon, clock) and still lifes (block, beehive, loaf, boat, tub):
 *      back to the start every 120 generations
 *   3  spaceships: LWSS, MWSS and HWSS in six lanes, back every 128
 *   4  R-pentomino, 5 diehard, 6 acorn: small starts that grow
 *   7  a random soup
 * The generation number is on the hex display (in hex); the text display
 * gets the scene's name and the population every 100 generations.
 *
 * Keys (the simulator window's keyboard): 1-7 a scene, n the next one,
 * r restart this one (a new soup for 7), space pause/continue, s one
 * generation while paused, q quit (back to the OS's shell when it was run
 * from there: os/shell.c).
 *
 *   -D SCENE=n        start with scene n (default 1)
 *   -D FULL_TEST      also check that scenes 1-3 repeat (27 checks, about
 *                     110 million instructions: use pypy3 and --steps 200000000)
 *
 * A generation takes 100 000 to 160 000 instructions (the random soup
 * about 330 000), the self-test about 7 million. The simulator under plain
 * python runs about 3 million instructions a second (20-30 generations,
 * 10 for the soup); pypy3 about ten times that. Not for the circuit (160
 * instructions a second, and it still has the old memory map).
 *
 * Expected output (the first lines):
 *   Game of Life
 *   self-test: 24 of 24 passed
 *   scene 1: Gosper glider gun + eater (period 30)
 *   gen 100: 70 cells
 *   gen 200: 81 cells
 */
#include <cpu.h>
#include <gfx.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#ifndef SCENE
#define SCENE 1
#endif

#define MAX 64                          /* the world's largest size */
#define CELL (GFX_WIDTH / MAX)          /* pixels per cell side */

/* Patterns: rows of '.' (dead) and 'O' (alive), separated by '/' */
static const char GLIDER[] = ".O./..O/OOO";
static const char LWSS[] = ".O..O/O..../O...O/OOOO.";            /* these three fly left */
static const char MWSS[] = "...O../.O...O/O...../O....O/OOOOO.";
static const char HWSS[] = "...OO../.O....O/O....../O.....O/OOOOOO.";
static const char BLINKER[] = "OOO";
static const char TOAD[] = ".OOO/OOO.";
static const char BEACON[] = "OO../OO../..OO/..OO";
static const char CLOCK[] = "..O./O.O./.O.O/.O..";
static const char PULSAR[] =
    "..OOO...OOO../............./O....O.O....O/O....O.O....O/O....O.O....O/"
    "..OOO...OOO../............./..OOO...OOO../O....O.O....O/O....O.O....O/"
    "O....O.O....O/............./..OOO...OOO..";
static const char PENTADECATHLON[] = "..O....O../OO.OOOO.OO/..O....O..";
static const char GALAXY[] =
    "OOOOOO.OO/OOOOOO.OO/.......OO/OO.....OO/OO.....OO/OO.....OO/OO......./"
    "OO.OOOOOO/OO.OOOOOO";
static const char BLOCK[] = "OO/OO";
static const char BEEHIVE[] = ".OO./O..O/.OO.";
static const char LOAF[] = ".OO./O..O/.O.O/..O.";
static const char BOAT[] = "OO./O.O/.O.";
static const char TUB[] = ".O./O.O/.O.";
static const char GOSPER_GUN[] =
    "........................O.........../......................O.O.........../"
    "............OO......OO............OO/...........O...O....OO............OO/"
    "OO........O.....O...OO............../OO........O...O.OO....O.O.........../"
    "..........O.....O.......O.........../...........O...O..................../"
    "............OO......................";
static const char EATER[] = "OO../O.O./..O./..OO";
static const char R_PENTOMINO[] = ".OO/OO./.O.";
static const char DIEHARD[] = "......O./OO....../.O...OOO";
static const char ACORN[] = ".O...../...O.../OO..OOO";

struct item {
    const char *pattern;
    int x, y;                           /* its top-left corner */
    int flip;                           /* 1: mirrored left to right */
};

struct scene {
    const char *name;
    const struct item *items;
    int count;                          /* 0: a random soup */
    int gens;                           /* how long it is shown */
    int color;
};

/* The placements were checked with a reference Life in Python: nothing in
 * scenes 2 and 3 ever touches anything else, and the eater sits on the
 * gun's glider path (-D FULL_TEST checks all three here too). */
static const struct item gun_items[] = {
    {GOSPER_GUN, 2, 2, 0}, {EATER, 56, 42, 0},
};
static const struct item gallery_items[] = {
    {PULSAR, 3, 3, 0}, {PENTADECATHLON, 25, 8, 0}, {GALAXY, 45, 5, 0},
    {BLINKER, 4, 27, 0}, {TOAD, 13, 27, 0}, {BEACON, 23, 26, 0}, {CLOCK, 33, 26, 0},
    {BLOCK, 4, 42, 0}, {BEEHIVE, 12, 42, 0}, {LOAF, 22, 41, 0}, {BOAT, 32, 42, 0},
    {TUB, 41, 42, 0},
};
static const struct item ship_items[] = {
    {LWSS, 4, 4, 0}, {LWSS, 36, 4, 0}, {MWSS, 10, 14, 1}, {MWSS, 42, 14, 1},
    {HWSS, 6, 25, 0}, {HWSS, 38, 25, 0}, {HWSS, 20, 36, 1}, {HWSS, 52, 36, 1},
    {LWSS, 20, 47, 1}, {LWSS, 52, 47, 1}, {MWSS, 12, 56, 0}, {MWSS, 44, 56, 0},
};
static const struct item rpent_items[] = {{R_PENTOMINO, 31, 31, 0}};
static const struct item diehard_items[] = {{DIEHARD, 28, 31, 0}};
static const struct item acorn_items[] = {{ACORN, 29, 31, 0}};

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))

static const struct scene scenes[] = {
    {"Gosper glider gun + eater (period 30)", gun_items, COUNT(gun_items), 300, GFX_YELLOW},
    {"oscillators and still lifes", gallery_items, COUNT(gallery_items), 240, GFX_CYAN},
    {"spaceships: LWSS, MWSS, HWSS", ship_items, COUNT(ship_items), 256, GFX_GREEN},
    {"R-pentomino", rpent_items, 1, 800, GFX_ORANGE},
    {"diehard (gone at generation 130)", diehard_items, 1, 160, GFX_PINK},
    {"acorn", acorn_items, 1, 1000, GFX_MAGENTA},
    {"random soup", 0, 0, 600, GFX_WHITE},
};

#define SCENES ((int)COUNT(scenes))

/* world[cur] is the current generation, world[cur ^ 1] the next one;
 * world[2] keeps a copy for the self-test to compare with. Cell (x, y) is
 * world[b][y + 1][x]. Around the cells, step() puts copies that make the
 * world wrap: column `width` copies column 0, row 0 copies the last row
 * and row height + 1 the first, so every neighbour is at a fixed offset. */
#define STRIDE (MAX + 1)                /* from a cell to the one below it */
static char world[3][MAX + 2][STRIDE];
#define CELL_AT(b, x, y) world[b][(y) + 1][x]
static int row_count[2][MAX];           /* live cells in each row of world[0] and [1] */
static int width = MAX, height = MAX;
static int cur;
static int generation, population;
static int drawing;                     /* 0 while the self-test runs */
static int color;

static void draw_cell(int x, int y, int alive)
{
    unsigned int word = ((unsigned int)(x * CELL) << GFX_X_SHIFT) | ((y * CELL) << GFX_Y_SHIFT)
                        | (alive ? color : GFX_BLACK);
    int i, j;
    for (j = 0; j < CELL; j++)
        for (i = 0; i < CELL; i++)
            device_out(GFX_DEVICE, word + ((unsigned int)i << GFX_X_SHIFT) + (j << GFX_Y_SHIFT));
}

/* redraws the cells of row y that differ between old and new */
static void draw_row(const char *old, const char *new, int y)
{
    int x;
    for (x = 0; x < width; x++)
        if (old[x] != new[x])
            draw_cell(x, y, new[x]);
}

/* an empty world of w x h cells (at most MAX x MAX) */
static void clear_world(int w, int h)
{
    int b, x, y;
    width = w;
    height = h;
    for (b = 0; b < 2; b++) {
        for (y = 0; y < h + 2; y++)
            for (x = 0; x <= w; x++)
                world[b][y][x] = 0;
        for (y = 0; y < h; y++)
            row_count[b][y] = 0;
    }
    generation = population = 0;
}

static void set_cell(int x, int y)
{
    x = (x % width + width) % width;
    y = (y % height + height) % height;
    if (!CELL_AT(cur, x, y)) {
        CELL_AT(cur, x, y) = 1;
        row_count[cur][y]++;
        population++;
        if (drawing)
            draw_cell(x, y, 1);
    }
}

/* puts a pattern with its top-left corner at (x, y) */
static void place(const char *p, int x, int y, int flip)
{
    int w = 0, i = 0, j = 0;
    while (p[w] && p[w] != '/')
        w++;
    for (; *p; p++) {
        if (*p == '/') {
            j++;
            i = 0;
            continue;
        }
        if (*p == 'O')
            set_cell(flip ? x + w - 1 - i : x + i, y + j);
        i++;
    }
}

/* The inner loop is written for this compiler, which gives registers to
 * about seven variables: it uses seven, and calls nothing (a call saves
 * every register variable around it). It slides a window of three column
 * sums (the cells above, at and below) along the row; their total counts
 * the cell itself too, so 3 means born or survives and 4 survives if
 * alive. A row's count changes only where a cell does, and only rows
 * where something changed are redrawn, afterwards. */
static void step(void)
{
    char (*now)[STRIDE] = world[cur], (*next)[STRIDE] = world[cur ^ 1];
    int *count = row_count[cur], *next_count = row_count[cur ^ 1];
    int w = width, h = height, x, y, left, mid, right, alive, live, changes, total = 0;
    char *p, *q, *end;

    for (y = 1; y <= h; y++)
        now[y][w] = now[y][0];
    for (x = 0; x <= w; x++) {
        now[0][x] = now[h][x];
        now[h + 1][x] = now[1][x];
    }
    for (y = 0; y < h; y++) {
        int up = y == 0 ? h - 1 : y - 1, down = y == h - 1 ? 0 : y + 1;
        q = next[y + 1];
        if (count[up] + count[y] + count[down] == 0) {
            /* nothing alive near: the row stays empty */
            if (next_count[y]) {
                for (end = q + w; q < end; q++)
                    *q = 0;
                next_count[y] = 0;
            }
            continue;
        }
        p = now[y + 1];
        end = p + w;
        left = p[w - 1 - STRIDE] + p[w - 1] + p[w - 1 + STRIDE];
        mid = p[-STRIDE] + p[0] + p[STRIDE];
        live = count[y];
        changes = 0;
        for (; p < end; p++, q++) {
            right = p[1 - STRIDE] + p[1] + p[1 + STRIDE];
            left += mid + right;
            alive = left == 3 || (left == 4 && *p);
            *q = alive;
            if (alive != *p) {
                live += alive - *p;
                changes++;
            }
            left = mid;
            mid = right;
        }
        if (changes && drawing)
            draw_row(now[y + 1], next[y + 1], y);
        next_count[y] = live;
        total += live;
    }
    cur ^= 1;
    population = total;
    generation++;
}

static void run(int gens)
{
    while (gens-- > 0)
        step();
}

static void snapshot(void)
{
    int x, y;
    for (y = 0; y < height; y++)
        for (x = 0; x < width; x++)
            CELL_AT(2, x, y) = CELL_AT(cur, x, y);
}

static int same_as_snapshot(void)
{
    int x, y;
    for (y = 0; y < height; y++)
        for (x = 0; x < width; x++)
            if (CELL_AT(2, x, y) != CELL_AT(cur, x, y))
                return 0;
    return 1;
}


static void start_scene(int s)
{
    const struct scene *sc = &scenes[s];
    int i, x, y;

    drawing = 0;
    clear_world(MAX, MAX);
    gfx_fill_rect(0, 0, GFX_WIDTH, GFX_HEIGHT, GFX_BLACK);   /* gfx_clear() isn't on the circuit */
    color = sc->color;
    drawing = 1;
    for (i = 0; i < sc->count; i++)
        place(sc->items[i].pattern, sc->items[i].x, sc->items[i].y, sc->items[i].flip);
    if (sc->count == 0) {
        srand((unsigned int)clock());
        for (y = 0; y < height; y++)
            for (x = 0; x < width; x++)
                if (rand() % 3 == 0)
                    set_cell(x, y);
    }
    show_hex(0);
    printf("scene %d: %s\n", s + 1, sc->name);
}

/* --- self-test ----------------------------------------------------------- */

static int tests, passed;

static void result(const char *what, int ok)
{
    tests++;
    if (ok)
        passed++;
    else
        printf("FAILED: %s\n", what);
}

/* after `period` generations (and not before) it is back where it was */
static void check_period(const char *name, const char *p, int period)
{
    int g;
    clear_world(32, 32);
    place(p, 8, 8, 0);
    snapshot();
    for (g = 1; g <= period; g++) {
        step();
        if (same_as_snapshot())
            break;
    }
    result(name, g == period);
}

/* after `gens` generations it is the same shape, moved by (dx, dy) */
static void check_moves(const char *name, const char *p, int flip, int gens, int dx, int dy)
{
    clear_world(32, 32);
    place(p, 12 + dx, 12 + dy, flip);
    snapshot();
    clear_world(32, 32);
    place(p, 12, 12, flip);
    run(gens);
    result(name, same_as_snapshot());
}

#ifdef FULL_TEST
/* the scene is back where it was after `period` generations, once the
 * first `settle` are over */
static void check_scene(int s, int settle, int period)
{
    int i;
    clear_world(MAX, MAX);
    for (i = 0; i < scenes[s].count; i++)
        place(scenes[s].items[i].pattern, scenes[s].items[i].x, scenes[s].items[i].y,
              scenes[s].items[i].flip);
    run(settle);
    snapshot();
    run(period - 1);
    i = same_as_snapshot();
    step();
    result(scenes[s].name, !i && same_as_snapshot());
}
#endif

static void self_test(void)
{
    int pop;

    drawing = 0;
    check_period("block", BLOCK, 1);
    check_period("beehive", BEEHIVE, 1);
    check_period("loaf", LOAF, 1);
    check_period("boat", BOAT, 1);
    check_period("tub", TUB, 1);
    check_period("blinker", BLINKER, 2);
    check_period("toad", TOAD, 2);
    check_period("beacon", BEACON, 2);
    check_period("clock", CLOCK, 2);
    check_period("pulsar", PULSAR, 3);
    check_period("Kok's galaxy", GALAXY, 8);
    check_period("pentadecathlon", PENTADECATHLON, 15);

    check_moves("glider", GLIDER, 0, 4, 1, 1);
    check_moves("mirrored glider", GLIDER, 1, 4, -1, 1);
    check_moves("LWSS", LWSS, 0, 4, -2, 0);
    check_moves("MWSS", MWSS, 0, 4, -2, 0);
    check_moves("HWSS", HWSS, 0, 4, -2, 0);
    check_moves("mirrored HWSS", HWSS, 1, 4, 2, 0);
    /* the edges wrap: on a 16 x 16 world a glider is home after 64 */
    clear_world(16, 16);
    place(GLIDER, 14, 14, 0);
    snapshot();
    run(64);
    result("glider around the world", same_as_snapshot());

    /* the diehard is gone after exactly 130 generations */
    clear_world(24, 24);
    place(DIEHARD, 8, 11, 0);
    run(129);
    result("diehard alive at 129", population > 0);
    step();
    result("diehard dead at 130", population == 0);

    /* the glider gun: 36 cells, plus a 5-cell glider every 30 generations */
    clear_world(MAX, MAX);
    place(GOSPER_GUN, 2, 2, 0);
    pop = population;
    run(30);
    result("glider gun: 36 cells", pop == 36);
    result("glider gun: one glider at 30", population == 41);
    run(30);
    result("glider gun: two gliders at 60", population == 46);

#ifdef FULL_TEST
    check_scene(0, 240, 30);
    check_scene(1, 0, 120);
    check_scene(2, 0, 128);
#endif
    printf("self-test: %d of %d passed\n", passed, tests);
}

int main(void)
{
    int scene = SCENE - 1, paused = 0, key, died;

    printf("Game of Life\n");
    self_test();
    start_scene(scene);
    died = 0;
    for (;;) {
        key = key_pressed();
        if (key == 'q')
            return 0;
        if (key >= '1' && key < '1' + SCENES) {
            scene = key - '1';
            start_scene(scene);
            died = 0;
            continue;
        }
        if (key == 'n' || key == 'r') {
            if (key == 'n')
                scene = (scene + 1) % SCENES;
            start_scene(scene);
            died = 0;
            continue;
        }
        if (key == ' ')
            paused = !paused;
        if (paused && key != 's')
            continue;

        step();
        show_hex(generation);
        if (population == 0 && !died) {
            printf("gen %d: everything died\n", generation);
            died = 1;
        } else if (generation % 100 == 0)
            printf("gen %d: %d cells\n", generation, population);
        if (generation >= scenes[scene].gens && !paused) {
            scene = (scene + 1) % SCENES;
            start_scene(scene);
            died = 0;
        }
    }
}
