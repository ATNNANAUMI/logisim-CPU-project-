/* maze3d.c - walk through a maze in first-person 3D (a raycaster)
 *
 *   python compiler/src/cc build compiler/examples/c/games/maze3d.c   then open
 *   compiler/ROM/maze3d.rom in the simulator window (the "RGB screen" tab),
 *   or under Tynix:  maze3d [SEED]
 *
 * W / S walk forward / back, A / D turn, Q / E sidestep, M shows the
 * minimap, R makes a new maze, Esc-free quit with X (back to the shell when
 * run from there). Find the green door in the far corner of the maze: the
 * time it took is printed on the text display.
 *
 * The technique is a grid raycaster: one ray per screen column (128 columns,
 * 2 pixels wide each) steps from cell to cell (DDA) until it hits a wall; the
 * wall's height on the screen is 1 / its distance. All art is made of colours
 * computed here, in 32-bit floats. The keyboard gives presses only, so a key
 * is one step or one turn (holding it works through the PC's auto-repeat).
 * Only the columns whose picture changed since the last frame are redrawn.
 *
 * The maze comes from a seed (default 1): the same seed is always the same
 * maze, so a scripted run can be checked (the self-check does).
 */
#include <cpu.h>
#include <gfx.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define CELLS 8                         /* the maze is CELLS x CELLS rooms ... */
#define SIZE (2 * CELLS + 1)            /* ... on a SIZE x SIZE grid with walls between */
#define COLS 128                        /* rays; each is 2 pixels wide */
#define VIEW_H 176                      /* the 3D view; the minimap and text are below */
#define STEP 0.35f
#define TURN 0.2618f                    /* 15 degrees */
#define CEILING GFX_RGB(40, 44, 70)
#define FLOOR GFX_RGB(70, 60, 50)

static char map[SIZE][SIZE];            /* 1 wall, 0 open, 2 the door */
static float px, py, dir_x, dir_y, plane_x, plane_y;
static int shown_top[COLS], shown_bottom[COLS], shown_color[COLS];

static int mod_rand(int n)
{
    return rand() % n;
}

/* depth-first search from the top-left room: the walls between rooms are knocked down */
static void make_maze(void)
{
    int stack[CELLS * CELLS][2], top = 0, x, y;
    static const int dx[4] = {0, 1, 0, -1}, dy[4] = {-1, 0, 1, 0};

    for (y = 0; y < SIZE; y++)
        for (x = 0; x < SIZE; x++)
            map[y][x] = 1;
    map[1][1] = 0;
    stack[0][0] = stack[0][1] = 0;
    top = 1;
    while (top) {
        int cx = stack[top - 1][0], cy = stack[top - 1][1], tries[4], n = 0, d;
        for (d = 0; d < 4; d++) {
            int nx = cx + dx[d], ny = cy + dy[d];
            if (nx >= 0 && ny >= 0 && nx < CELLS && ny < CELLS && map[2 * ny + 1][2 * nx + 1] == 1)
                tries[n++] = d;
        }
        if (n == 0) {
            top--;
            continue;
        }
        d = tries[mod_rand(n)];
        map[cy * 2 + 1 + dy[d]][cx * 2 + 1 + dx[d]] = 0;        /* the wall between */
        map[(cy + dy[d]) * 2 + 1][(cx + dx[d]) * 2 + 1] = 0;
        stack[top][0] = cx + dx[d];
        stack[top][1] = cy + dy[d];
        top++;
    }
    map[SIZE - 2][SIZE - 1] = 2;                                /* the door, in the far corner's outer wall */
}

static void start_position(void)
{
    px = py = 1.5f;
    dir_x = 1;
    dir_y = 0;
    plane_x = 0;
    plane_y = 0.66f;                                            /* about a 66 degree field of view */
}

static void turn(float a)
{
    float c = cos(a), s = sin(a), t;
    t = dir_x * c - dir_y * s;
    dir_y = dir_x * s + dir_y * c;
    dir_x = t;
    t = plane_x * c - plane_y * s;
    plane_y = plane_x * s + plane_y * c;
    plane_x = t;
}

/* one column: the wall's top and bottom row and its colour */
static void cast(int col, int *top, int *bottom, int *color)
{
    float camera = 2.0f * col / COLS - 1.0f;
    float rx = dir_x + plane_x * camera, ry = dir_y + plane_y * camera;
    int mx = (int)px, my = (int)py, side = 0, step_x, step_y, hit = 0, steps = 0;
    float dx = rx == 0 ? 1e30f : fabs(1.0f / rx), dy = ry == 0 ? 1e30f : fabs(1.0f / ry);
    float side_x, side_y, dist;
    int h, kind = 1;

    if (rx < 0) { step_x = -1; side_x = (px - mx) * dx; } else { step_x = 1; side_x = (mx + 1.0f - px) * dx; }
    if (ry < 0) { step_y = -1; side_y = (py - my) * dy; } else { step_y = 1; side_y = (my + 1.0f - py) * dy; }
    while (!hit && steps++ < SIZE * 2) {
        if (side_x < side_y) { side_x += dx; mx += step_x; side = 0; }
        else { side_y += dy; my += step_y; side = 1; }
        if (mx < 0 || my < 0 || mx >= SIZE || my >= SIZE || map[my][mx]) {
            hit = 1;
            kind = (mx >= 0 && my >= 0 && mx < SIZE && my < SIZE) ? map[my][mx] : 1;
        }
    }
    dist = side == 0 ? side_x - dx : side_y - dy;
    if (dist < 0.05f)
        dist = 0.05f;
    h = (int)(VIEW_H / dist);
    if (h > VIEW_H)
        h = VIEW_H;
    *top = (VIEW_H - h) / 2;
    *bottom = *top + h;
    {
        int shade = (int)(255.0f / (1.0f + dist * 0.6f)) >> side;       /* darker far away and on one pair of faces */
        *color = kind == 2 ? GFX_RGB(0, shade, 40) : GFX_RGB(shade, shade * 3 / 4, shade / 2);
    }
}

static void draw_view(int force)
{
    int col;
    for (col = 0; col < COLS; col++) {
        int top, bottom, color;
        cast(col, &top, &bottom, &color);
        if (!force && top == shown_top[col] && bottom == shown_bottom[col] && color == shown_color[col])
            continue;
        if (top > 0)
            gfx_fill_rect(col * 2, 0, 2, top, CEILING);
        gfx_fill_rect(col * 2, top, 2, bottom - top, color);
        if (bottom < VIEW_H)
            gfx_fill_rect(col * 2, bottom, 2, VIEW_H - bottom, FLOOR);
        shown_top[col] = top;
        shown_bottom[col] = bottom;
        shown_color[col] = color;
    }
}

static void draw_minimap(int on)
{
    int x, y;
    gfx_fill_rect(0, VIEW_H, GFX_WIDTH, GFX_HEIGHT - VIEW_H, GFX_BLACK);
    if (on) {
        for (y = 0; y < SIZE; y++)
            for (x = 0; x < SIZE; x++)
                gfx_fill_rect(4 + x * 4, VIEW_H + 4 + y * 4 - 0, 4, 4,
                              map[y][x] == 2 ? GFX_GREEN : map[y][x] ? GFX_GRAY : GFX_BLACK);
        gfx_fill_rect(4 + (int)(px * 4) - 1, VIEW_H + 4 + (int)(py * 4) - 1, 3, 3, GFX_RED);
    }
    gfx_text(80, VIEW_H + 6, "W S walk  A D turn  Q E side", GFX_WHITE, GFX_NONE);
    gfx_text(80, VIEW_H + 16, "M map  R new maze  X quit", GFX_WHITE, GFX_NONE);
    gfx_text(80, VIEW_H + 30, "find the green door", GFX_GREEN, GFX_NONE);
}

static int try_move(float nx, float ny)
{
    int cell = map[(int)ny][(int)nx];
    if (cell == 1)
        return 0;
    px = nx;
    py = ny;
    return cell == 2 ? 2 : 1;
}

int main(int argc, char **argv)
{
    int minimap = 1, seed = argc > 1 ? atoi(argv[1]) : 1, key, moved, won = 0;
    clock_t began;

    srand(seed);
    make_maze();
    start_position();
    gfx_clear();
    began = clock();
    draw_view(1);
    draw_minimap(minimap);
    for (;;) {
        if (gfx_lost()) {                       /* under Tynix: the screen was taken and given back */
            draw_view(1);
            draw_minimap(minimap);
        }
        key = key_pressed();
        if (!key)
            continue;
        moved = 0;
        switch (key | 0x20) {                   /* either case */
        case 'w': moved = try_move(px + dir_x * STEP, py + dir_y * STEP); break;
        case 's': moved = try_move(px - dir_x * STEP, py - dir_y * STEP); break;
        case 'q': moved = try_move(px - plane_x * STEP, py - plane_y * STEP); break;
        case 'e': moved = try_move(px + plane_x * STEP, py + plane_y * STEP); break;
        case 'a': turn(-TURN); moved = 1; break;
        case 'd': turn(TURN); moved = 1; break;
        case 'm': minimap = !minimap; moved = 1; break;
        case 'r':
            seed++;
            srand(seed);
            make_maze();
            start_position();
            began = clock();
            draw_view(1);
            moved = 1;
            break;
        case 'x':
            return 0;
        }
        if (moved == 2) {
            won = 1;
            break;
        }
        if (moved) {
            draw_view(0);
            draw_minimap(minimap);
        }
    }
    printf("out in %d seconds\n", (int)((clock() - began) / 1000));
    return won ? 0 : 1;
}
