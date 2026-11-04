/* paint.c - draw with the mouse on the RGB screen (the mouse device, cpu.h)
 *
 *   python compiler/src/cc run compiler/examples/c/graphics/paint.c
 *   (the window: click the "RGB screen" tab, then draw on it)
 *
 * Left button draws, right button erases, a click on a colour in the top
 * strip picks it, the middle button quits, and prints how many pixels it
 * drew ("painted N"). A headless run takes a script: --mouse
 * "x,y,buttons@step;..." (see main.py), e.g. in the self-check.
 */
#include <cpu.h>
#include <gfx.h>
#include <stdio.h>

#define STRIP 12                /* the colour strip is the top STRIP rows */
#define COLORS 8

static const int palette[COLORS] = {
    GFX_WHITE, GFX_RED, GFX_ORANGE, GFX_YELLOW, GFX_GREEN, GFX_CYAN, GFX_BLUE, GFX_GRAY
};

static void strip(int picked)
{
    int i, w = GFX_WIDTH / COLORS;
    for (i = 0; i < COLORS; i++) {
        gfx_fill_rect(i * w, 0, w, STRIP, palette[i]);
        if (i == picked)
            gfx_rect(i * w, 0, w, STRIP, GFX_BLACK);
    }
}

int main(void)
{
    int x, y, buttons, px = -1, py = -1, color = 0, painted = 0;

    gfx_clear();
    strip(color);
    for (;;) {
        buttons = mouse_state(&x, &y);
        if (buttons & 4)
            break;
        if (!(buttons & 8) || !(buttons & 3)) {     /* off the screen or no button */
            px = -1;
            continue;
        }
        if (y < STRIP) {
            if (buttons & 1) {
                color = x / (GFX_WIDTH / COLORS);
                strip(color);
            }
            px = -1;
            continue;
        }
        if (px < 0 || x != px || y != py) {         /* the first point, or moved: a line from the last */
            int c = (buttons & 2) ? GFX_BLACK : palette[color];
            if (px < 0)
                gfx_pixel(x, y, c);
            else
                gfx_line(px, py, x, y, c);
            painted++;
            px = x;
            py = y;
        }
    }
    printf("painted %d\n", painted);
    return 0;
}
