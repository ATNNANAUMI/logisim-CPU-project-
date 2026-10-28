#include <cpu.h>
#include <gfx.h>
#include <stdlib.h>
#include <stdio.h>
#include <time.h>

/*
 * Snake for Tiny C / the logic-gate CPU.
 *
 * python compiler/src/cc build compiler/examples/c/snake.c, then open
 *     compiler/ROM/snake.rom in the simulator window (the "RGB screen" tab)
 *
 * Grid: 16 x 14 cells, each 8 x 8 pixels. The top 16 pixels are reserved for the score panel.
 * Controls: W/A/S/D. Press R to restart after game over, Q to quit (back to
 * the OS's shell when it was run from there: os/shell.c).
 */

#define GRID_W 16
#define GRID_H 14
#define CELL 8
#define BOARD_Y 16
#define MAX_SNAKE (GRID_W * GRID_H)

#define COLOR_BG      GFX_RGB(12, 18, 28)
#define COLOR_SNAKE   GFX_RGB(70, 220, 120)
#define COLOR_HEAD    GFX_RGB(150, 255, 170)
#define COLOR_FOOD    GFX_RGB(255, 85, 95)
#define COLOR_TEXT    GFX_RGB(235, 240, 250)
#define COLOR_PANEL   GFX_RGB(25, 35, 48)

static int snake_x[MAX_SNAKE];
static int snake_y[MAX_SNAKE];
static int snake_len;
static int dir_x;
static int dir_y;
static int food_x;
static int food_y;
static int score;
static int game_over;
static int quit;

static void draw_cell(int x, int y, unsigned color)
{
    gfx_fill_rect(x * CELL, BOARD_Y + y * CELL, CELL - 1, CELL - 1, color);
}

static int snake_has_cell(int x, int y)
{
    int i;
    for (i = 0; i < snake_len; i++) {
        if (snake_x[i] == x && snake_y[i] == y)
            return 1;
    }
    return 0;
}

static void spawn_food(void)
{
    int tries;
    int x;
    int y;

    /* There is nowhere to place food if the snake fills the board. */
    if (snake_len >= MAX_SNAKE)
        return;

    /* Random placement is fast in the normal case. */
    for (tries = 0; tries < 1000; tries++) {
        food_x = rand() % GRID_W;
        food_y = rand() % GRID_H;
        if (!snake_has_cell(food_x, food_y))
            return;
    }

    /*
     * Random retries can all hit the snake, especially when the board is
     * nearly full. Fall back to a guaranteed search instead of leaving the
     * food inside the snake.
     */
    for (y = 0; y < GRID_H; y++) {
        for (x = 0; x < GRID_W; x++) {
            if (!snake_has_cell(x, y)) {
                food_x = x;
                food_y = y;
                return;
            }
        }
    }
}

static void draw_game(void)
{
    int i;

    gfx_fill(COLOR_BG);

    /* The board starts below the score panel, so UI and gameplay never overlap. */
    for (i = 0; i < GRID_W; i++)
        gfx_vline(i * CELL, BOARD_Y, 128 - BOARD_Y, GFX_RGB(22, 30, 42));
    for (i = 0; i < GRID_H; i++)
        gfx_hline(0, BOARD_Y + i * CELL, 128, GFX_RGB(22, 30, 42));

    /* Food. */
    gfx_fill_rect(food_x * CELL + 1, BOARD_Y + food_y * CELL + 1,
                  CELL - 2, CELL - 2, COLOR_FOOD);

    /* Body, then head. */
    for (i = snake_len - 1; i >= 1; i--)
        draw_cell(snake_x[i], snake_y[i], COLOR_SNAKE);

    draw_cell(snake_x[0], snake_y[0], COLOR_HEAD);

    /* Score panel is separate from the board. */
    gfx_fill_rect(0, 0, 128, BOARD_Y, COLOR_PANEL);
    gfx_text(3, 1, "SCORE", COLOR_TEXT, GFX_NONE);
    gfx_text(48, 1, "              ", COLOR_TEXT, GFX_NONE);
    {
        char score_text[12];
        /* Score is small enough for a simple decimal conversion. */
        int n = score;
        int p = 0;
        char reversed[12];

        if (n == 0) {
            score_text[0] = '0';
            score_text[1] = '\0';
        } else {
            while (n > 0 && p < 10) {
                reversed[p++] = (char)('0' + n % 10);
                n /= 10;
            }
            for (i = 0; i < p; i++)
                score_text[i] = reversed[p - 1 - i];
            score_text[p] = '\0';
        }
        gfx_text(48, 1, score_text, COLOR_TEXT, GFX_NONE);
    }
}

static void reset_game(void)
{
    snake_len = 3;
    snake_x[0] = 8;
    snake_y[0] = 8;
    snake_x[1] = 7;
    snake_y[1] = 8;
    snake_x[2] = 6;
    snake_y[2] = 8;

    dir_x = 1;
    dir_y = 0;
    score = 0;
    game_over = 0;

    spawn_food();
    draw_game();
}

static void read_input(void)
{
    int key = key_pressed();

    if (key >= 'A' && key <= 'Z')
        key += 'a' - 'A';

    if (key == 'q')
        quit = 1;
    else if (key == 'w' && dir_y != 1) {
        dir_x = 0;
        dir_y = -1;
    } else if (key == 's' && dir_y != -1) {
        dir_x = 0;
        dir_y = 1;
    } else if (key == 'a' && dir_x != 1) {
        dir_x = -1;
        dir_y = 0;
    } else if (key == 'd' && dir_x != -1) {
        dir_x = 1;
        dir_y = 0;
    }
}

static void update_game(void)
{
    int next_x = snake_x[0] + dir_x;
    int next_y = snake_y[0] + dir_y;
    int ate;
    int i;
    int body_limit;

    /* Wall collision. */
    if (next_x < 0 || next_x >= GRID_W ||
        next_y < 0 || next_y >= GRID_H) {
        game_over = 1;
        return;
    }

    ate = (next_x == food_x && next_y == food_y);

    /*
     * If not eating, the tail moves away this turn, so entering its
     * current cell is legal. Otherwise every body segment is occupied.
     */
    body_limit = snake_len - (ate ? 0 : 1);
    for (i = 0; i < body_limit; i++) {
        if (snake_x[i] == next_x && snake_y[i] == next_y) {
            game_over = 1;
            return;
        }
    }

    if (ate && snake_len < MAX_SNAKE)
        snake_len++;

    for (i = snake_len - 1; i > 0; i--) {
        snake_x[i] = snake_x[i - 1];
        snake_y[i] = snake_y[i - 1];
    }

    snake_x[0] = next_x;
    snake_y[0] = next_y;

    if (ate) {
        score += 1;
        if (snake_len == MAX_SNAKE) {
            game_over = 1;
            return;
        }
        spawn_food();
    }
}

static void draw_game_over(void)
{
    gfx_fill(COLOR_BG);
    gfx_fill_rect(8, 34, 112, 58, COLOR_PANEL);
    gfx_text(29, 43, "GAME OVER", COLOR_FOOD, GFX_NONE);
    gfx_text(20, 57, "FINAL SCORE", COLOR_TEXT, GFX_NONE);

    {
        char text_score[12];
        char reversed[12];
        int n = score;
        int p = 0;
        int i;

        if (n == 0) {
            text_score[0] = '0';
            text_score[1] = '\0';
        } else {
            while (n > 0 && p < 10) {
                reversed[p++] = (char)('0' + n % 10);
                n /= 10;
            }
            for (i = 0; i < p; i++)
                text_score[i] = reversed[p - 1 - i];
            text_score[p] = '\0';
        }
        gfx_text(88, 57, text_score, COLOR_HEAD, GFX_NONE);
    }

    gfx_text(18, 76, "PRESS R TO RESTART", COLOR_TEXT, GFX_NONE);
    gfx_text(37, 84, "Q TO QUIT", COLOR_TEXT, GFX_NONE);
}

int main(void)
{
    srand((unsigned)clock());
    reset_game();

    while (!quit) {
        if (game_over) {
            int key;

            draw_game_over();
            do {
                key = wait_key();
                if (key >= 'A' && key <= 'Z')
                    key += 'a' - 'A';
            } while (key != 'r' && key != 'q');

            if (key == 'q')
                break;
            reset_game();
        }

        read_input();
        update_game();

        if (!game_over)
            draw_game();

        wait_ms(140);
    }

    return 0;
}
