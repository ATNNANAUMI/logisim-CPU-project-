/* chip8.c - a CHIP-8 interpreter (a program for Tynix, in /bin)
 *
 *   python tynix/make_disk.py              (builds it into /bin)
 *   (in the shell)   chip8 FILE [CYCLES]   run a program, CYCLES instructions per frame (default 10)
 *                    chip8 -t FRAMES       test mode: read a program from the keyboard (stdin),
 *                                          run FRAMES frames, print the state and the screen
 *
 * CHIP-8 is a 1970s virtual machine: 4K bytes of memory, sixteen 8-bit registers V0-VF
 * (VF is the carry/collision flag), a 16-bit index register I, a call stack of 16, two
 * 60 Hz timers, a 64x32 one-colour screen drawn by XOR-ing sprites, and a 16-key hex pad.
 * All 35 instructions are here (no SUPER-CHIP ones).
 *
 * Program files are TEXT: the program's bytes as hex digits, separated by anything that is
 * not a hex digit, with # comments to the end of a line (so `edit` can write them):
 *     6005 6107 8014   # V0 = 5; V1 = 7; V0 += V1
 * Programs are loaded at 0x200, the font (digits 0-F, 5 rows each) is at 0.
 *
 * Choices where interpreters differ: 8XY6 and 8XYE shift VX (not VY); FX55 and FX65 leave I
 * alone; 8XY1, 8XY2 and 8XY3 leave VF alone; a sprite is clipped at the screen's edges but
 * starts at its position modulo the screen; BNNN jumps to NNN + V0; CXNN uses a fixed LCG
 * (the same numbers every run). A frame is CYCLES instructions followed by one tick of the
 * timers, and a frame lasts 1/60 s.
 *
 * Screen: 4x4 pixels per CHIP-8 pixel (256x128) in the middle of the RGB screen, redrawn only
 * where a pixel changed. Keys: 1 2 3 4 / Q W E R / A S D F / Z X C V are the pad's 1 2 3 C /
 * 4 5 6 D / 7 8 9 E / A 0 B F; the keyboard has no key-up, so a key counts as held for 9 frames
 * (150 ms) after each press. P pauses and the backquote key ` quits (Esc is the kernel's menu).
 *
 * Exit status: 0, or 1 when the file cannot be read.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef CHIP8_NO_SCREEN
#include <cpu.h>
#include <gfx.h>
#include <time.h>
#endif

#define MEM 4096
#define W 64
#define H 32

static int mem[MEM];                    /* one byte per word */
static int v[16], stack[16], sp;
static int pc = 0x200, idx, dt, st;
static int screen[H][W];
static int keys[16];                    /* frames left that the key counts as held */
static unsigned rnd = 1;
static int waiting = -1;                /* FX0A: the register that wants a key, or -1 */

static const int font[80] = {
    0xF0, 0x90, 0x90, 0x90, 0xF0, 0x20, 0x60, 0x20, 0x20, 0x70,
    0xF0, 0x10, 0xF0, 0x80, 0xF0, 0xF0, 0x10, 0xF0, 0x10, 0xF0,
    0x90, 0x90, 0xF0, 0x10, 0x10, 0xF0, 0x80, 0xF0, 0x10, 0xF0,
    0xF0, 0x80, 0xF0, 0x90, 0xF0, 0xF0, 0x10, 0x20, 0x40, 0x40,
    0xF0, 0x90, 0xF0, 0x90, 0xF0, 0xF0, 0x90, 0xF0, 0x10, 0xF0,
    0xF0, 0x90, 0xF0, 0x90, 0x90, 0xE0, 0x90, 0xE0, 0x90, 0xE0,
    0xF0, 0x80, 0x80, 0x80, 0xF0, 0xE0, 0x90, 0x90, 0x90, 0xE0,
    0xF0, 0x80, 0xF0, 0x80, 0xF0, 0xF0, 0x80, 0xF0, 0x80, 0x80
};

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

/* read a program from f into memory at 0x200; returns the bytes read */
static int load_hex(FILE *f)
{
    int c, high = -1, n = 0, comment = 0;
    while ((c = getc(f)) != EOF) {
        int d;
        if (c == '\n')
            comment = 0;
        if (c == '#')
            comment = 1;
        if (comment)
            continue;
        d = hexval(c);
        if (d < 0) {
            high = -1;                  /* a separator: a lone digit is dropped */
            continue;
        }
        if (high < 0) {
            high = d;
        } else {
            if (0x200 + n >= MEM)
                break;
            mem[0x200 + n++] = high * 16 + d;
            high = -1;
        }
    }
    return n;
}

static unsigned next_random(void)
{
    rnd = rnd * 1103515245u + 12345u;
    return (rnd >> 16) & 0xFF;
}

/* one instruction */
static void step(void)
{
    int op = mem[pc & 0xFFF] << 8 | mem[(pc + 1) & 0xFFF];
    int x = (op >> 8) & 15, y = (op >> 4) & 15, n = op & 15, nn = op & 0xFF, nnn = op & 0xFFF;
    int i, r;
    if (waiting >= 0) {                 /* FX0A: wait for a key */
        for (i = 0; i < 16; i++)
            if (keys[i] > 0) {
                v[waiting] = i;
                waiting = -1;
                pc += 2;
                return;
            }
        return;
    }
    pc += 2;
    switch (op >> 12) {
    case 0:
        if (op == 0x00E0)
            memset(screen, 0, sizeof screen);
        else if (op == 0x00EE)
            pc = sp > 0 ? stack[--sp] : pc;
        break;
    case 1: pc = nnn; break;
    case 2:
        if (sp < 16)
            stack[sp++] = pc;
        pc = nnn;
        break;
    case 3: if (v[x] == nn) pc += 2; break;
    case 4: if (v[x] != nn) pc += 2; break;
    case 5: if (n == 0 && v[x] == v[y]) pc += 2; break;
    case 6: v[x] = nn; break;
    case 7: v[x] = (v[x] + nn) & 255; break;
    case 8:
        switch (n) {
        case 0: v[x] = v[y]; break;
        case 1: v[x] |= v[y]; break;
        case 2: v[x] &= v[y]; break;
        case 3: v[x] ^= v[y]; break;
        case 4: r = v[x] + v[y]; v[x] = r & 255; v[15] = r > 255; break;
        case 5: r = v[x] >= v[y]; v[x] = (v[x] - v[y]) & 255; v[15] = r; break;
        case 6: r = v[x] & 1; v[x] >>= 1; v[15] = r; break;
        case 7: r = v[y] >= v[x]; v[x] = (v[y] - v[x]) & 255; v[15] = r; break;
        case 14: r = v[x] >> 7; v[x] = (v[x] << 1) & 255; v[15] = r; break;
        }
        break;
    case 9: if (n == 0 && v[x] != v[y]) pc += 2; break;
    case 10: idx = nnn; break;
    case 11: pc = (nnn + v[0]) & 0xFFF; break;
    case 12: v[x] = next_random() & nn; break;
    case 13: {                          /* DXYN: XOR an 8 x N sprite from memory at I */
        int row, bit, px = v[x] % W, py = v[y] % H;
        v[15] = 0;
        for (row = 0; row < n && py + row < H; row++) {
            int bits = mem[(idx + row) & 0xFFF];
            for (bit = 0; bit < 8 && px + bit < W; bit++)
                if (bits & (0x80 >> bit)) {
                    if (screen[py + row][px + bit])
                        v[15] = 1;
                    screen[py + row][px + bit] ^= 1;
                }
        }
        break;
    }
    case 14:
        if (nn == 0x9E && keys[v[x] & 15] > 0)
            pc += 2;
        else if (nn == 0xA1 && keys[v[x] & 15] <= 0)
            pc += 2;
        break;
    case 15:
        switch (nn) {
        case 0x07: v[x] = dt; break;
        case 0x0A: waiting = x; pc -= 2; break;
        case 0x15: dt = v[x]; break;
        case 0x18: st = v[x]; break;
        case 0x1E: idx = (idx + v[x]) & 0xFFF; break;
        case 0x29: idx = (v[x] & 15) * 5; break;
        case 0x33:
            mem[idx & 0xFFF] = v[x] / 100;
            mem[(idx + 1) & 0xFFF] = v[x] / 10 % 10;
            mem[(idx + 2) & 0xFFF] = v[x] % 10;
            break;
        case 0x55: for (i = 0; i <= x; i++) mem[(idx + i) & 0xFFF] = v[i]; break;
        case 0x65: for (i = 0; i <= x; i++) v[i] = mem[(idx + i) & 0xFFF]; break;
        }
        break;
    }
}

static void frame(int cycles)
{
    int i;
    for (i = 0; i < cycles; i++)
        step();
    if (dt > 0)
        dt--;
    if (st > 0)
        st--;
    for (i = 0; i < 16; i++)
        if (keys[i] > 0)
            keys[i]--;
}

static void dump(void)
{
    int i, y, x;
    printf("PC=%04X I=%04X SP=%d DT=%02X ST=%02X\n", pc, idx, sp, dt, st);
    for (i = 0; i < 16; i++)
        printf("%02X%c", v[i], i == 15 ? '\n' : ' ');
    for (y = 0; y < H; y++) {
        for (x = 0; x < W; x += 4)
            printf("%X", screen[y][x] << 3 | screen[y][x + 1] << 2 | screen[y][x + 2] << 1 | screen[y][x + 3]);
        printf("\n");
    }
}

#ifndef CHIP8_NO_SCREEN
#define PIXEL 4
#define OX ((GFX_WIDTH - W * PIXEL) / 2)
#define OY ((GFX_HEIGHT - H * PIXEL) / 2)

static int shown[H][W];                 /* what the RGB screen holds now */

static void draw(int all)
{
    int y, x;
    for (y = 0; y < H; y++)
        for (x = 0; x < W; x++)
            if (all || screen[y][x] != shown[y][x]) {
                gfx_fill_rect(OX + x * PIXEL, OY + y * PIXEL, PIXEL, PIXEL,
                              screen[y][x] ? GFX_WHITE : GFX_RGB(16, 24, 16));
                shown[y][x] = screen[y][x];
            }
}

static int pad_key(int c)
{
    static const char map[] = "1234qwerasdfzxcv";   /* the pad keys 1 2 3 C 4 5 6 D 7 8 9 E A 0 B F */
    static const int pad[16] = {1, 2, 3, 12, 4, 5, 6, 13, 7, 8, 9, 14, 10, 0, 11, 15};
    int i;
    if (c >= 'A' && c <= 'Z')
        c += 32;
    for (i = 0; i < 16; i++)
        if (map[i] == c)
            return pad[i];
    return -1;
}

static int play(int cycles)
{
    clock_t start = clock();
    int frames = 0, paused = 0;
    gfx_clear();
    gfx_fill_rect(OX - 2, OY - 2, W * PIXEL + 4, H * PIXEL + 4, GFX_GRAY);
    draw(1);
    gfx_text(4, 4, "chip8   ` quits  p pauses", GFX_GRAY, GFX_NONE);
    for (;;) {
        int k = key_pressed(), pk;
        if (gfx_lost()) {
            gfx_clear();
            gfx_fill_rect(OX - 2, OY - 2, W * PIXEL + 4, H * PIXEL + 4, GFX_GRAY);
            draw(1);
        }
        if (k == '`')
            return 0;
        if (k == 'p' || k == 'P') {
            paused = !paused;
            start = clock() - frames * 1000 / 60;       /* time stands still while paused */
        }
        if ((pk = pad_key(k)) >= 0)
            keys[pk] = 9;
        if (paused) {
            start = clock() - frames * 1000 / 60;
        } else if ((int)(clock() - start) >= frames * 1000 / 60) {
            frame(cycles);
            frames++;
            draw(0);
        }
    }
}
#endif

int main(int argc, char **argv)
{
    int i, n, cycles = 10;
    FILE *f;

    memset(mem, 0, sizeof mem);
    for (i = 0; i < 80; i++)
        mem[i] = font[i];
    if (argc >= 3 && strcmp(argv[1], "-t") == 0) {          /* test mode: the program is on stdin */
        int frames = atoi(argv[2]);
        load_hex(stdin);
        for (i = 0; i < frames; i++)
            frame(cycles);
        dump();
        return 0;
    }
    if (argc < 2) {
        printf("usage: chip8 FILE [CYCLES]   (see the header of tynix/bin/chip8.c)\n");
        return 1;
    }
    if (argc >= 3)
        cycles = atoi(argv[2]) > 0 ? atoi(argv[2]) : 10;
    f = fopen(argv[1], "r");
    if (!f) {
        printf("chip8: cannot read %s\n", argv[1]);
        return 1;
    }
    n = load_hex(f);
    fclose(f);
    if (n == 0) {
        printf("chip8: %s has no program\n", argv[1]);
        return 1;
    }
#ifndef CHIP8_NO_SCREEN
    play(cycles);
#endif
    return 0;
}
