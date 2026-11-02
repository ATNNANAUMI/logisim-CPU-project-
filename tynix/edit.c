/* edit.c - a full-screen text editor on the RGB screen (a program for Tynix, in /bin)
 *
 *   python tynix/make_disk.py              (builds it into /bin)
 *   (in the shell)   edit notes.txt
 *
 * The text shows on the 256 x 256 RGB screen, 42 columns by 31 lines, with a
 * status line under it (file name, * when unsaved, line and column, or the
 * last message). Keys go to the keyboard device, so type with the simulator
 * window focused. A missing file starts empty and is made by Ctrl-S; a binary
 * file (a program) is refused. Lines are at most 255 chars.
 *
 *   printable keys  insert            Enter  split the line
 *   Backspace       delete left       (at the start of a line: join with the one above)
 *   arrows          move              Ctrl-A, Ctrl-E  start / end of the line
 *   Ctrl-B, Ctrl-F  page up / down    Ctrl-K  delete the line
 *   Ctrl-S          save              Ctrl-Q  quit (unsaved: warns, a second Ctrl-Q quits)
 *   Ctrl-G          lists these keys on the status line
 *
 * The screen is redrawn at most 30 times a second, however fast keys come,
 * and only the cells that changed (a typed char redraws a few cells and the
 * status line, not the page). Ctrl-D is not used
 * (it is Tynix's end of input).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <time.h>
#include <cpu.h>
#include <gfx.h>

#define FRAME_MS 33             /* the screen is redrawn at most every 33 ms (30 fps) */
#define LINE_MAX 255            /* chars in a line */
#define COLS (GFX_WIDTH / GFX_CHAR_WIDTH)               /* 42 */
#define ROWS (GFX_HEIGHT / GFX_CHAR_HEIGHT - 1)         /* 31 text lines + the status line */
#define STATUS_ROW ROWS

struct line {
    char *s;                    /* malloc'd, len chars and a 0 */
    int len, cap;
};

static struct line *text;       /* text[0 .. count-1] */
static int count, room;
static int cy, cx;              /* the cursor: line (0-based) and column */
static int want;                /* the column up/down try to keep */
static int top, left;           /* first line / column shown */
static int dirty, warned;
static char name[256];
static const char *message;     /* shown on the status line until the next key */
static int shown[ROWS + 1][COLS];       /* what each cell shows now: char | 0x100 if inverted; -1 unknown */

static int out_of_memory(void)
{
    message = "out of memory";
    return -1;
}

/* a line of room chars + 1 for the 0 */
static int reserve(struct line *l, int n)
{
    char *bigger;
    int cap;
    if (n + 1 <= l->cap)
        return 0;
    cap = n + 17;
    if (cap > LINE_MAX + 1)
        cap = LINE_MAX + 1;
    if ((bigger = realloc(l->s, cap)) == 0)
        return out_of_memory();
    l->s = bigger;
    l->cap = cap;
    return 0;
}

/* a new empty line at index at */
static int add_line(int at)
{
    if (count == room) {
        struct line *bigger = realloc(text, (room + 64) * sizeof(struct line));
        if (bigger == 0)
            return out_of_memory();
        text = bigger;
        room += 64;
    }
    memmove(text + at + 1, text + at, (count - at) * sizeof(struct line));
    text[at].s = 0;
    text[at].len = text[at].cap = 0;
    if (reserve(&text[at], 0)) {
        memmove(text + at, text + at + 1, (count - at) * sizeof(struct line));
        return -1;
    }
    text[at].s[0] = 0;
    count++;
    return 0;
}

static void drop_line(int at)
{
    free(text[at].s);
    memmove(text + at, text + at + 1, (count - at - 1) * sizeof(struct line));
    count--;
}

static int load(const char *file)
{
    struct stat st;
    FILE *f;
    int c, chars = 0;
    if (stat(file, &st)) {
        if (errno != ENOENT) {
            printf("%s: %s\n", file, strerror(errno));
            return -1;
        }
        return add_line(0);
    }
    if (!S_ISREG(st.st_mode) || !S_ISTEXT(st.st_mode)) {
        printf("%s: not a text file\n", file);
        return -1;
    }
    if ((f = fopen(file, "r")) == 0) {
        printf("%s: %s\n", file, strerror(errno));
        return -1;
    }
    if (add_line(0)) {
        fclose(f);
        printf("out of memory\n");
        return -1;
    }
    while ((c = fgetc(f)) != EOF) {
        struct line *l = &text[count - 1];
        chars++;
        if (c == '\n' || l->len == LINE_MAX) {
            if (add_line(count)) {
                fclose(f);
                printf("out of memory\n");
                return -1;
            }
            if (c == '\n')
                continue;
            l = &text[count - 1];
        }
        if (reserve(l, l->len + 1)) {
            fclose(f);
            printf("out of memory\n");
            return -1;
        }
        l->s[l->len++] = c;
        l->s[l->len] = 0;
    }
    fclose(f);
    if (count > 1 && text[count - 1].len == 0)  /* the file ended with a newline */
        drop_line(count - 1);
    return 0;
}

static int save(void)
{
    static char note[40];
    FILE *f = fopen(name, "w");
    int i, chars = 0;
    if (f == 0) {
        message = strerror(errno);
        return -1;
    }
    for (i = 0; i < count; i++) {
        if (i < count - 1 || text[i].len) {     /* an empty last line is not written */
            fputs(text[i].s, f);
            fputc('\n', f);
            chars += text[i].len + 1;
        }
    }
    if (fclose(f) || ferror(f)) {
        message = "could not write (disk full?)";
        return -1;
    }
    sprintf(note, "saved %d chars", chars);
    message = note;
    dirty = warned = 0;
    return 0;
}

/* ---- the screen ---- */

/* what the cell should show: the char, 0x100 added when it is drawn inverted */
static int cell(int row, int col)
{
    static char status[COLS + 1];
    int y, x;
    if (row == STATUS_ROW) {
        if (col == 0) {
            if (message)
                sprintf(status, "%-*.*s", COLS, COLS, message);
            else {
                char where[16];
                int w, n;
                sprintf(where, "%d:%d", cy + 1, cx + 1);
                w = strlen(where);
                n = strlen(name);
                if (n > COLS - w - 2)
                    n = COLS - w - 2;
                sprintf(status, "%-*.*s%c%*s", COLS - w - 1, n, name,
                        dirty ? '*' : ' ', w, where);
                /* name, then the * column, then the position, COLS chars in all */
            }
        }
        return status[col] | 0x100;
    }
    y = top + row;
    x = left + col;
    if (y >= count)
        return ' ';
    if (y == cy && x == cx)
        return (x < text[y].len ? text[y].s[x] : ' ') | 0x100;
    return x < text[y].len ? text[y].s[x] : ' ';
}

static void refresh(void)
{
    int row, col, v;
    if (cy < top)
        top = cy;
    if (cy >= top + ROWS)
        top = cy - ROWS + 1;
    if (cx < left)
        left = cx;
    if (cx >= left + COLS)
        left = cx - COLS + 1;
    for (row = 0; row <= STATUS_ROW; row++)
        for (col = 0; col < COLS; col++) {
            v = cell(row, col);
            if (v == shown[row][col])
                continue;
            shown[row][col] = v;
            if (v & 0x100)
                gfx_char(col * GFX_CHAR_WIDTH, row * GFX_CHAR_HEIGHT, v & 0xFF, GFX_BLACK, GFX_WHITE);
            else
                gfx_char(col * GFX_CHAR_WIDTH, row * GFX_CHAR_HEIGHT, v, GFX_WHITE, GFX_BLACK);
        }
}

static void blank_screen(void)
{
    int row, col;
    gfx_fill_rect(0, 0, GFX_WIDTH, GFX_HEIGHT, GFX_BLACK);
    for (row = 0; row <= STATUS_ROW; row++)
        for (col = 0; col < COLS; col++)
            shown[row][col] = ' ';
}

/* ---- editing ---- */

static void insert(int c)
{
    struct line *l = &text[cy];
    if (l->len >= LINE_MAX) {
        message = "line is full (255)";
        return;
    }
    if (reserve(l, l->len + 1))
        return;
    memmove(l->s + cx + 1, l->s + cx, l->len - cx + 1);
    l->s[cx++] = c;
    l->len++;
    dirty = 1;
    want = cx;
}

static void split(void)
{
    struct line *l;
    if (add_line(cy + 1))
        return;
    l = &text[cy];
    if (reserve(&text[cy + 1], l->len - cx)) {
        drop_line(cy + 1);
        return;
    }
    memcpy(text[cy + 1].s, l->s + cx, l->len - cx + 1);
    text[cy + 1].len = l->len - cx;
    l->s[cx] = 0;
    l->len = cx;
    cy++;
    cx = want = 0;
    dirty = 1;
}

static void backspace(void)
{
    struct line *l = &text[cy];
    if (cx > 0) {
        memmove(l->s + cx - 1, l->s + cx, l->len - cx + 1);
        l->len--;
        cx--;
    } else if (cy > 0) {
        struct line *up = &text[cy - 1];
        if (up->len + l->len > LINE_MAX) {
            message = "line would be too long";
            return;
        }
        if (reserve(up, up->len + l->len))
            return;
        memcpy(up->s + up->len, l->s, l->len + 1);
        cx = up->len;
        up->len += l->len;
        drop_line(cy);
        cy--;
    } else
        return;
    want = cx;
    dirty = 1;
}

static void delete_line(void)
{
    if (count == 1) {
        text[0].s[0] = 0;
        text[0].len = 0;
    } else {
        drop_line(cy);
        if (cy == count)
            cy--;
    }
    cx = want = 0;
    dirty = 1;
}

static void clamp(void)
{
    cx = want < text[cy].len ? want : text[cy].len;
}

static void move_to_line(int y)
{
    if (y < 0)
        y = 0;
    if (y >= count)
        y = count - 1;
    cy = y;
    clamp();
}

static const char *HELP[] = {"^S save  ^Q quit", "^K del line ^A ^E", "^B ^F page up/down"};

int main(int argc, char **argv)
{
    int k, quit = 0, help = 0, stale = 1;
    unsigned int last = 0;
    if (argc != 2) {
        printf("usage: edit FILE\n");
        return 1;
    }
    strncpy(name, argv[1], sizeof name - 1);
    if (load(name))
        return 1;
    blank_screen();
    message = "^G keys";
    while (!quit) {
        if ((k = key_pressed()) == 0) {         /* no key: redraw if something changed and a frame has passed */
            if (stale && (unsigned int)clock() - last >= FRAME_MS) {
                refresh();
                last = clock();
                stale = 0;
            }
            continue;
        }
        stale = 1;
        message = 0;
        if (k != KEY_CTRL('q'))
            warned = 0;
        if (k != KEY_CTRL('g'))
            help = 0;
        if (k >= 32 && k < 127)
            insert(k);
        else if (k == '\n')
            split();
        else if (k == '\b')
            backspace();
        else if (k == KEY_LEFT) {
            if (cx > 0)
                cx--;
            else if (cy > 0) {
                cy--;
                cx = text[cy].len;
            }
            want = cx;
        } else if (k == KEY_RIGHT) {
            if (cx < text[cy].len)
                cx++;
            else if (cy < count - 1) {
                cy++;
                cx = 0;
            }
            want = cx;
        } else if (k == KEY_UP)
            move_to_line(cy - 1);
        else if (k == KEY_DOWN)
            move_to_line(cy + 1);
        else if (k == KEY_CTRL('a'))
            cx = want = 0;
        else if (k == KEY_CTRL('e'))
            cx = want = text[cy].len;
        else if (k == KEY_CTRL('b'))
            move_to_line(cy - ROWS);
        else if (k == KEY_CTRL('f'))
            move_to_line(cy + ROWS);
        else if (k == KEY_CTRL('k'))
            delete_line();
        else if (k == KEY_CTRL('s'))
            save();
        else if (k == KEY_CTRL('g'))
            message = HELP[help++ % 3];
        else if (k == KEY_CTRL('q')) {
            if (dirty && !warned) {
                warned = 1;
                message = "unsaved: ^Q again";
            } else
                quit = 1;
        }
    }
    gfx_fill_rect(0, 0, GFX_WIDTH, GFX_HEIGHT, GFX_BLACK);
    return 0;
}
