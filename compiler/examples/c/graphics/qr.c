/* qr.c - QR codes on the RGB screen
 *
 * python compiler/src/cc build compiler/examples/c/graphics/qr.c, then open
 *     compiler/ROM/qr.rom in the simulator window (the "RGB screen" tab)
 * python compiler/src/cc run compiler/examples/c/graphics/qr.c --keys $'\x04' --screen qr.png
 * python compiler/src/cc run compiler/examples/c/graphics/qr.c --keys $'hello\n' --screen qr.png
 *     (Ctrl-D, or the end of --keys, stops it; otherwise it waits for keys)
 *
 * At the start it draws a QR code of this project's GitHub page, as big as
 * the screen allows, black on white with the 4-module quiet zone around it.
 * Type any text on the keyboard (it shows on a bar at the bottom) and press
 * Enter: that text becomes the new QR code. An empty line goes back to the
 * GitHub link. Check the result with a phone, or with zbarimg qr.png.
 *
 * The encoder follows the QR standard (ISO/IEC 18004) from scratch: byte
 * mode, versions 1-10 (21x21 to 57x57 modules; the smallest that fits is
 * chosen), error correction level L, M, Q or H, Reed-Solomon codes over
 * GF(256), the data spread over the blocks and interleaved, and all eight
 * masks tried, keeping the one with the lowest penalty (long runs, 2x2
 * blocks, finder-like patterns, the dark/light balance).
 *
 *   -D LEVEL=n     error correction: 0 L (7%), 1 M (15%, the default),
 *                  2 Q (25%), 3 H (30%)
 *   -D TEXT="..."  the first text, instead of the GitHub link
 *   -D MASK=n      always mask n (0-7) instead of the best one
 *   -D DARK=c      the colour of the dark modules (default GFX_BLACK); a
 *                  dark one like GFX_RGB(0x82, 0x0A, 0xD1) still scans
 *
 * The GitHub link (50 bytes) is version 4 at level M: 33x33 modules, 3
 * pixels each. Encoding and drawing it takes about 2.6 million
 * instructions, half of it scoring the masks: about 0.9 s in the simulator
 * under plain python. Text longer than the version 10 capacity (271
 * bytes at level L, 213 at M, 151 at Q, 119 at H) is refused; typed lines
 * stop at 120.
 * Not for the circuit (160 instructions a second, and it still has the
 * old memory map).
 *
 * Expected output (the time changes):
 *   QR: https://github.com/ATNNANAUMI/logisim-CPU-project-
 *     version 4 (33x33), level M, mask 7, 50 bytes, 3 pixels a module  (877 ms)
 *
 * Checked against zbarimg (every version and level, at its full capacity,
 * decodes back to the text) and qrencode (with the same mask forced, the
 * modules are identical; the mask each picks can differ, as encoders score
 * the masks a little differently).
 */
#include <cpu.h>
#include <gfx.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#ifndef LEVEL
#define LEVEL 1
#endif
#ifndef TEXT
#define TEXT "https://github.com/ATNNANAUMI/logisim-CPU-project-"
#endif
#ifndef DARK
#define DARK GFX_BLACK
#endif
#ifndef MASK
#define MASK -1                         /* -1: the one with the lowest penalty */
#endif

#define LIGHT GFX_WHITE
#define BAR GFX_RGB(30, 20, 40)
#define BAR_TEXT GFX_WHITE
#define ERROR GFX_RGB(255, 90, 90)

#define MAX_VERSION 10
#define MAX_SIZE (17 + 4 * MAX_VERSION)
#define MAX_CODEWORDS 346               /* version 10: 2768 modules / 8 */
#define MAX_ECC 30
#define QUIET 4                         /* light modules around the code */
#define MAX_LINE 120
#define BAR_Y (GFX_HEIGHT - GFX_CHAR_HEIGHT)

/* per level (L M Q H) and version (index 1-10): Reed-Solomon codewords per
   block, and the number of blocks */
static const int ecc_per_block[4][MAX_VERSION + 1] = {
    {0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18},
    {0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26},
    {0, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24},
    {0, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28},
};
static const int num_blocks[4][MAX_VERSION + 1] = {
    {0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4},
    {0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5},
    {0, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8},
    {0, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8},
};
static const int level_bits[4] = {1, 0, 3, 2};  /* in the format bits */
static const char level_names[] = "LMQH";

static int size;
static int modules[MAX_SIZE][MAX_SIZE];         /* 1 dark, [y][x] */
static int is_function[MAX_SIZE][MAX_SIZE];     /* finders, timing, format... */
static int codewords[MAX_CODEWORDS];
static int count;                               /* bits written to codewords */

static char line[MAX_LINE + 1];
static int line_len;

/* ---- GF(256) and Reed-Solomon ---- */

static int gf_exp[512], gf_log[256];  /* 2^i, and i for 2^i */

/* the tables for GF(256) with the QR polynomial x^8 + x^4 + x^3 + x^2 + 1:
   2 generates every non-zero element */
static void gf_init(void)
{
    int i, v = 1;
    for (i = 0; i < 255; i++) {
        gf_exp[i] = gf_exp[i + 255] = v;
        gf_log[v] = i;
        v <<= 1;
        if (v & 0x100)
            v ^= 0x11D;
    }
}

static int gf_mul(int x, int y)
{
    return x && y ? gf_exp[gf_log[x] + gf_log[y]] : 0;
}

/* the generator polynomial (x - 1)(x - 2)(x - 4)...(x - 2^(n-1)), its
   leading 1 left out, highest power first */
static void rs_divisor(int n, int *result)
{
    int i, j, root = 1;
    for (i = 0; i < n - 1; i++)
        result[i] = 0;
    result[n - 1] = 1;
    for (i = 0; i < n; i++) {
        for (j = 0; j < n; j++) {
            result[j] = gf_mul(result[j], root);
            if (j + 1 < n)
                result[j] ^= result[j + 1];
        }
        root = gf_mul(root, 2);
    }
}

/* the n error correction codewords of data[0..len-1]: the remainder of
   data * x^n divided by the generator */
static void rs_remainder(const int *data, int len, const int *divisor, int n, int *result)
{
    int i, j, factor;
    for (i = 0; i < n; i++)
        result[i] = 0;
    for (i = 0; i < len; i++) {
        factor = data[i] ^ result[0];
        for (j = 0; j < n - 1; j++)
            result[j] = result[j + 1];
        result[n - 1] = 0;
        for (j = 0; j < n; j++)
            result[j] ^= gf_mul(divisor[j], factor);
    }
}

/* ---- sizes ---- */

/* modules left for data and error correction once the function patterns
   are placed */
static int raw_modules(int version)
{
    int result = (16 * version + 128) * version + 64, align;
    if (version >= 2) {
        align = version / 7 + 2;
        result -= (25 * align - 10) * align - 55;
        if (version >= 7)
            result -= 36;
    }
    return result;
}

static int data_codewords(int version, int level)
{
    return raw_modules(version) / 8
           - ecc_per_block[level][version] * num_blocks[level][version];
}

/* the bits a text of len bytes takes: mode, character count, the bytes */
static int needed_bits(int version, int len)
{
    return 4 + (version < 10 ? 8 : 16) + 8 * len;
}

/* the centres of the alignment patterns along each axis */
static int alignment_positions(int version, int *result)
{
    int n, step, i, pos;
    if (version == 1)
        return 0;
    n = version / 7 + 2;
    step = (version * 8 + n * 3 + 5) / (n * 4 - 4) * 2;
    result[0] = 6;
    for (i = n - 1, pos = size - 7; i >= 1; i--, pos -= step)
        result[i] = pos;
    return n;
}

/* ---- the matrix ---- */

static void set_function(int x, int y, int dark)
{
    modules[y][x] = dark;
    is_function[y][x] = 1;
}

static void draw_finder(int cx, int cy)
{
    int dx, dy, d, x, y;
    for (dy = -4; dy <= 4; dy++)
        for (dx = -4; dx <= 4; dx++) {
            x = cx + dx;
            y = cy + dy;
            if (x < 0 || x >= size || y < 0 || y >= size)
                continue;
            d = dx < 0 ? -dx : dx;
            if (dy > d || -dy > d)
                d = dy < 0 ? -dy : dy;
            set_function(x, y, d != 2 && d != 4);   /* the separator is d 4 */
        }
}

static void draw_alignment(int cx, int cy)
{
    int dx, dy, d;
    for (dy = -2; dy <= 2; dy++)
        for (dx = -2; dx <= 2; dx++) {
            d = dx < 0 ? -dx : dx;
            if (dy > d || -dy > d)
                d = dy < 0 ? -dy : dy;
            set_function(cx + dx, cy + dy, d != 1);
        }
}

/* the 15 format bits (level and mask, BCH-protected), twice */
static void draw_format(int level, int mask)
{
    int data = level_bits[level] << 3 | mask, rem = data, bits, i;
    for (i = 0; i < 10; i++)
        rem = (rem << 1) ^ ((rem >> 9) * 0x537);
    bits = (data << 10 | rem) ^ 0x5412;
    /* around the top left finder */
    for (i = 0; i <= 5; i++)
        set_function(8, i, (bits >> i) & 1);
    set_function(8, 7, (bits >> 6) & 1);
    set_function(8, 8, (bits >> 7) & 1);
    set_function(7, 8, (bits >> 8) & 1);
    for (i = 9; i < 15; i++)
        set_function(14 - i, 8, (bits >> i) & 1);
    /* split between the other two */
    for (i = 0; i < 8; i++)
        set_function(size - 1 - i, 8, (bits >> i) & 1);
    for (i = 8; i < 15; i++)
        set_function(8, size - 15 + i, (bits >> i) & 1);
    set_function(8, size - 8, 1);       /* always dark */
}

/* versions 7 and up: the version number, 18 bits, twice */
static void draw_version(int version)
{
    int rem = version, bits, i, a, b;
    if (version < 7)
        return;
    for (i = 0; i < 12; i++)
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25);
    bits = version << 12 | rem;
    for (i = 0; i < 18; i++) {
        a = size - 11 + i % 3;
        b = i / 3;
        set_function(a, b, (bits >> i) & 1);
        set_function(b, a, (bits >> i) & 1);
    }
}

static void draw_function_patterns(int version, int level)
{
    int pos[7], n, i, j, x, y;
    for (y = 0; y < size; y++)
        for (x = 0; x < size; x++) {
            modules[y][x] = 0;
            is_function[y][x] = 0;
        }
    for (i = 0; i < size; i++) {        /* timing patterns */
        set_function(6, i, i % 2 == 0);
        set_function(i, 6, i % 2 == 0);
    }
    draw_finder(3, 3);
    draw_finder(size - 4, 3);
    draw_finder(3, size - 4);
    n = alignment_positions(version, pos);
    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++)
            if (!((i == 0 && j == 0) || (i == 0 && j == n - 1) || (i == n - 1 && j == 0)))
                draw_alignment(pos[i], pos[j]);
    draw_format(level, 0);              /* reserves the cells; redrawn later */
    draw_version(version);
}

/* the codewords into the free cells: two columns at a time from the right,
   going up then down, skipping the vertical timing column */
static void draw_codewords(int total)
{
    int i = 0, right, vert, j, x, y, upward;
    for (right = size - 1; right >= 1; right -= 2) {
        if (right == 6)
            right = 5;
        upward = ((right + 1) & 2) == 0;
        for (vert = 0; vert < size; vert++)
            for (j = 0; j < 2; j++) {
                x = right - j;
                y = upward ? size - 1 - vert : vert;
                if (!is_function[y][x] && i < total * 8) {
                    modules[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1;
                    i++;
                }
            }
    }
}

/* flips the data cells where the mask's condition holds; doing it twice
   undoes it */
static void apply_mask(int mask)
{
    int x, y, flip;
    for (y = 0; y < size; y++)
        for (x = 0; x < size; x++) {
            if (is_function[y][x])
                continue;
            switch (mask) {
            case 0: flip = (x + y) % 2 == 0; break;
            case 1: flip = y % 2 == 0; break;
            case 2: flip = x % 3 == 0; break;
            case 3: flip = (x + y) % 3 == 0; break;
            case 4: flip = (x / 3 + y / 2) % 2 == 0; break;
            case 5: flip = x * y % 2 + x * y % 3 == 0; break;
            case 6: flip = (x * y % 2 + x * y % 3) % 2 == 0; break;
            default: flip = ((x + y) % 2 + x * y % 3) % 2 == 0; break;
            }
            modules[y][x] ^= flip;
        }
}

/* rule 1 (five or more alike in a row: 3, plus 1 for each more) and rule 3
   (dark-light-dark-dark-dark-light-dark with four light modules on either
   side, like a finder: 40) for one row or column. lane[] has the modules
   from index 4, with the light quiet zone around them */
static int line_penalty(const int *lane)
{
    int score = 0, run = 1, i;
    const int *p;
    for (i = 5; i <= size + 4; i++) {
        if (i < size + 4 && lane[i] == lane[i - 1]) {
            run++;
            continue;
        }
        if (run >= 5)
            score += run - 2;
        run = 1;
    }
    for (i = 4; i + 6 < size + 4; i++) {
        p = lane + i;
        if (p[0] && !p[1] && p[2] && p[3] && p[4] && !p[5] && p[6]
            && ((!p[-4] && !p[-3] && !p[-2] && !p[-1]) || (!p[7] && !p[8] && !p[9] && !p[10])))
            score += 40;
    }
    return score;
}

/* the standard's four penalty rules; the lowest total wins */
static int penalty(void)
{
    static int lane[MAX_SIZE + 2 * QUIET];      /* stays 0 outside 4..size+3 */
    int score = 0, x, y, dark = 0, total, k;
    for (y = 0; y < size; y++) {
        for (x = 0; x < size; x++)
            lane[x + QUIET] = modules[y][x];
        score += line_penalty(lane);
    }
    for (x = 0; x < size; x++) {
        for (y = 0; y < size; y++)
            lane[y + QUIET] = modules[y][x];
        score += line_penalty(lane);
    }
    for (y = 0; y + 1 < size; y++)      /* 2: 2x2 blocks of one colour */
        for (x = 0; x + 1 < size; x++) {
            k = modules[y][x];
            if (modules[y][x + 1] == k && modules[y + 1][x] == k && modules[y + 1][x + 1] == k)
                score += 3;
        }
    for (y = 0; y < size; y++)          /* 4: 10 for each 5% from half dark */
        for (x = 0; x < size; x++)
            dark += modules[y][x];
    total = size * size;
    k = dark * 20 - total * 10;
    if (k < 0)
        k = -k;
    k = (k + total - 1) / total - 1;
    return score + k * 10;
}

/* ---- encoding ---- */

static void append_bits(int value, int n)
{
    int i;
    for (i = n - 1; i >= 0; i--, count++)
        codewords[count >> 3] |= ((value >> i) & 1) << (7 - (count & 7));
}

/* text -> codewords[] with the error correction, interleaved; returns how
   many */
static int make_codewords(const char *text, int len, int version, int level)
{
    static int data[MAX_CODEWORDS], ecc[MAX_ECC], divisor[MAX_ECC];
    int capacity = data_codewords(version, level), i, j, b;
    int blocks = num_blocks[level][version], n = ecc_per_block[level][version];
    int raw = raw_modules(version) / 8, short_blocks = blocks - raw % blocks;
    int short_len = raw / blocks - n;   /* data codewords in a short block */
    int start, out;

    /* the bit stream: byte mode, the count, the bytes, up to 4 zero bits,
       zeros to a byte boundary, then the pad bytes EC 11 EC 11 ... */
    for (i = 0; i < raw; i++)
        codewords[i] = 0;
    count = 0;
    append_bits(4, 4);
    append_bits(len, version < 10 ? 8 : 16);
    for (i = 0; i < len; i++)
        append_bits(text[i] & 0xFF, 8);
    append_bits(0, capacity * 8 - count < 4 ? capacity * 8 - count : 4);
    append_bits(0, (8 - count % 8) % 8);
    for (b = 0xEC; count < capacity * 8; b ^= 0xEC ^ 0x11)
        append_bits(b, 8);
    for (i = 0; i < capacity; i++)
        data[i] = codewords[i];

    /* block i holds short_len (+1 for the long ones) data codewords, then
       n of error correction. The output takes the data codewords column
       by column across the blocks, then the error correction ones */
    rs_divisor(n, divisor);
    out = 0;
    for (i = 0; i <= short_len; i++)
        for (b = 0, start = 0; b < blocks; b++) {
            j = short_len + (b >= short_blocks);
            if (i < j)
                codewords[out++] = data[start + i];
            start += j;
        }
    for (b = 0, start = 0; b < blocks; b++) {
        j = short_len + (b >= short_blocks);
        rs_remainder(data + start, j, divisor, n, ecc);
        for (i = 0; i < n; i++)
            codewords[out + i * blocks + b] = ecc[i];
        start += j;
    }
    return raw;
}

/* encodes text into modules[][]; returns the version, or 0 if it doesn't
   fit in version 10 */
static int encode(const char *text, int level, int *mask_used)
{
    int len = strlen(text), version, total, mask, best = 0, best_score = -1, score;
    for (version = 1; version <= MAX_VERSION; version++)
        if (needed_bits(version, len) <= data_codewords(version, level) * 8)
            break;
    if (version > MAX_VERSION)
        return 0;
    size = 17 + 4 * version;
    total = make_codewords(text, len, version, level);
    draw_function_patterns(version, level);
    draw_codewords(total);
    for (mask = 0; mask < 8; mask++) {
        apply_mask(mask);
        draw_format(level, mask);
        score = MASK < 0 ? penalty() : mask != MASK;
        if (best_score < 0 || score < best_score) {
            best = mask;
            best_score = score;
        }
        apply_mask(mask);
    }
    apply_mask(best);
    draw_format(level, best);
    *mask_used = best;
    return version;
}

/* ---- the screen ---- */

/* the code as big as fits with its quiet zone, in the middle; returns the
   pixels per module */
static int draw_code(void)
{
    int scale = GFX_WIDTH / (size + 2 * QUIET), offset, x, y, run;
    offset = (GFX_WIDTH - size * scale) / 2;
    gfx_fill_rect(0, 0, GFX_WIDTH, GFX_HEIGHT, LIGHT);
    for (y = 0; y < size; y++)
        for (x = 0; x < size; x += run) {
            for (run = 1; x + run < size && modules[y][x + run] == modules[y][x]; run++)
                ;
            if (modules[y][x])
                gfx_fill_rect(offset + x * scale, offset + y * scale, run * scale, scale, DARK);
        }
    return scale;
}

static void show(const char *text)
{
    int version, mask, scale;
    clock_t start = clock();
    version = encode(text, LEVEL, &mask);
    printf("QR: %s\n", text);
    if (!version) {
        printf("  too long: %d bytes, version %d at level %c holds %d\n", (int)strlen(text),
               MAX_VERSION, level_names[LEVEL], data_codewords(MAX_VERSION, LEVEL) - 3);
        gfx_fill_rect(0, BAR_Y, GFX_WIDTH, GFX_CHAR_HEIGHT, BAR);
        gfx_text(0, BAR_Y, "too long", ERROR, GFX_NONE);
        return;
    }
    scale = draw_code();
    printf("  version %d (%dx%d), level %c, mask %d, %d bytes, %d pixel%s a module  (%d ms)\n",
           version, size, size, level_names[LEVEL], mask, (int)strlen(text), scale,
           scale == 1 ? "" : "s", (int)(clock() - start));
}

/* the line being typed on a bar at the bottom (its end if it's long); the
   bar goes when the line is empty */
static void draw_input(void)
{
    int shown = GFX_WIDTH / GFX_CHAR_WIDTH - 1;
    const char *s = line_len > shown ? line + line_len - shown : line;
    if (line_len == 0) {                /* the quiet zone is at least 8 pixels */
        gfx_fill_rect(0, BAR_Y, GFX_WIDTH, GFX_CHAR_HEIGHT, LIGHT);
        return;
    }
    gfx_fill_rect(0, BAR_Y, GFX_WIDTH, GFX_CHAR_HEIGHT, BAR);
    gfx_text(gfx_text(0, BAR_Y, s, BAR_TEXT, GFX_NONE), BAR_Y, "_", BAR_TEXT, GFX_NONE);
}

int main(void)
{
    int key;
    gf_init();
    show(TEXT);
    for (;;) {
        key = wait_key();
        if (key == '\n') {
            show(line_len > 0 ? line : TEXT);
            line_len = 0;
            line[0] = 0;
            continue;
        } else if (key == 8) {
            if (line_len > 0)
                line[--line_len] = 0;
        } else if (key == 4)            /* Ctrl-D: the end of --keys input */
            break;
        else if (key >= 32 && key < 127 && line_len < MAX_LINE) {
            line[line_len++] = key;
            line[line_len] = 0;
        }
        draw_input();
    }
    return 0;
}
