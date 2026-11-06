/* screen_test.c - the RGB screen on the real circuit (look at it)
 *
 * Build and run (from the project root):
 *   python compiler/src/cc build logisim/tests/screen_test.c
 *   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/screen_test.rom
 * (headless there is nothing to see: load the .rom in Logisim and look at the
 * RGB Video; the text display says "screen test done" at the end)
 * or in the simulator:  python cpu_sim/src/main.py compiler/ROM/screen_test.rom
 *
 * The screen is 256 x 256 with x in word bits 31-24, y in 23-16 and the colour
 * RGB565 in 15-0. What it should show (the circuit has no clear yet, so run it
 * on a black screen):
 *   corners   four pixels: top left red, top right green, bottom left blue,
 *             bottom right white (the last row and column are on the screen)
 *   frame     a yellow rectangle 2 pixels in from the edge
 *   diagonal  a white line from (8, 8) to (247, 247)
 *   letter F  a white F at (20, 20) made of three bars: the bar on top and
 *             the shorter one in the middle both point right, the stem is on
 *             the left. Turned or mirrored: x and y are swapped or flipped.
 *   bars      eight colour bars, left to right: red, orange, yellow, green,
 *             cyan, blue, magenta, white, y = 200 to 203
 *   ramp      a red gradient from black on the left to bright red on the right
 *             (y = 215 and 216), then a green one (221, 222) and a blue one
 *             (227, 228)
 * About 140 000 instructions, four or five minutes on the circuit.
 */
#include <stdio.h>
#include <gfx.h>

int main(void)
{
    int x, i;
    static const int bar[8] = {GFX_RED, GFX_ORANGE, GFX_YELLOW, GFX_GREEN, GFX_CYAN, GFX_BLUE,
                               GFX_MAGENTA, GFX_WHITE};

    gfx_pixel(0, 0, GFX_RED);
    gfx_pixel(255, 0, GFX_GREEN);
    gfx_pixel(0, 255, GFX_BLUE);
    gfx_pixel(255, 255, GFX_WHITE);

    gfx_rect(2, 2, 252, 252, GFX_YELLOW);
    gfx_line(8, 8, 247, 247, GFX_WHITE);

    gfx_fill_rect(20, 20, 6, 40, GFX_WHITE);        /* the stem of the F */
    gfx_fill_rect(26, 20, 30, 6, GFX_WHITE);        /* the top bar */
    gfx_fill_rect(26, 36, 20, 6, GFX_WHITE);        /* the middle bar */

    for (i = 0; i < 8; i++)
        gfx_fill_rect(16 + i * 28, 200, 28, 4, bar[i]);

    for (x = 0; x < 256; x += 2) {
        gfx_fill_rect(x, 215, 2, 2, GFX_RGB(x, 0, 0));
        gfx_fill_rect(x, 221, 2, 2, GFX_RGB(0, x, 0));
        gfx_fill_rect(x, 227, 2, 2, GFX_RGB(0, 0, x));
    }

    puts("screen test done");
    return 0;
}
