/* an ASCII Mandelbrot set, in float arithmetic */
#include <stdio.h>

int main(void)
{
    const char *shades = " .:-=+*#%@";
    int row, col;
    for (row = 0; row < 12; row++) {
        for (col = 0; col < 32; col++) {
            float cr = -2.0f + col * 0.08f;
            float ci = -1.1f + row * 0.2f;
            float zr = 0.0f, zi = 0.0f;
            int i = 0;
            while (i < 30 && zr * zr + zi * zi < 4.0f) {
                float t = zr * zr - zi * zi + cr;
                zi = 2.0f * zr * zi + ci;
                zr = t;
                i++;
            }
            putchar(shades[i % 10]);
        }
        putchar('\n');
    }
    return 0;
}
