/* visual_file_manager.c - a file manager on the RGB screen, in the style of yazi
 * (a program for Tynix, in /bin)
 *
 *   python os/make_disk.py                 (builds it into /bin)
 *   (in the shell)   visual_file_manager [dir [name]]
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
 *   space              select the entry (shown as *) and go down; y x d then
 *                      work on all the selected entries instead of one
 *   y  x  p            copy / cut; paste here (never over an existing name;
 *                      a cut is a rename, so a file cannot be lost; a copy
 *                      that fails leaves no half file or folder; a folder is
 *                      copied with everything in it, but not into itself).
 *                      y or x again on the lone entry that is on the
 *                      clipboard takes it off
 *   u, Ctrl-G          forget the selection and the clipboard
 *   ~                  the home folder, /home/user (also where it starts with
 *                      no argument, when that folder exists)
 *   r                  rename (type the name, Enter; Ctrl-G or Ctrl-Q cancels)
 *   d                  delete, after asking (y), a folder with everything in it
 *                      (the question says how many things; there is no undo)
 *   a                  a new folder (type the name, Enter)
 *   ?                  the keys on the status line         q   quit
 *
 * Ctrl-D is not used (it is Tynix's end of input).
 *
 * Opening a file: a program for the OS cannot call spawnv() (the other
 * program would be loaded over this one), so it asks the shell to do it:
 * it writes the commands to run into the file /.next (the program, then this
 * manager again, started in the same folder on the same entry and with the
 * same clipboard, which goes through the file /.clipboard: `visual_file_manager
 * DIR NAME clip`) and exits with status 254. os/shell.c runs those lines, so the manager comes back with the whole
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
#define CLIP_FILE "/.clipboard" /* the clipboard, carried over to the next start of this program */
#define HOME "/home/user"       /* where it starts with no argument, and what ~ goes to */
#define CLIP_MAX 64
#define MAX_DEPTH 32            /* folders inside folders that copy and delete will go down (the stack is small) */
#define PREVIEW_CHARS 2000      /* at most this many chars of a text file are read for the preview */
#define TEX1 0x31584554         /* the first word of a program (compiler/libc/spawn.c) */

#define INVERT 0x100            /* a cell's attributes, added to its char */
#define CYAN 0x200

enum mode { NORMAL, RENAME, MKDIR, DELETE };

struct entry {
    char *name;
    int dir;
    int sel;                    /* marked with the space bar */
};

static char *prog;              /* argv[0]: how to start this program again */
static char cwd[PATH_MAX];      /* the folder shown: absolute, "/" or without a trailing / */
static struct entry *list;      /* sorted: folders first, then by name */
static int count;
static int cur, top;            /* the cursor, the first row shown */
static char *clips[CLIP_MAX];   /* the copied or cut paths, malloc'd */
static int nclip;
static int clip_cut;
static enum mode mode;
static char input[NAME_MAX + 2];                /* what is being typed */
static int input_len;
static const char *message;     /* on the status line until the next key */
static char note[COLS + 40];    /* where a message with a name in it is written */
static char delete_prompt[COLS + 40];           /* "delete NAME + 12 inside? (y/n)" */
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
        l[n].sel = 0;
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

/* ---- the selection and the clipboard ---- */

static int selected(void)
{
    int i, n = 0;
    for (i = 0; i < count; i++)
        n += list[i].sel;
    return n;
}

static void unselect_all(void)
{
    int i;
    for (i = 0; i < count; i++)
        list[i].sel = 0;
}

static void clip_clear(void)
{
    while (nclip > 0)
        free(clips[--nclip]);
}

static int in_clip(const char *path)
{
    int i;
    for (i = 0; i < nclip; i++)
        if (strcmp(clips[i], path) == 0)
            return 1;
    return 0;
}

static void clip_add(const char *path)
{
    char *p;
    if (nclip == CLIP_MAX)
        return;
    if ((p = malloc(strlen(path) + 1)) == 0) {
        no_memory = 1;
        return;
    }
    strcpy(p, path);
    clips[nclip++] = p;
}

/* a deleted path leaves the clipboard */
static void clip_forget(const char *path)
{
    int i, j = 0;
    for (i = 0; i < nclip; i++)
        if (strcmp(clips[i], path) == 0)
            free(clips[i]);
        else
            clips[j++] = clips[i];
    nclip = j;
}

/* a renamed path stays on the clipboard under its new name */
static void clip_rename(const char *from, const char *to)
{
    int i;
    char *p;
    for (i = 0; i < nclip; i++)
        if (strcmp(clips[i], from) == 0 && (p = malloc(strlen(to) + 1)) != 0) {
            strcpy(p, to);
            free(clips[i]);
            clips[i] = p;
        }
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
        if (list[i].sel)                                        /* * selected, + copied, x cut */
            want[1 + r][0] = '*' | attr;
        else if (nclip) {
            char path[PATH_MAX];
            if (join(path, cwd, list[i].name) == 0 && in_clip(path))
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
        put(STATUS_ROW, 0, delete_prompt, COLS, INVERT);
    } else if (message)
        put(STATUS_ROW, 0, message, COLS, INVERT);
    else {
        n = sprintf(text, "%d/%d  %u KB free", count ? cur + 1 : 0, count, free_kb);
        if (selected())
            n += sprintf(text + n, "  %d sel", selected());
        if (nclip)
            sprintf(text + n, "  %d %s", nclip, clip_cut ? "cut" : "copied");
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

/* show another folder, the cursor on its first entry */
static void go_to(const char *path)
{
    if (load_dir(path) == 0)
        select_name("");
    update_free();
}

/* the clipboard into CLIP_FILE (for the next start of this program); 0, or -1 with the message set */
static int save_clip(void)
{
    FILE *f = fopen(CLIP_FILE, "w");
    int i;
    if (f == 0) {
        fail(CLIP_FILE);
        return -1;
    }
    fprintf(f, "%s\n", clip_cut ? "cut" : "copy");
    for (i = 0; i < nclip; i++)
        fprintf(f, "%s\n", clips[i]);
    if (fclose(f) || ferror(f)) {
        remove(CLIP_FILE);
        say("", CLIP_FILE, "could not write (disk full?)");
        return -1;
    }
    return 0;
}

/* the clipboard another start of this program left in CLIP_FILE, which is deleted */
static void load_clip(void)
{
    static char line[PATH_MAX + 2];
    FILE *f = fopen(CLIP_FILE, "r");
    int first = 1;
    if (f == 0)
        return;
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\n")] = 0;
        if (first)
            clip_cut = strcmp(line, "cut") == 0;
        else if (line[0])
            clip_add(line);
        first = 0;
    }
    fclose(f);
    remove(CLIP_FILE);
}

/* leave for the shell: it runs cmd, then this program again where we are */
static void open_with(const char *cmd, const char *path)
{
    FILE *f;
    int again = strlen(prog) + strlen(cwd) + strlen(list[cur].name) + 16;
    if (!shell_safe(path) || !shell_safe(cwd) || !shell_safe(list[cur].name) || again > 250) {
        say("", list[cur].name, "a name the shell cannot pass on");
        return;
    }
    if (nclip && save_clip())
        return;
    if ((f = fopen(NEXT_FILE, "w")) == 0) {
        fail(NEXT_FILE);
        remove(CLIP_FILE);
        return;
    }
    fprintf(f, "%s\n%s %s %s%s\n", cmd, prog, cwd, list[cur].name, nclip ? " clip" : "");
    if (fclose(f) || ferror(f)) {
        remove(NEXT_FILE);
        remove(CLIP_FILE);
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
        go_to(path);
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

/* ---- folders and everything in them ---- */

/* dir/name in a malloc'd string, or 0 with errno (or no_memory) set */
static char *child(const char *dir, const char *name)
{
    char *p;
    if (strlen(dir) + strlen(name) + 2 > PATH_MAX) {
        errno = ENAMETOOLONG;
        return 0;
    }
    if ((p = malloc(strlen(dir) + strlen(name) + 2)) == 0) {
        no_memory = 1;
        return 0;
    }
    sprintf(p, "%s%s%s", dir, dir[1] ? "/" : "", name);
    return p;
}

/* how many files and folders are under path (a file: 0) */
static int tree_count(const char *path, int depth)
{
    struct entry *l;
    char *c;
    int n, i, total = 0;
    if (depth >= MAX_DEPTH || (n = read_dir(path, &l, 1 << 30)) < 0) {
        no_memory = 0;
        return 0;
    }
    for (i = 0; i < n; i++) {
        total++;
        if (l[i].dir && (c = child(path, l[i].name)) != 0) {
            total += tree_count(c, depth + 1);
            free(c);
        }
    }
    free_list(l, n);
    return total;
}

/* delete path and, for a folder, everything in it, deepest first; 0, or -1 with errno set
   (the first thing that could not be deleted stops it) */
static int remove_tree(const char *path, int depth)
{
    struct stat st;
    struct entry *l;
    char *c;
    int n, i, bad = 0;
    if (stat(path, &st))
        return -1;
    if (S_ISDIR(st.st_mode)) {
        if (depth >= MAX_DEPTH) {
            errno = ENAMETOOLONG;
            return -1;
        }
        if ((n = read_dir(path, &l, 1 << 30)) < 0)
            return -1;
        for (i = 0; i < n && !bad; i++) {
            c = child(path, l[i].name);
            bad = c == 0 || remove_tree(c, depth + 1);
            if (c)
                free(c);
        }
        free_list(l, n);
        if (bad)
            return -1;
    }
    return remove(path);
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

/* copy a file, or a folder with everything in it; the caller removes what a failed
   copy left (remove_tree). A folder cannot be copied into itself (EINVAL) */
static int copy_tree(const char *src, const char *dst, int depth)
{
    struct stat st;
    struct entry *l;
    char *a, *b;
    int n, i, bad = 0;
    if (stat(src, &st))
        return -1;
    if (!S_ISDIR(st.st_mode))
        return copy_file(src, dst);
    n = strlen(src);
    if (strncmp(dst, src, n) == 0 && (dst[n] == '/' || dst[n] == 0)) {
        errno = EINVAL;
        return -1;
    }
    if (depth >= MAX_DEPTH) {
        errno = ENAMETOOLONG;
        return -1;
    }
    if (mkdir(dst) || (n = read_dir(src, &l, 1 << 30)) < 0)
        return -1;
    for (i = 0; i < n && !bad; i++) {
        a = child(src, l[i].name);
        b = child(dst, l[i].name);
        bad = a == 0 || b == 0 || copy_tree(a, b, depth + 1);
        if (a)
            free(a);
        if (b)
            free(b);
    }
    free_list(l, n);
    return bad ? -1 : 0;
}

/* paste one path here: 0 done, 1 the source is gone (drop it), -1 stop with the message set */
static int paste_one(const char *src, char *name)
{
    char to[PATH_MAX];
    struct stat st;
    strcpy(name, base_of(src));
    if (join(to, cwd, name)) {
        message = "path too long";
        return -1;
    }
    if (stat(to, &st) == 0) {
        say("", name, "already exists here");
        return -1;
    }
    if (stat(src, &st)) {
        fail(src);
        return 1;
    }
    if (clip_cut) {
        if (rename(src, to)) {
            if (errno == EINVAL)
                message = "a folder cannot go inside itself";
            else
                fail(name);
            return -1;
        }
    } else {
        int dir = S_ISDIR(st.st_mode), e;
        if (dir) {
            message = "copying...";                 /* it takes a while: show that now */
            refresh();
        }
        if (copy_tree(src, to, 0)) {
            e = errno;
            if (dir)
                remove_tree(to, 0);                 /* what was copied so far */
            errno = e;
            if (errno == EINVAL)
                message = "a folder cannot go inside itself";
            else
                fail(name);
            update_free();
            return -1;
        }
    }
    return 0;
}

/* paste the whole clipboard; a cut leaves it as the items are moved, a copy keeps it */
static void paste(void)
{
    static int gone[CLIP_MAX];
    char name[NAME_MAX + 1] = "";
    int i, r = 0, done = 0, j = 0;
    if (nclip == 0) {
        message = "nothing to paste (y copy, x cut)";
        return;
    }
    memset(gone, 0, sizeof gone);
    for (i = 0; i < nclip; i++) {
        r = paste_one(clips[i], name);
        if (r < 0)
            break;
        gone[i] = r == 1 || clip_cut;
        done += r == 0;
    }
    for (i = 0; i < nclip; i++)                 /* items that moved or vanished leave the clipboard */
        if (gone[i])
            free(clips[i]);
        else
            clips[j++] = clips[i];
    nclip = j;
    reload(name[0] ? name : 0);
    if (r >= 0 && done)
        say("pasted", done == 1 ? name : "items", "");
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
        clip_rename(path, to);
    } else if (mkdir(to)) {
        fail(input);
        return;
    }
    reload(input);
}

/* delete the selected entries, or the one under the cursor */
static void delete_entry(void)
{
    char path[PATH_MAX];
    int at = cur, i, n = selected(), deleted = 0, bad = 0;
    static char text[24];
    mode = NORMAL;
    message = "deleting...";
    refresh();
    for (i = 0; i < count; i++) {
        if (n ? !list[i].sel : i != cur)
            continue;
        if (join(path, cwd, list[i].name) || remove_tree(path, 0)) {
            bad++;
            fail(list[i].name);
        } else {
            deleted++;
            clip_forget(path);
        }
    }
    reload("");
    cur = at < count ? at : count - 1;
    if (cur < 0)
        cur = 0;
    preview_ok = 0;
    if (!bad) {
        sprintf(text, "deleted %d", deleted);
        message = text;
    }
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

/* the question before a delete: what goes, and how much is inside the folders */
static void ask_delete(void)
{
    char path[PATH_MAX];
    int i, n = selected(), targets = 0, inside = 0;
    for (i = 0; i < count; i++)
        if ((n ? list[i].sel : i == cur) && list[i].dir && join(path, cwd, list[i].name) == 0)
            inside += tree_count(path, 0);
    for (i = 0; i < count; i++)
        targets += n ? list[i].sel : i == cur;
    if (targets > 1)
        snprintf(delete_prompt, sizeof delete_prompt, "delete %d items%s? (y/n)", targets,
                 inside ? " and what is inside" : "");
    else if (inside)
        snprintf(delete_prompt, sizeof delete_prompt, "delete %s + %d inside? (y/n)",
                 list[cur].name, inside);
    else
        snprintf(delete_prompt, sizeof delete_prompt, "delete %s? (y/n)", list[cur].name);
    mode = DELETE;
}

/* copy (cut = 0) or cut the selected entries, or the one under the cursor; the same key
   again on a lone entry that is already on the clipboard takes it off */
static void yank(int cut)
{
    char path[PATH_MAX];
    static char text[32];
    int i, n = selected();
    if (n == 0) {
        if (!cur_path(path)) {
            message = "path too long";
            return;
        }
        if (nclip == 1 && clip_cut == cut && strcmp(clips[0], path) == 0) {
            clip_clear();
            message = "clipboard cleared";
            return;
        }
    }
    clip_clear();
    clip_cut = cut;
    for (i = 0; i < count; i++)
        if ((n ? list[i].sel : i == cur) && join(path, cwd, list[i].name) == 0)
            clip_add(path);
    unselect_all();
    if (no_memory) {
        no_memory = 0;
        message = "out of memory";
        return;
    }
    sprintf(text, "%s %d item%s", cut ? "cut" : "copied", nclip, nclip == 1 ? "" : "s");
    message = text;
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
        message = "hjkl move  space select  y x p  r d a  u ~ q";
    else if (count == 0 && (k == 'y' || k == 'x' || k == 'r' || k == 'd'))
        message = "nothing here";
    else if (k == ' ') {                        /* select it and go down, as yazi does */
        if (count) {
            list[cur].sel ^= 1;
            move_to(cur + 1);
        }
    } else if (k == 'y' || k == 'x')
        yank(k == 'x');
    else if (k == 'u' || k == KEY_CTRL('g')) {   /* forget the selection and the clipboard */
        unselect_all();
        clip_clear();
        message = "selection and clipboard cleared";
    } else if (k == '~')
        go_to(HOME);
    else if (k == 'p')
        paste();
    else if (k == 'r')
        start_input(RENAME);
    else if (k == 'a')
        start_input(MKDIR);
    else if (k == 'd')
        ask_delete();
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
    if (argc > 4 || (argc == 4 && strcmp(argv[3], "clip") != 0)) {
        printf("usage: visual_file_manager [dir [name]]\n");
        return 1;
    }
    getcwd(cwd, sizeof cwd);
    if (argc > 1 && chdir(argv[1]) == 0)
        getcwd(cwd, sizeof cwd);
    else if (argc > 1) {
        printf("visual_file_manager: %s: %s\n", argv[1], strerror(errno));
        return 1;
    }
    else if (chdir(HOME) == 0)                  /* no argument: the home folder, if there is one */
        getcwd(cwd, sizeof cwd);
    if (argc == 4)
        load_clip();
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
