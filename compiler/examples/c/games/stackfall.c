/* stackfall.c - Stackfall: a falling-block puzzle with gravity chains
 *
 *   python compiler/src/cc build compiler/examples/c/games/stackfall.c, then open
 *       compiler/ROM/stackfall.rom in the simulator window (the "RGB screen" tab)
 *   or, under Tynix: stackfall   (tynix/make_disk.py puts it in /bin)
 *
 * Pieces of four cells fall into a well 10 wide and 20 deep; a full row
 * clears. The twist: after a clear, every block with nothing under it falls
 * on its own (cell by cell, not row by row), and the rows that fills clear
 * too: a chain. Each step of a chain multiplies what it scores (x1, x2, x3 ...).
 *
 * Keys: A/D move, W rotates, S drops one row, space drops to the bottom,
 * P pauses, Q (or Ctrl-D) quits, R starts again after the game ends. Every 10
 * rows the level goes up and the pieces fall faster (clock(): the timer).
 * Score: rows cleared at once 1/2/3/4 give 100/300/500/800, times the level,
 * times the step of the chain. Under Tynix the screen is drawn again when the
 * game gets the foreground back (gfx_lost()).
 *
 * At the end it prints "Stackfall: score S, rows R, level L, longest chain C"
 * on the text display. Only the cells that change are drawn again.
 */
#include <cpu.h>
#include <gfx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define W 10
#define H 20
#define CELL 12
#define WELL_X 8
#define WELL_Y 8
#define PANEL_X 140

#define C_BG      GFX_RGB(16, 18, 30)
#define C_WELL    GFX_RGB(28, 30, 48)
#define C_FRAME   GFX_RGB(90, 96, 140)
#define C_TEXT    GFX_RGB(230, 232, 245)
#define C_DIM     GFX_RGB(130, 136, 170)
#define C_FLASH   GFX_RGB(255, 255, 255)

/* the pieces: 4 cells each, as (x, y) in a 4 x 4 box, first rotation */
static const int shapes[7][8] = {
    {0, 1, 1, 1, 2, 1, 3, 1},   /* the bar */
    {1, 0, 2, 0, 1, 1, 2, 1},   /* the square */
    {1, 0, 0, 1, 1, 1, 2, 1},   /* the tee */
    {1, 0, 2, 0, 0, 1, 1, 1},   /* the step right */
    {0, 0, 1, 0, 1, 1, 2, 1},   /* the step left */
    {0, 0, 0, 1, 1, 1, 2, 1},   /* the hook left */
    {2, 0, 0, 1, 1, 1, 2, 1},   /* the hook right */
};
static const unsigned colors[7] = {
    GFX_RGB(80, 200, 230), GFX_RGB(240, 200, 70), GFX_RGB(190, 110, 230),
    GFX_RGB(110, 220, 120), GFX_RGB(240, 100, 110), GFX_RGB(90, 130, 240),
    GFX_RGB(245, 150, 70),
};

static unsigned board[H][W];        /* 0 empty, else the cell's colour */
static unsigned shown[H][W];        /* what the screen shows (for drawing only changes) */
static int piece, rot, px, py;      /* the falling piece */
static int next_piece;
static int score, rows, level, chain_best, best;
static int over, paused, quit;
static unsigned next_fall;

/* cell i of piece p turned r quarter turns, in its 4 x 4 box */
static void cell(int p, int r, int i, int *x, int *y)
{
    int cx = shapes[p][2 * i], cy = shapes[p][2 * i + 1], t;
    if (p == 1) {                   /* the square doesn't turn */
        *x = cx;
        *y = cy;
        return;
    }
    while (r-- > 0) {               /* a quarter turn clockwise inside the 3 x 3 (4 x 4 for the bar) */
        int n = p == 0 ? 3 : 2;
        t = cx;
        cx = n - cy;
        cy = t;
    }
    *x = cx;
    *y = cy;
}

static int fits(int p, int r, int x, int y)
{
    int i, cx, cy;
    for (i = 0; i < 4; i++) {
        cell(p, r, i, &cx, &cy);
        cx += x;
        cy += y;
        if (cx < 0 || cx >= W || cy >= H)
            return 0;
        if (cy >= 0 && board[cy][cx])
            return 0;
    }
    return 1;
}

static unsigned fall_time(void)
{
    int t = 800 - 70 * (level - 1);
    return t < 100 ? 100 : t;
}

/* ------------------------------------------------------------- drawing */

static void draw_block(int sx, int sy, unsigned color)
{
    if (color == 0) {
        gfx_fill_rect(sx, sy, CELL, CELL, C_WELL);
        return;
    }
    gfx_fill_rect(sx, sy, CELL - 1, CELL - 1, color);
    gfx_hline(sx + 1, sy + 1, CELL - 4, C_FLASH);          /* a lit top edge: a gem */
    gfx_vline(sx + 1, sy + 1, CELL - 4, C_FLASH);
}

static void draw_number(int x, int y, const char *label, int value)
{
    char text[24];
    sprintf(text, "%-6s%6d", label, value);
    gfx_text(x, y, text, C_TEXT, C_BG);
}

static void draw_panel(void)
{
    draw_number(PANEL_X, 70, "SCORE", score);
    draw_number(PANEL_X, 84, "ROWS", rows);
    draw_number(PANEL_X, 98, "LEVEL", level);
    draw_number(PANEL_X, 112, "CHAIN", chain_best);
    draw_number(PANEL_X, 126, "BEST", best);
}

static void draw_next(void)
{
    int i, cx, cy;
    gfx_fill_rect(PANEL_X, 28, 4 * CELL, 2 * CELL, C_BG);
    for (i = 0; i < 4; i++) {
        cell(next_piece, 0, i, &cx, &cy);
        draw_block(PANEL_X + cx * CELL, 28 + cy * CELL, colors[next_piece]);
    }
}

static void draw_frame(void)
{
    int y, x;
    gfx_fill(C_BG);
    gfx_rect(WELL_X - 2, WELL_Y - 2, W * CELL + 4, H * CELL + 4, C_FRAME);
    gfx_text(PANEL_X, 8, "STACKFALL", C_TEXT, C_BG);
    gfx_text(PANEL_X, 18, "next", C_DIM, C_BG);
    gfx_text(PANEL_X, 150, "A D  move", C_DIM, C_BG);
    gfx_text(PANEL_X, 160, "W    turn", C_DIM, C_BG);
    gfx_text(PANEL_X, 170, "S    down", C_DIM, C_BG);
    gfx_text(PANEL_X, 180, "spc  drop", C_DIM, C_BG);
    gfx_text(PANEL_X, 190, "P    pause", C_DIM, C_BG);
    gfx_text(PANEL_X, 200, "Q    quit", C_DIM, C_BG);
    for (y = 0; y < H; y++)
        for (x = 0; x < W; x++)
            shown[y][x] = 0xFFFFFFFF;       /* nothing is known: all drawn */
    draw_next();
    draw_panel();
}

/* the board with the falling piece on it, drawing the cells that changed */
static void draw_board(void)
{
    static unsigned want[H][W];
    int x, y, i, cx, cy;
    memcpy(want, board, sizeof board);
    if (!over) {
        for (i = 0; i < 4; i++) {
            cell(piece, rot, i, &cx, &cy);
            if (py + cy >= 0)
                want[py + cy][px + cx] = colors[piece];
        }
    }
    for (y = 0; y < H; y++)
        for (x = 0; x < W; x++)
            if (want[y][x] != shown[y][x]) {
                draw_block(WELL_X + x * CELL, WELL_Y + y * CELL, want[y][x]);
                shown[y][x] = want[y][x];
            }
}

static void message(const char *line1, const char *line2)
{
    gfx_fill_rect(WELL_X + 6, WELL_Y + 100, W * CELL - 12, 34, C_BG);
    gfx_rect(WELL_X + 6, WELL_Y + 100, W * CELL - 12, 34, C_FRAME);
    gfx_text(WELL_X + 12, WELL_Y + 106, line1, C_TEXT, C_BG);
    gfx_text(WELL_X + 12, WELL_Y + 120, line2, C_DIM, C_BG);
    for (int y = 8; y < 12; y++)            /* drawn over: the board shows again after */
        for (int x = 0; x < W; x++)
            shown[y][x] = 0xFFFFFFFF;
}

/* ---------------------------------------------------------------- rules */

static void new_piece(void)
{
    piece = next_piece;
    next_piece = rand() % 7;
    rot = 0;
    px = 3;
    py = -1;
    draw_next();
    if (!fits(piece, rot, px, py + 1)) {
        over = 1;
        if (score > best)
            best = score;
        draw_panel();
    }
}

static int full(int y)
{
    int x;
    for (x = 0; x < W; x++)
        if (!board[y][x])
            return 0;
    return 1;
}

/* every block with nothing under it falls as far as it can; 1 if one moved */
static int settle(void)
{
    int x, y, moved = 0;
    for (x = 0; x < W; x++) {
        int to = H - 1;
        for (y = H - 1; y >= 0; y--)
            if (board[y][x]) {
                if (y != to) {
                    board[to][x] = board[y][x];
                    board[y][x] = 0;
                    moved = 1;
                }
                to--;
            }
    }
    return moved;
}

/* the full rows go, then the chain: settle, clear again, ... */
static void clear_rows(void)
{
    static const int points[5] = {0, 100, 300, 500, 800};
    int step = 0;
    for (;;) {
        int y, x, n = 0;
        for (y = 0; y < H; y++)
            if (full(y)) {
                n++;
                for (x = 0; x < W; x++)
                    board[y][x] = 0;
            }
        if (n == 0)
            break;
        step++;
        rows += n;
        score += points[n > 4 ? 4 : n] * level * step;
        if (step > chain_best)
            chain_best = step;
        level = 1 + rows / 10;
        draw_board();                       /* the cleared rows, a moment */
        wait_ms(60);
        if (!settle())
            break;
        draw_board();
        wait_ms(60);
    }
    draw_panel();
}

static void lock_piece(void)
{
    int i, cx, cy;
    for (i = 0; i < 4; i++) {
        cell(piece, rot, i, &cx, &cy);
        if (py + cy < 0) {                  /* it stopped above the well */
            over = 1;
            continue;
        }
        board[py + cy][px + cx] = colors[piece];
    }
    if (over) {
        if (score > best)
            best = score;
        draw_panel();
        return;
    }
    clear_rows();
    new_piece();
}

/* one row down; at the bottom it locks */
static void down(void)
{
    if (fits(piece, rot, px, py + 1))
        py++;
    else
        lock_piece();
    next_fall = clock() + fall_time();
}

static void turn(void)
{
    int r = (rot + 1) & 3;
    static const int kick[3] = {0, -1, 1};      /* try in place, then a step aside */
    int i;
    for (i = 0; i < 3; i++)
        if (fits(piece, r, px + kick[i], py)) {
            rot = r;
            px += kick[i];
            return;
        }
}

static void start(void)
{
    memset(board, 0, sizeof board);
    score = rows = chain_best = 0;
    level = 1;
    over = paused = 0;
    next_piece = rand() % 7;
    new_piece();
    draw_frame();
    next_fall = clock() + fall_time();
}

static void key(int k)
{
    if (k >= 'A' && k <= 'Z')
        k += 'a' - 'A';
    if (k == 'q' || k == KEY_CTRL('d')) {
        quit = 1;
        return;
    }
    if (over) {
        if (k == 'r')
            start();
        return;
    }
    if (k == 'p') {
        paused = !paused;
        if (paused)
            message("PAUSED", "P goes on");
        next_fall = clock() + fall_time();
        return;
    }
    if (paused)
        return;
    if (k == 'a' && fits(piece, rot, px - 1, py))
        px--;
    else if (k == 'd' && fits(piece, rot, px + 1, py))
        px++;
    else if (k == 'w')
        turn();
    else if (k == 's') {
        down();
        score += 1;
    } else if (k == ' ') {
        while (fits(piece, rot, px, py + 1)) {
            py++;
            score += 2;
        }
        lock_piece();
        next_fall = clock() + fall_time();
    }
}

int main(void)
{
    int k;
    gfx_fill(C_BG);
    gfx_text(70, 110, "STACKFALL", C_TEXT, C_BG);
    gfx_text(46, 130, "press a key to start", C_DIM, C_BG);
    k = wait_key();
    if (k == 'q' || k == KEY_CTRL('d'))
        return 0;
    srand((unsigned)clock());               /* how long that took: the only randomness */
    start();
    while (!quit) {
        if (gfx_lost()) {
            draw_frame();
            if (paused)
                message("PAUSED", "P goes on");
        }
        while ((k = key_pressed()) != 0 && !quit)
            key(k);
        if (quit)
            break;
        if (!over && !paused && (int)(clock() - next_fall) >= 0)
            down();
        if (!paused)
            draw_board();
        if (over) {
            message("GAME OVER", "R again, Q quits");
            while (!quit && over) {
                k = wait_key();
                key(k);
            }
            continue;
        }
        wait_ms(10);
    }
    gfx_clear();
    printf("Stackfall: score %d, rows %d, level %d, longest chain %d\n", score, rows, level, chain_best);
    return 0;
}
