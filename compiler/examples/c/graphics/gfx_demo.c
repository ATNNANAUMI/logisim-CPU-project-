/* gfx_demo.c - the RGB screen: shapes, text and colours with gfx.h
 *
 *   python compiler/src/cc run compiler/examples/c/graphics/gfx_demo.c --screen gfx_demo.png
 *   (or build it and open compiler/ROM/gfx_demo.rom in the simulator window:
 *    the "RGB screen" tab shows the picture)
 *
 * Needs the RGB Video wired as device 0x6C/0x6D (see gfx.h). Draws a colour
 * gradient, a title, a few shapes and a sine wave; prints "drawn" on the
 * text display when it is done (about 870 000 instructions).
 */
#include <gfx.h>
#include <math.h>
#include <stdio.h>

int main(void)
{
    int x, y;

    gfx_clear();
    /* background: a gradient from blue (top) to purple (bottom) */
    for (y = 0; y < GFX_HEIGHT; y++)
        gfx_hline(0, y, GFX_WIDTH, GFX_RGB(y, 0, 128 + y / 2));

    gfx_fill_rect(0, 0, GFX_WIDTH, 11, GFX_BLACK);
    gfx_text(4, 2, "tiny C on gates", GFX_YELLOW, GFX_NONE);

    gfx_fill_circle(60, 80, 32, GFX_ORANGE);
    gfx_circle(60, 80, 40, GFX_WHITE);
    gfx_fill_rect(128, 52, 80, 56, GFX_GREEN);
    gfx_rect(124, 48, 88, 64, GFX_WHITE);
    gfx_line(128, 52, 207, 107, GFX_BLACK);
    gfx_line(207, 52, 128, 107, GFX_BLACK);

    /* a sine wave across the bottom half, and its axis */
    gfx_hline(0, 184, GFX_WIDTH, GFX_GRAY);
    for (x = 0; x < GFX_WIDTH; x++) {
        y = 184 - (int)(40 * sin(x * 3.14159265f / 64));
        gfx_pixel(x, y, GFX_CYAN);
        gfx_pixel(x, y + 1, GFX_CYAN);
    }

    gfx_text(4, GFX_HEIGHT - 11, "256 x 256, RGB565", GFX_WHITE, GFX_BLACK);
    printf("drawn\n");
    return 0;
}
