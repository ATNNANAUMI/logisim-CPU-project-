/* visual_file_manager.c - a file manager on the RGB screen, in the style of yazi
 * (a program for Tynix, in /bin)
 *
 *   python os/make_disk.py                 (builds it into /bin)
 *   (in the shell)   visual_file_manager [dir [name [copy|cut path]]]
 *
 * Two panes on the 256 x 256 screen (42 columns by 32 rows, like edit.c):
 * the folder's entries on the left (folders first, then by name, folders in
 * cyan), a preview of the entry under the cursor on the right: the first lines
 * of a text file, the entries of a folder, "program, N words" for a program or
 * "binary, N words" for any other binary file. The top row is the folder's
 * path; the bottom rows are the full name of the entry (a name too long for
 * the list takes up to 4 rows) and the status line: entry number / count and
 * the free space (statvfs, as `df`), or the last message. Folders larger than
 * the screen scroll. Keys go to the keyboard device, so type with the
 * simulator window focused.
 *
 *   j k, Down Up       move the cursor      g G   first / last entry
 *   h, Left            the parent folder    Ctrl-F Ctrl-B   page down / up
 *   l, Right, Enter    go into a folder; open a file: a text file in `edit`,
 *                      a program (built --exe) runs; other binaries are refused
 *   y  x  p            copy / cut the entry; paste it here (never over an
 *                      existing name; a cut is a rename, so a file cannot be
 *                      lost; a copy that fails leaves no half file; a folder
 *                      can be cut but not copied)
 *   r                  rename (type the name, Enter; Ctrl-G or Ctrl-Q cancels)
 *   d                  delete, after asking (y); a folder only if it is empty
 *   a                  a new folder (type the name, Enter)
 *   ?                  the keys on the status line         q   quit
 *
 * Ctrl-D is not used (it is Tynix's end of input).
 *
 * Opening a file: a program for the OS cannot call spawnv() (the other
 * program would be loaded over this one), so it asks the shell to do it:
 * it writes the commands to run into the file /.next (the program, then this
 * manager again, started in the same folder on the same entry and with the
 * same clipboard: `visual_file_manager DIR NAME [copy|cut PATH]`) and exits with status
 * 254. os/shell.c runs those lines, so the manager comes back with the whole
 * screen drawn again, however much the program left on it.
 *
 * The screen code (the cache of what each cell shows, the 33 ms frame, key
 * polling) is edit.c's, written again here for a grid of cells; both could
 * share it if it moved into the C library.
 * Names are cut for display only. Paths use the full name everywhere.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>
#include <cpu.h>
#include <gfx.h>

#define FRAME_MS 33             /* the screen is redrawn at most every 33 ms (30 fps) */
#define COLS (GFX_WIDTH / GFX_CHAR_WIDTH)               /* 42 */
#define ROWS (GFX_HEIGHT / GFX_CHAR_HEIGHT)             /* 32: path, list, name rows, status */
#define STATUS_ROW (ROWS - 1)
#define LEFT 20                 /* the list's columns; column 20 is the divider */
#define PREVIEW_X (LEFT + 1)
#define PREVIEW_W (COLS - PREVIEW_X)                    /* 21 */
#define PATH_MAX 512
#define NAME_MAX 127
#define EXIT_NEXT 254           /* os/shell.c runs the commands in /.next after this status */
#define NEXT_FILE "/.next"
#define PREVIEW_CHARS 2000      /* at most this many chars of a text file are read for the preview */
#define TEX1 0x31584554         /* the first word of a program (compiler/libc/spawn.c) */

#define INVERT 0x100            /* a cell's attributes, added to its char */
#define CYAN 0x200

enum mode { NORMAL, RENAME, MKDIR, DELETE };

struct entry {
    char *name;
    int dir;
};

static char *prog;              /* argv[0]: how to start this program again */
static char cwd[PATH_MAX];      /* the folder shown: absolute, "/" or without a trailing / */
static struct entry *list;      /* sorted: folders first, then by name */
static int count;
static int cur, top;            /* the cursor, the first row shown */
static char clip[PATH_MAX];     /* the copied or cut path, "" if none */
static int clip_cut;
static enum mode mode;
static char input[NAME_MAX + 2];                /* what is being typed */
static int input_len;
static const char *message;     /* on the status line until the next key */
static char note[COLS + 40];    /* where a message with a name in it is written */
static unsigned free_kb;        /* free blocks, read after each change of the disk */
static int no_memory;           /* malloc failed in read_dir: errno has no code for it */
static int status;              /* the exit status */
static int quit;

static char preview[ROWS][PREVIEW_W + 1];       /* the right pane */
static int preview_dir[ROWS];                   /* that line is a folder (cyan) */
static int preview_n;
static char size_text[24];      /* "36 chars", "256 words", "folder" of the entry under the cursor */
static int preview_ok;          /* the preview is of the entry under the cursor */

static int want[ROWS][COLS];    /* what each cell should show: char | INVERT | CYAN */
static int shown[ROWS][COLS];   /* what it shows now; -1 unknown */

/* ---- paths and the disk ---- */

static void say(const char *what, const char *name, const char *why)
{
    snprintf(note, sizeof note, "%s%s%s%s%s", what, what[0] ? " " : "", name, why[0] ? ": " : "", why);
    message = note;
}

static void fail(const char *name)
{
    say("", name, no_memory ? "out of memory" : strerror(errno));
    no_memory = 0;
}

/* dir + "/" + name into out; 0, or -1 if it does not fit */
static int join(char *out, const char *dir, const char *name)
{
    if (strlen(dir) + strlen(name) + 2 > PATH_MAX)
        return -1;
    sprintf(out, "%s%s%s", dir, dir[1] ? "/" : "", name);
    return 0;
}

static const char *base_of(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static int by_name(const void *x, const void *y)
{
    const struct entry *a = x, *b = y;
    if (a->dir != b->dir)
        return b->dir - a->dir;
    return strcmp(a->name, b->name);
}

static void free_list(struct entry *l, int n)
{
    int i;
    for (i = 0; i < n; i++)
        free(l[i].name);
    free(l);
}

/* the sorted entries of a folder; -1 with errno set if it can't be read */
static int read_dir(const char *path, struct entry **out, int max)
{
    DIR *d = opendir(path);
    struct dirent *e;
    struct entry *l = 0, *bigger;
    int n = 0, room = 0;
    if (d == 0)
        return -1;
    while (n < max && (e = readdir(d))) {
        if (n == room) {
            if ((bigger = realloc(l, (room + 32) * sizeof *l)) == 0) {
                no_memory = 1;
                break;
            }
            l = bigger;
            room += 32;
        }
        if ((l[n].name = malloc(strlen(e->d_name) + 1)) == 0) {
            no_memory = 1;
            break;
        }
        strcpy(l[n].name, e->d_name);
        l[n++].dir = e->d_type == DT_DIR;
    }
    closedir(d);
    if (no_memory) {
        free_list(l, n);
        return -1;
    }
    if (n > 1)
        qsort(l, n, sizeof *l, by_name);
    *out = l;
    return n;
}

/* show the folder path; 0, or -1 with the message set (the old folder stays) */
static int load_dir(const char *path)
{
    struct entry *l;
    int n = read_dir(path, &l, 1 << 30);
    if (n < 0) {
        fail(path);
        return -1;
    }
    free_list(list, count);
    list = l;
    count = n;
    strcpy(cwd, path);
    preview_ok = 0;
    return 0;
}

static void select_name(const char *name)
{
    int i;
    cur = 0;
    for (i = 0; i < count; i++)
        if (strcmp(list[i].name, name) == 0)
            cur = i;
    preview_ok = 0;
}

/* the entry under the cursor as a full path; 0 if the folder is empty */
static int cur_path(char *out)
{
    if (count == 0)
        return 0;
    return join(out, cwd, list[cur].name) == 0;
}

static void update_free(void)
{
    struct statvfs s;
    free_kb = statvfs("/", &s) ? 0 : s.f_bfree;
}

/* after a change: read the folder again with the cursor on name */
static void reload(const char *name)
{
    char keep[NAME_MAX + 1];
    strcpy(keep, name ? name : count ? list[cur].name : "");
    if (load_dir(cwd) == 0)
        select_name(keep);
    if (cur >= count)
        cur = count ? count - 1 : 0;
    update_free();
}

static int is_program(const char *path)
{
    FILE *f = fopen(path, "rb");
    int c;
    if (f == 0)
        return 0;
    c = fgetc(f);
    fclose(f);
    return c == TEX1;
}

/* ---- the right pane ---- */

static void make_preview(void)
{
    char path[PATH_MAX];
    struct stat st;
    preview_n = 0;
    size_text[0] = 0;
    preview_ok = 1;
    memset(preview_dir, 0, sizeof preview_dir);
    if (count == 0) {
        strcpy(preview[preview_n++], "(empty folder)");
        return;
    }
    if (!cur_path(path)) {
        strcpy(preview[preview_n++], "(name too long)");
        return;
    }
    if (stat(path, &st)) {
        snprintf(preview[preview_n++], PREVIEW_W + 1, "%s", strerror(errno));
        return;
    }
    if (S_ISDIR(st.st_mode)) {
        struct entry *l;
        int n = read_dir(path, &l, ROWS), i;
        strcpy(size_text, "folder");
        if (n < 0)
            snprintf(preview[preview_n++], PREVIEW_W + 1, "%s", strerror(errno));
        else if (n == 0)
            strcpy(preview[preview_n++], "(empty)");
        for (i = 0; i < n && preview_n < ROWS; i++) {
            snprintf(preview[preview_n], PREVIEW_W + 1, "%s%s", l[i].name, l[i].dir ? "/" : "");
            preview_dir[preview_n++] = l[i].dir;
        }
        if (n >= 0)
            free_list(l, n);
    } else if (S_ISTEXT(st.st_mode)) {
        FILE *f = fopen(path, "r");
        int c, col = 0, chars = 0;
        sprintf(size_text, "%u chars", st.st_size);
        if (f == 0) {
            snprintf(preview[preview_n++], PREVIEW_W + 1, "%s", strerror(errno));
            return;
        }
        preview[0][0] = 0;
        while (chars++ < PREVIEW_CHARS && (c = fgetc(f)) != EOF) {
            if (c == '\n') {
                preview_n++;
                preview[preview_n][0] = 0;
                col = 0;
                if (preview_n == ROWS - 1)
                    break;
            } else if (col < PREVIEW_W) {
                preview[preview_n][col++] = c >= 32 && c < 127 ? c : '.';
                preview[preview_n][col] = 0;
            }
        }
        if (preview_n == 0 && preview[0][0] == 0)
            strcpy(preview[0], "(empty file)");
        else if (preview[preview_n][0])
            preview_n++;
        fclose(f);
    } else {
        sprintf(size_text, "%u words", st.st_size);
        sprintf(preview[preview_n++], "%s, %u words", is_program(path) ? "program" : "binary", st.st_size);
    }
}

/* ---- the screen ---- */

static void put(int row, int col, const char *s, int width, int attr)
{
    int i;
    for (i = 0; i < width && s[i]; i++)
        want[row][col + i] = (s[i] >= 32 && s[i] < 127 ? s[i] : '?') | attr;
}

static void fill(int row, int col, int width, int attr)
{
    int i;
    for (i = 0; i < width; i++)
        want[row][col + i] = ' ' | attr;
}

/* how many rows the entry's full name takes under the lists: 1 unless it is long */
static int name_rows(void)
{
    int n = count ? strlen(list[cur].name) + list[cur].dir : 0;
    return n > COLS ? (n + COLS - 1) / COLS : 1;
}

static void compose(void)
{
    char text[PATH_MAX + 1], full[NAME_MAX + 3];
    int rows = name_rows(), height = ROWS - 2 - rows;           /* rows of the lists */
    int r, i, n, attr;
    for (r = 0; r < ROWS; r++)
        fill(r, 0, COLS, 0);
    /* the path, from its end when it is too long */
    n = strlen(cwd);
    if (n > COLS) {
        text[0] = '~';
        strcpy(text + 1, cwd + n - (COLS - 1));
        put(0, 0, text, COLS, INVERT);
    } else
        put(0, 0, cwd, COLS, INVERT);
    fill(0, n > COLS ? COLS : n, COLS - (n > COLS ? COLS : n), INVERT);
    if (cur < top)
        top = cur;
    if (cur >= top + height)
        top = cur - height + 1;
    if (top < 0)
        top = 0;
    for (r = 0; r < height; r++) {
        want[1 + r][LEFT] = '|';
        i = top + r;
        if (i >= count) {
            if (count == 0 && r == 0)
                put(1, 1, "(empty)", LEFT - 1, 0);
            continue;
        }
        attr = (list[i].dir ? CYAN : 0) | (i == cur ? INVERT : 0);
        n = strlen(list[i].name);
        sprintf(full, "%s%s", list[i].name, list[i].dir ? "/" : "");
        if (i == cur)
            fill(1 + r, 0, LEFT, attr);
        if (clip[0]) {                                          /* the copied or cut entry */
            char path[PATH_MAX];
            if (join(path, cwd, list[i].name) == 0 && strcmp(path, clip) == 0)
                want[1 + r][0] = (clip_cut ? 'x' : '+') | attr;
        }
        if (strlen(full) > LEFT - 1) {
            full[LEFT - 2] = '~';
            full[LEFT - 1] = 0;
        }
        put(1 + r, 1, full, LEFT - 1, attr);
    }
    if (!preview_ok)
        make_preview();
    for (r = 0; r < preview_n && r < height; r++)
        put(1 + r, PREVIEW_X, preview[r], PREVIEW_W, preview_dir[r] && count && list[cur].dir ? CYAN : 0);
    /* the full name, and for a name that fits, its size on the right */
    if (count) {
        sprintf(text, "%s%s", list[cur].name, list[cur].dir ? "/" : "");
        for (r = 0; r < rows; r++)
            put(1 + height + r, 0, text + r * COLS, COLS, list[cur].dir ? CYAN : 0);
        n = strlen(text);
        if (rows == 1 && size_text[0] && n + 1 + (int)strlen(size_text) <= COLS)
            put(1 + height, COLS - strlen(size_text), size_text, COLS, 0);
    }
    /* the status line */
    fill(STATUS_ROW, 0, COLS, INVERT);
    if (mode == RENAME || mode == MKDIR) {
        const char *prompt = mode == RENAME ? "rename: " : "new folder: ";
        int room = COLS - strlen(prompt) - 1;
        put(STATUS_ROW, 0, prompt, COLS, INVERT);
        put(STATUS_ROW, strlen(prompt), input_len > room ? input + input_len - room : input, room, INVERT);
        want[STATUS_ROW][strlen(prompt) + (input_len > room ? room : input_len)] = '_' | INVERT;
    } else if (mode == DELETE) {
        snprintf(text, sizeof text, "delete %s? (y/n)", list[cur].name);
        put(STATUS_ROW, 0, text, COLS, INVERT);
    } else if (message)
        put(STATUS_ROW, 0, message, COLS, INVERT);
    else {
        sprintf(text, "%d/%d  %u KB free", count ? cur + 1 : 0, count, free_kb);
        put(STATUS_ROW, 0, text, COLS, INVERT);
    }
}

static void draw_cell(int row, int col, int v)
{
    int fg = (v & CYAN) ? GFX_CYAN : GFX_WHITE;
    if (v & INVERT)
        gfx_char(col * GFX_CHAR_WIDTH, row * GFX_CHAR_HEIGHT, v & 0xFF, GFX_BLACK, fg);
    else
        gfx_char(col * GFX_CHAR_WIDTH, row * GFX_CHAR_HEIGHT, v & 0xFF, fg, GFX_BLACK);
}

static void refresh(void)
{
    int row, col;
    compose();
    for (row = 0; row < ROWS; row++)
        for (col = 0; col < COLS; col++) {
            if (want[row][col] == shown[row][col])
                continue;
            shown[row][col] = want[row][col];
            draw_cell(row, col, want[row][col]);
        }
}

static void blank_screen(void)
{
    int row, col;
    gfx_fill_rect(0, 0, GFX_WIDTH, GFX_HEIGHT, GFX_BLACK);
    for (row = 0; row < ROWS; row++)
        for (col = 0; col < COLS; col++)
            shown[row][col] = ' ';
}

/* ---- actions ---- */

static int shell_safe(const char *s)
{
    for (; *s; s++)
        if (*s <= ' ' || *s >= 127 || *s == '"' || *s == '\'' || *s == '>')
            return 0;
    return 1;
}

/* a name that can be a file: 1-127 chars, no '/', space or control char */
static int good_name(const char *s)
{
    int n = strlen(s);
    if (n < 1 || n > NAME_MAX || strcmp(s, ".") == 0 || strcmp(s, "..") == 0)
        return 0;
    for (; *s; s++)
        if (*s == '/' || *s <= ' ' || *s == 127)
            return 0;
    return 1;
}

static void go_up(void)
{
    char parent[PATH_MAX], from[NAME_MAX + 1];
    char *slash;
    if (strcmp(cwd, "/") == 0)
        return;
    strcpy(from, base_of(cwd));
    strcpy(parent, cwd);
    slash = strrchr(parent, '/');
    if (slash == parent)
        slash[1] = 0;
    else
        *slash = 0;
    if (load_dir(parent) == 0)
        select_name(from);
    update_free();
}

/* leave for the shell: it runs cmd, then this program again where we are */
static void open_with(const char *cmd, const char *path)
{
    FILE *f;
    int again = strlen(prog) + strlen(cwd) + strlen(list[cur].name) + strlen(clip) + 16;
    int keep = clip[0] && shell_safe(clip) && again < 250;
    if (!shell_safe(path) || !shell_safe(cwd) || !shell_safe(list[cur].name) || again > 250) {
        say("", list[cur].name, "a name the shell cannot pass on");
        return;
    }
    if ((f = fopen(NEXT_FILE, "w")) == 0) {
        fail(NEXT_FILE);
        return;
    }
    fprintf(f, "%s\n%s %s %s", cmd, prog, cwd, list[cur].name);
    if (keep)
        fprintf(f, " %s %s", clip_cut ? "cut" : "copy", clip);
    fputc('\n', f);
    if (fclose(f) || ferror(f)) {
        remove(NEXT_FILE);
        say("", NEXT_FILE, "could not write (disk full?)");
        return;
    }
    status = EXIT_NEXT;
    quit = 1;
}

static void open_entry(void)
{
    char path[PATH_MAX], cmd[PATH_MAX + 8];
    struct stat st;
    if (count == 0 || !cur_path(path)) {
        message = count ? "path too long" : "nothing here";
        return;
    }
    if (list[cur].dir) {
        char from[1];
        from[0] = 0;
        if (load_dir(path) == 0)
            select_name(from);
        update_free();
        return;
    }
    if (stat(path, &st)) {
        fail(path);
        return;
    }
    if (S_ISTEXT(st.st_mode)) {
        if (stat("/bin/edit", &st)) {
            message = "no /bin/edit to open it with";
            return;
        }
        sprintf(cmd, "edit %s", path);
        open_with(cmd, path);
    } else if (is_program(path))
        open_with(path, path);
    else
        say("", list[cur].name, "not a text file or a program");
}

/* a copy of the file at from; a failed copy leaves nothing at to */
static int copy_file(const char *from, const char *to)
{
    struct stat st;
    FILE *in, *out;
    int c, text, bad;
    if (stat(from, &st))
        return -1;
    text = S_ISTEXT(st.st_mode);
    if ((in = fopen(from, text ? "r" : "rb")) == 0)
        return -1;
    if ((out = fopen(to, text ? "w" : "wb")) == 0) {
        fclose(in);
        return -1;
    }
    while ((c = fgetc(in)) != EOF || !feof(in))
        fputc(c, out);                  /* a binary word of -1 reads as EOF: feof tells */
    bad = ferror(in) || ferror(out);
    fclose(in);
    if (fclose(out))
        bad = 1;
    if (bad) {
        remove(to);
        errno = ENOSPC;
        return -1;
    }
    return 0;
}

static void paste(void)
{
    char to[PATH_MAX];
    struct stat st;
    const char *name = base_of(clip);
    if (!clip[0]) {
        message = "nothing to paste (y copy, x cut)";
        return;
    }
    if (join(to, cwd, name)) {
        message = "path too long";
        return;
    }
    if (stat(to, &st) == 0) {
        say("", name, "already exists here");
        return;
    }
    if (stat(clip, &st)) {
        fail(clip);
        clip[0] = 0;
        return;
    }
    if (clip_cut) {
        if (rename(clip, to)) {
            if (errno == EINVAL)
                message = "a folder cannot go inside itself";
            else
                fail(name);
            return;
        }
        clip[0] = 0;
    } else if (S_ISDIR(st.st_mode)) {
        message = "cannot copy a folder (x moves it)";
        return;
    } else if (copy_file(clip, to)) {
        fail(name);
        update_free();
        return;
    }
    reload(name);
    say("pasted", name, "");
}

static void start_input(enum mode m)
{
    if (m == RENAME) {
        strcpy(input, list[cur].name);
        input_len = strlen(input);
    } else
        input_len = input[0] = 0;
    mode = m;
}

static void finish_input(void)
{
    char path[PATH_MAX], to[PATH_MAX];
    enum mode m = mode;
    mode = NORMAL;
    if (!good_name(input)) {
        message = "not a good name (1-127 chars, no / or spaces)";
        return;
    }
    if (join(to, cwd, input)) {
        message = "path too long";
        return;
    }
    if (m == RENAME) {
        if (strcmp(input, list[cur].name) == 0)
            return;
        if (!cur_path(path) || rename(path, to)) {
            fail(list[cur].name);
            return;
        }
        if (strcmp(clip, path) == 0)
            strcpy(clip, to);
    } else if (mkdir(to)) {
        fail(input);
        return;
    }
    reload(input);
}

static void delete_entry(void)
{
    char path[PATH_MAX];
    int at = cur;
    mode = NORMAL;
    if (!cur_path(path) || remove(path)) {
        fail(list[cur].name);
        return;
    }
    if (strcmp(clip, path) == 0)
        clip[0] = 0;
    reload("");
    cur = at < count ? at : count - 1;
    if (cur < 0)
        cur = 0;
    preview_ok = 0;
    message = "deleted";
}

static void move_to(int i)
{
    if (i >= count)
        i = count - 1;
    if (i < 0)
        i = 0;
    cur = i;
    preview_ok = 0;
}

static void key_normal(int k)
{
    int page = ROWS - 3;
    if (k == 'j' || k == KEY_DOWN)
        move_to(cur + 1);
    else if (k == 'k' || k == KEY_UP)
        move_to(cur - 1);
    else if (k == 'g')
        move_to(0);
    else if (k == 'G')
        move_to(count - 1);
    else if (k == KEY_CTRL('f'))
        move_to(cur + page);
    else if (k == KEY_CTRL('b'))
        move_to(cur - page);
    else if (k == 'h' || k == KEY_LEFT)
        go_up();
    else if (k == 'l' || k == KEY_RIGHT || k == '\n')
        open_entry();
    else if (k == 'q')
        quit = 1;
    else if (k == '?')
        message = "hjkl move  y x p copy cut paste  r d a  q";
    else if (count == 0 && (k == 'y' || k == 'x' || k == 'r' || k == 'd'))
        message = "nothing here";
    else if (k == 'y' || k == 'x') {
        if (!cur_path(clip))
            message = "path too long";
        else {
            clip_cut = k == 'x';
            say(clip_cut ? "cut" : "copied", list[cur].name, "");
        }
    } else if (k == 'p')
        paste();
    else if (k == 'r')
        start_input(RENAME);
    else if (k == 'a')
        start_input(MKDIR);
    else if (k == 'd')
        mode = DELETE;
}

static void key_input(int k)
{
    if (k == '\n')
        finish_input();
    else if (k == KEY_CTRL('g') || k == KEY_CTRL('q'))
        mode = NORMAL;
    else if (k == '\b') {
        if (input_len > 0)
            input[--input_len] = 0;
    } else if (k >= 32 && k < 127 && input_len < NAME_MAX) {
        input[input_len++] = k;
        input[input_len] = 0;
    }
}

int main(int argc, char **argv)
{
    int k, stale = 1;
    unsigned int last = 0;
    prog = argv[0];
    if (argc > 5 || argc == 4) {
        printf("usage: visual_file_manager [dir [name [copy|cut path]]]\n");
        return 1;
    }
    getcwd(cwd, sizeof cwd);
    if (argc > 1 && chdir(argv[1]) == 0)
        getcwd(cwd, sizeof cwd);
    else if (argc > 1) {
        printf("visual_file_manager: %s: %s\n", argv[1], strerror(errno));
        return 1;
    }
    if (argc == 5 && strlen(argv[4]) < PATH_MAX) {
        strcpy(clip, argv[4]);
        clip_cut = strcmp(argv[3], "cut") == 0;
    }
    if (load_dir(cwd)) {
        printf("visual_file_manager: %s: %s\n", cwd, strerror(errno));
        return 1;
    }
    if (argc > 2)
        select_name(argv[2]);
    update_free();
    blank_screen();
    message = "? keys";
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
        if (mode == NORMAL)
            key_normal(k);
        else if (mode == DELETE) {
            if (k == 'y')
                delete_entry();
            else
                mode = NORMAL;
        } else
            key_input(k);
    }
    gfx_fill_rect(0, 0, GFX_WIDTH, GFX_HEIGHT, GFX_BLACK);
    return status;
}
