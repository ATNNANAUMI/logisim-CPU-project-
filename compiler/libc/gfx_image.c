/* gfx.h: gfx_image, compressed images made by compiler/src/img */
#include <gfx.h>

/* The format is described in compiler/src/img/codec.py. Two rows are kept:
 * the one above and the one being decoded. Pixel i of a row is at [i + 1];
 * [0] and [w + 1] hold palette colour 0, the colour of everything outside
 * the image, and are never written. Each row is decoded, then drawn, then
 * becomes the row above.
 *
 * The work is split so that each busy loop has its variables in registers
 * (the compiler gives at most 7 per function): decode_row (or unpack_row,
 * for the packed form) keeps the bit stream in local variables while it
 * decodes a row, and draw_row sends a row to the screen. */

/* the decoder's state between rows */
static const unsigned int *src;     /* the next word of the stream */
static unsigned int bits;           /* the bits of the last word not read yet, at the top */
static int count;                   /* how many */
static int run, kind, color;        /* a run can go on into the next row */
static const int *pal;
static int index_bits;              /* bits per palette index, 1-8 */
static int index_div;               /* 2^(31 - index_bits): (b >> 1) / index_div = the top index_bits */
static unsigned int index_mul;      /* 2^index_bits */

/* (in decode_row, where b and n are bits and count) the next k bits of
   the stream as a number, into v; k is 1-25. When b has fewer than k, they
   are followed by z = k - n bits from the next word. */
#define TAKE(v, k) \
    do { \
        if (n >= (k)) { \
            v = b >> (32 - (k)); \
            b <<= (k); \
            n -= (k); \
        } else { \
            z = (k) - n; \
            v = n ? b >> (32 - n) << z : 0; \
            b = *s++; \
            v |= b >> (32 - z); \
            b <<= z; \
            n = 32 - z; \
        } \
    } while (0)

/* TAKE(v, index_bits), quicker: index_div and index_mul are worked out once */
#define TAKE_INDEX(v) \
    do { \
        if (n >= index_bits) { \
            v = (int)(b >> 1) / index_div; \
            b *= index_mul; \
            n -= index_bits; \
        } else \
            TAKE(v, index_bits); \
    } while (0)

/* decodes pixels into to .. end - 1; to[up] is the pixel above to.
   Returns -1 if the stream is not an image. */
static int decode_row(int *to, int *end, int up)
{
    const unsigned int *s = src;
    unsigned int b = bits;
    int n = count, v, z;

    while (to < end) {
        if (run == 0) {
            if (n == 0) {
                b = *s++;
                n = 32;
            }
            n--;
            if ((int)b >= 0) {              /* 0: one pixel, its palette index */
                b += b;
                TAKE_INDEX(v);
                *to++ = color = pal[v];
                continue;
            }
            b += b;
            TAKE(kind, 2);                  /* 1: a run, its kind and length */
            for (z = 0;; z++) {             /* the length: z zeros, then z + 1 bits */
                if (n == 0) {
                    b = *s++;
                    n = 32;
                }
                if ((int)b < 0)
                    break;
                b += b;
                n--;
                if (z == 24)
                    return -1;
            }
            TAKE(run, z + 1);
        }
        v = end - to;                       /* the part of the run in this row */
        if (v > run)
            v = run;
        run -= v;
        if (kind == 0) {
            z = color;
            do
                *to++ = z;
            while (--v);
        } else {
            /* to[z]: above, above-left, above-right */
            z = up + (kind == 1 ? 0 : kind == 2 ? -1 : 1);
            do {
                *to = to[z];
                to++;
            } while (--v);
            color = to[-1];
        }
    }
    src = s;
    bits = b;
    count = n;
    return 0;
}

/* the packed form: a palette index for each pixel of to .. end - 1 */
static void unpack_row(int *to, int *end)
{
    const unsigned int *s = src;
    unsigned int b = bits;
    int n = count, v, z;

    do {
        TAKE_INDEX(v);
        *to++ = pal[v];
    } while (to < end);
    src = s;
    bits = b;
    count = n;
}

/* unpack_row for 1 bit a pixel (two colours): the top bit of b picks the colour */
static void unpack_bits_row(int *to, int *end)
{
    const unsigned int *s = src;
    unsigned int b = bits;
    int n = count, c0 = pal[0], c1 = pal[1];

    do {
        if (n == 0) {
            b = *s++;
            n = 32;
        }
        n--;
        *to++ = (int)b < 0 ? c1 : c0;
        b += b;
    } while (to < end);
    src = s;
    bits = b;
    count = n;
}

/* sends from .. end - 1 to the screen, the first at pixel (x and y in
   place); transparent pixels are left out */
static void draw_row(const int *from, const int *end, unsigned int pixel)
{
    int c;
    do {
        c = *from;
        if (c >= 0)
            __builtin_out(GFX_DEVICE, pixel | c);
        pixel += 1u << GFX_X_SHIFT;
    } while (++from < end);
}

int gfx_image(int x, int y, const unsigned int *img)
{
    int colors[256];
    int row_a[GFX_IMAGE_MAX_WIDTH + 2], row_b[GFX_IMAGE_MAX_WIDTH + 2];
    int *above = row_a, *row = row_b, *swap;
    int w = img[0], h = img[1], k = img[2] & 0xFFFF, clear = img[3];
    int packed = img[2] >> 16, i, first, last, end;

    if (w < 1 || w > GFX_IMAGE_MAX_WIDTH || h < 1 || k < 1 || k > 256 || packed > 1)
        return -1;
    for (i = 0; i < k; i++)
        colors[i] = i & 1 ? img[4 + i / 2] & 0xFFFF : img[4 + i / 2] >> 16;
    if (clear >= 0 && clear < k)
        colors[clear] = GFX_NONE;
    for (index_bits = 1; 1 << index_bits < k; index_bits++)
        ;
    index_div = 1 << (31 - index_bits);
    index_mul = 1u << index_bits;
    pal = colors;
    src = img + 4 + (k + 1) / 2;
    count = run = kind = 0;
    color = colors[0];
    for (i = 0; i < w + 2; i++)
        above[i] = row[i] = color;

    /* the columns on the screen: first .. last - 1 */
    first = x < 0 ? -x : 0;
    last = x + w > GFX_WIDTH ? GFX_WIDTH - x : w;
    for (end = y + h; y < end; y++) {
        if (packed && index_bits == 1)
            unpack_bits_row(row + 1, row + 1 + w);
        else if (packed)
            unpack_row(row + 1, row + 1 + w);
        else if (decode_row(row + 1, row + 1 + w, above - row))
            return -1;
        if (y >= 0 && y < GFX_HEIGHT && first < last)
            draw_row(row + 1 + first, row + 1 + last,
                     (unsigned int)(x + first) << GFX_X_SHIFT | y << GFX_Y_SHIFT);
        swap = above;
        above = row;
        row = swap;
    }
    return 0;
}
