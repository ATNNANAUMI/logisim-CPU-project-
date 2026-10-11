/* gfx.h: pixels, lines, rectangles, circles and bitmaps on the RGB screen */
#include <gfx.h>

#define PIXEL(x, y, color) \
    __builtin_out(GFX_DEVICE, ((x) << GFX_X_SHIFT) | ((y) << GFX_Y_SHIFT) | ((color) & 0xFFFF))

void gfx_clear(void)
{
    __builtin_out(GFX_CLEAR_DEVICE, 0);
}

void gfx_fill(int color)
{
    gfx_clear();
    if ((color & 0xFFFF) != 0)
        gfx_fill_rect(0, 0, GFX_WIDTH, GFX_HEIGHT, color);
}

void gfx_pixel(int x, int y, int color)
{
    if (x >= 0 && x < GFX_WIDTH && y >= 0 && y < GFX_HEIGHT)
        PIXEL(x, y, color);
}

void gfx_hline(int x, int y, int w, int color)
{
    unsigned int word, last;
    if (y < 0 || y >= GFX_HEIGHT)
        return;
    if (x < 0) {
        w += x;
        x = 0;
    }
    if (x + w > GFX_WIDTH)
        w = GFX_WIDTH - x;
    if (w <= 0)
        return;
    /* one word per pixel: step x by adding 1 << GFX_X_SHIFT */
    word = ((unsigned int)x << GFX_X_SHIFT) | (y << GFX_Y_SHIFT) | (color & 0xFFFF);
    last = word + ((unsigned int)(w - 1) << GFX_X_SHIFT);
    for (;;) {
        __builtin_out(GFX_DEVICE, word);
        if (word == last)
            break;
        word += 1u << GFX_X_SHIFT;
    }
}

void gfx_vline(int x, int y, int h, int color)
{
    int word, last;
    if (x < 0 || x >= GFX_WIDTH)
        return;
    if (y < 0) {
        h += y;
        y = 0;
    }
    if (y + h > GFX_HEIGHT)
        h = GFX_HEIGHT - y;
    if (h <= 0)
        return;
    word = (y << GFX_Y_SHIFT) | (color & 0xFFFF);
    last = word + ((h - 1) << GFX_Y_SHIFT);
    for (;;) {
        __builtin_out(GFX_DEVICE, ((unsigned int)x << GFX_X_SHIFT) | word);
        if (word == last)
            break;
        word += 1 << GFX_Y_SHIFT;
    }
}

void gfx_line(int x0, int y0, int x1, int y1, int color)
{
    /* Bresenham, all octants */
    int dx = x1 > x0 ? x1 - x0 : x0 - x1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0;
    int sx = x0 < x1 ? 1 : -1;
    int sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    for (;;) {
        int e2;
        gfx_pixel(x0, y0, color);
        if (x0 == x1 && y0 == y1)
            break;
        e2 = 2 * err;
        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}

void gfx_rect(int x, int y, int w, int h, int color)
{
    if (w <= 0 || h <= 0)
        return;
    gfx_hline(x, y, w, color);
    gfx_hline(x, y + h - 1, w, color);
    gfx_vline(x, y + 1, h - 2, color);
    gfx_vline(x + w - 1, y + 1, h - 2, color);
}

void gfx_fill_rect(int x, int y, int w, int h, int color)
{
    int end;
    if (y < 0) {
        h += y;
        y = 0;
    }
    end = y + h;
    if (end > GFX_HEIGHT)
        end = GFX_HEIGHT;
    for (; y < end; y++)
        gfx_hline(x, y, w, color);
}

void gfx_circle(int cx, int cy, int r, int color)
{
    /* midpoint circle: one octant, mirrored eight ways */
    int x = r, y = 0, err = 1 - r;
    if (r < 0)
        return;
    while (x >= y) {
        gfx_pixel(cx + x, cy + y, color);
        gfx_pixel(cx - x, cy + y, color);
        gfx_pixel(cx + x, cy - y, color);
        gfx_pixel(cx - x, cy - y, color);
        gfx_pixel(cx + y, cy + x, color);
        gfx_pixel(cx - y, cy + x, color);
        gfx_pixel(cx + y, cy - x, color);
        gfx_pixel(cx - y, cy - x, color);
        y++;
        if (err < 0)
            err += 2 * y + 1;
        else {
            x--;
            err += 2 * (y - x) + 1;
        }
    }
}

void gfx_fill_circle(int cx, int cy, int r, int color)
{
    int x = r, y = 0, err = 1 - r;
    if (r < 0)
        return;
    while (x >= y) {
        /* the wide spans (rows cy +- y) every step, the narrow ones
           (rows cy +- x) only when x is about to change, so no row is drawn twice */
        gfx_hline(cx - x, cy + y, 2 * x + 1, color);
        if (y != 0)
            gfx_hline(cx - x, cy - y, 2 * x + 1, color);
        if (err >= 0 && x != y) {
            gfx_hline(cx - y, cy + x, 2 * y + 1, color);
            gfx_hline(cx - y, cy - x, 2 * y + 1, color);
        }
        y++;
        if (err < 0)
            err += 2 * y + 1;
        else {
            x--;
            err += 2 * (y - x) + 1;
        }
    }
}

void gfx_bitmap(int x, int y, int w, int h, const int *pixels)
{
    int i, j;
    for (j = 0; j < h; j++)
        for (i = 0; i < w; i++) {
            int c = *pixels++;
            if (c != GFX_NONE)
                gfx_pixel(x + i, y + j, c);
        }
}
