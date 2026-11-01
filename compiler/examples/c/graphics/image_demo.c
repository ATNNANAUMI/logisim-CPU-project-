/* image_demo.c - compressed pictures on the RGB screen with gfx_image (gfx.h)
 *
 *   python compiler/src/cc run compiler/examples/c/graphics/image_demo.c --screen image_demo.png
 *   (or build it and open compiler/ROM/image_demo.rom in the simulator
 *    window: the "RGB screen" tab shows the picture)
 *
 * The pictures are images/mandelbrot.png (256 x 256, 70 colours) and
 * images/smiley.png (16 x 16, transparent corners), turned into the .h
 * files next to them by
 *   python compiler/src/img compiler/examples/c/graphics/images/mandelbrot.png
 *   python compiler/src/img compiler/examples/c/graphics/images/smiley.png
 * They take 1707 + 18 words of ROM instead of 65536 + 256 at one word per
 * pixel (the whole program is 3818 words; gfx_image itself is about 1500).
 * Draws the Mandelbrot set over the whole screen, then smileys on top (two
 * of them half off the edges), and prints "drawn" on the text display
 * (about 2 200 000 instructions, half a second in the simulator).
 */
#include <gfx.h>
#include <stdio.h>             /* puts: printf would add 4300 words */
#include "images/mandelbrot.h"
#include "images/smiley.h"

int main(void)
{
    int i, w = GFX_IMAGE_WIDTH(smiley);

    if (gfx_image(0, 0, mandelbrot) != 0) {
        puts("not an image");
        return 1;
    }
    for (i = 0; i < 4; i++)
        gfx_image(10 + i * (w + 14), GFX_HEIGHT - w - 8, smiley);
    gfx_image(-w / 2, 6, smiley);                   /* clipped on the left */
    gfx_image(GFX_WIDTH - w / 2, 6, smiley);        /* and on the right */
    puts("drawn");
    return 0;
}
