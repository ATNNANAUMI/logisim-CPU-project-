/* gfx.h - drawing on the RGB Video screen (not standard C)
 *
 * The screen is Logisim's RGB Video component, 128 x 128 pixels of RGB565
 * colour. Each word sent to device 0x6C sets one pixel: x in bits 31-24,
 * y in bits 23-16, the colour in bits 15-0. Any word sent to 0x6D clears the
 * screen to black. The screen can't be read back. Everything is clipped:
 * drawing off the screen does nothing.
 *
 *   GFX_RGB(r, g, b)               a colour from 0-255 components
 *   gfx_clear()                    all black (fast: one reset pulse)
 *   gfx_fill(color)                the whole screen in one colour
 *   gfx_pixel(x, y, color)
 *   gfx_hline(x, y, w, color)      w pixels to the right of (x, y)
 *   gfx_vline(x, y, h, color)      h pixels down from (x, y)
 *   gfx_line(x0, y0, x1, y1, color)
 *   gfx_rect(x, y, w, h, color)    outline
 *   gfx_fill_rect(x, y, w, h, color)
 *   gfx_circle(cx, cy, r, color)   outline
 *   gfx_fill_circle(cx, cy, r, color)
 *   gfx_char(x, y, c, fg, bg)      a 5x7 character in a 6x8 cell; bg GFX_NONE
 *                                  leaves the background; returns x + 6
 *   gfx_text(x, y, s, fg, bg)      a string ('\n' starts a new line under x);
 *                                  returns the x after the last character
 *   gfx_bitmap(x, y, w, h, pixels) w*h colours row by row; GFX_NONE ones
 *                                  are left out (transparent)
 *
 * If the screen is wired differently, change the GFX_ numbers below (and
 * VIDEO_* in cpu_sim/src/config.py for the simulator).
 */
#ifndef _GFX_H
#define _GFX_H

#define GFX_DEVICE 0x6C
#define GFX_CLEAR_DEVICE 0x6D
#define GFX_WIDTH 128
#define GFX_HEIGHT 128
#define GFX_X_SHIFT 24
#define GFX_Y_SHIFT 16

#define GFX_CHAR_WIDTH 6        /* the cell a character takes */
#define GFX_CHAR_HEIGHT 8

#define GFX_RGB(r, g, b) ((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | (((b) & 0xFF) >> 3))
#define GFX_NONE (-1)           /* "no colour": transparent */

#define GFX_BLACK    0x0000
#define GFX_WHITE    0xFFFF
#define GFX_GRAY     0x8410
#define GFX_DARKGRAY 0x4208
#define GFX_RED      0xF800
#define GFX_GREEN    0x07E0
#define GFX_BLUE     0x001F
#define GFX_YELLOW   0xFFE0
#define GFX_CYAN     0x07FF
#define GFX_MAGENTA  0xF81F
#define GFX_ORANGE   0xFC00
#define GFX_BROWN    0x8200
#define GFX_PINK     0xFB56
#define GFX_PURPLE   0x8010
#define GFX_NAVY     0x0010
#define GFX_DARKGREEN 0x0400

void gfx_clear(void);
void gfx_fill(int color);
void gfx_pixel(int x, int y, int color);
void gfx_hline(int x, int y, int w, int color);
void gfx_vline(int x, int y, int h, int color);
void gfx_line(int x0, int y0, int x1, int y1, int color);
void gfx_rect(int x, int y, int w, int h, int color);
void gfx_fill_rect(int x, int y, int w, int h, int color);
void gfx_circle(int cx, int cy, int r, int color);
void gfx_fill_circle(int cx, int cy, int r, int color);
int gfx_char(int x, int y, int c, int fg, int bg);
int gfx_text(int x, int y, const char *s, int fg, int bg);
void gfx_bitmap(int x, int y, int w, int h, const int *pixels);

#endif
