/* ed.c - a line editor for text files (a program for Tynix, in /bin)
 *
 *   python os/make_disk.py                 (builds it into /bin)
 *   (in the shell)   ed notes.txt
 *
 * Like Unix's ed, but the errors say what is wrong. The text is held in
 * memory a line at a time; nothing reaches the disk until `w`. A missing
 * file starts empty and is made by `w`; a binary file (a program) is refused.
 *
 *   p [range]          print lines with their numbers (no range: all)
 *   n                  line number of the current line and the line count
 *   a [n], i [n]       add lines after / before line n (default: the current
 *                      line); type them, end with a line holding only "."
 *   c [range]          replace the lines with typed ones (same ending)
 *   d [range]          delete the lines
 *   s [range]/old/new/ replace the first old in each line by new (any char
 *                      can stand for the / ); old is plain text
 *   /text              the next line with text in it (wraps round)
 *   N                  a bare number: go to that line and print it
 *   w [file]           save (to file, which then becomes the name); prints
 *                      the number of chars
 *   q                  quit; with unsaved changes it warns, and a second q quits
 *   h                  this list
 *
 * A range is N, N,M, `.` (the current line) or `$` (the last); `,` alone is
 * the whole text. Ctrl-D at the prompt quits like q. Lines are at most 255
 * chars. The current line is the last one printed, added or changed.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <sys/stat.h>

#define LINE_MAX 256

static char **text;             /* text[0 .. count-1]: the lines, malloc'd */
static int count, room;
static int cur;                 /* the current line, 1-based; 0 when empty */
static int dirty, warned;       /* unsaved changes; the quit warning was given */
static char name[256];
static char line[LINE_MAX];
static int from, to;            /* the range of the command being run */

static void help(void)
{
    printf("p [range]  print     n  where am I   a/i [n]  add after/before, end with .\n"
           "c [range]  replace   d [range]  delete   s[range]/old/new/  substitute\n"
           "/text  find   N  go to line N   w [file]  save   q  quit   h  this\n"
           "range: N  N,M  .  $  , (all)\n");
}

/* the line is [s] with its newline cut; 0 at end of input (Ctrl-D) */
static char *get(const char *prompt)
{
    char *nl;
    printf("%s", prompt);
    if (fgets(line, sizeof line, stdin) == 0)
        return 0;
    if ((nl = strchr(line, '\n')))
        *nl = 0;
    return line;
}

/* open a gap of n lines at index at (0-based) */
static int make_room(int at, int n)
{
    if (count + n > room) {
        char **bigger = realloc(text, (count + n + 64) * sizeof(char *));
        if (bigger == 0) {
            printf("out of memory\n");
            return -1;
        }
        text = bigger;
        room = count + n + 64;
    }
    memmove(text + at + n, text + at, (count - at) * sizeof(char *));
    count += n;
    return 0;
}

static int put_line(int at, const char *s)
{
    char *copy;
    if (make_room(at, 1))
        return -1;
    if ((copy = malloc(strlen(s) + 1)) == 0) {
        memmove(text + at, text + at + 1, (count - at - 1) * sizeof(char *));
        count--;
        printf("out of memory\n");
        return -1;
    }
    strcpy(copy, s);
    text[at] = copy;
    return 0;
}

static void drop(int first, int last)           /* 1-based, inclusive */
{
    int i;
    for (i = first - 1; i < last; i++)
        free(text[i]);
    memmove(text + first - 1, text + last, (count - last) * sizeof(char *));
    count -= last - first + 1;
}

static int load(const char *file)
{
    struct stat st;
    FILE *f;
    int c, n = 0, chars = 0;
    if (stat(file, &st)) {
        if (errno != ENOENT) {
            printf("%s: %s\n", file, strerror(errno));
            return -1;
        }
        printf("%s: new file\n", file);
        return 0;
    }
    if (!S_ISREG(st.st_mode) || !S_ISTEXT(st.st_mode)) {
        printf("%s: not a text file\n", file);
        return -1;
    }
    if ((f = fopen(file, "r")) == 0) {
        printf("%s: %s\n", file, strerror(errno));
        return -1;
    }
    while ((c = fgetc(f)) != EOF) {
        chars++;
        if (c == '\n' || n == LINE_MAX - 1) {
            line[n] = 0;
            if (put_line(count, line)) {
                fclose(f);
                return -1;
            }
            n = 0;
            if (c == '\n')
                continue;
        }
        line[n++] = c;
    }
    if (n) {                                    /* last line without a newline */
        line[n] = 0;
        put_line(count, line);
    }
    fclose(f);
    cur = count;
    printf("%d chars, %d lines\n", chars, count);
    return 0;
}

static int save(const char *file)
{
    FILE *f = fopen(file, "w");
    int i, chars = 0;
    if (f == 0) {
        printf("%s: %s\n", file, strerror(errno));
        return -1;
    }
    for (i = 0; i < count; i++) {
        fputs(text[i], f);
        fputc('\n', f);
        chars += strlen(text[i]) + 1;
    }
    if (fclose(f) || ferror(f)) {
        printf("%s: could not write it (disk full?)\n", file);
        return -1;
    }
    printf("%d chars\n", chars);
    dirty = warned = 0;
    return 0;
}

/* one address at *s: N . $ ; -1 if none there, -2 if out of range */
static int address(char **s)
{
    char *p = *s;
    int n;
    if (*p == '.') {
        n = cur;
        p++;
    } else if (*p == '$') {
        n = count;
        p++;
    } else if (isdigit(*p)) {
        n = 0;
        while (isdigit(*p))
            n = n * 10 + *p++ - '0';
    } else
        return -1;
    *s = p;
    return n;
}

/* the range before the command: sets from and to; returns 1 if the line
   had one, 0 if from and to are the defaults */
static int range(char **s, int dfrom, int dto)
{
    char *p = *s;
    int a, b, had = 1;
    from = dfrom;
    to = dto;
    while (*p == ' ')
        p++;
    if (*p == ',') {                            /* , alone: everything */
        p++;
        from = 1;
        to = count;
        if ((b = address(&p)) >= 0)
            to = b;
    } else if ((a = address(&p)) >= 0) {
        from = to = a;
        if (*p == ',') {
            p++;
            to = count;
            if ((b = address(&p)) >= 0)
                to = b;
        }
    } else
        had = 0;
    *s = p;
    return had;
}

static int check(int allow_zero)
{
    if (from > to || from < (allow_zero ? 0 : 1) || to > count) {
        printf("no such line (the text has %d)\n", count);
        return -1;
    }
    return 0;
}

static void show(int first, int last)
{
    int i;
    for (i = first; i <= last; i++)
        printf("%4d  %s\n", i, text[i - 1]);
    cur = last;
}

/* typed lines up to "." go in before index at (0-based) */
static void input(int at)
{
    char *s;
    int n = 0;
    while ((s = get("")) && strcmp(s, ".") != 0) {
        if (put_line(at + n, s))
            break;
        n++;
    }
    if (s == 0)
        clearerr(stdin);
    if (n) {
        cur = at + n;
        dirty = 1;
        warned = 0;
    }
}

/* s/old/new/ at p (p points at the delimiter) over from..to */
static void substitute(char *p)
{
    char delim = *p++, *old = p, *new, *end, *hit;
    int i, changed = 0, olen;
    if (!(new = strchr(old, delim))) {
        printf("usage: s/old/new/\n");
        return;
    }
    *new++ = 0;
    if ((end = strchr(new, delim)))
        *end = 0;
    olen = strlen(old);
    if (olen == 0) {
        printf("s: old text is empty\n");
        return;
    }
    if (check(0))
        return;
    for (i = from; i <= to; i++) {
        char *l = text[i - 1], *copy;
        if (!(hit = strstr(l, old)))
            continue;
        if (strlen(l) - olen + strlen(new) >= LINE_MAX) {
            printf("line %d would be too long\n", i);
            continue;
        }
        copy = malloc(strlen(l) - olen + strlen(new) + 1);
        if (copy == 0) {
            printf("out of memory\n");
            return;
        }
        memcpy(copy, l, hit - l);
        strcpy(copy + (hit - l), new);
        strcpy(copy + (hit - l) + strlen(new), hit + olen);
        free(l);
        text[i - 1] = copy;
        cur = i;
        changed++;
    }
    if (changed) {
        dirty = 1;
        warned = 0;
        show(cur, cur);
    } else
        printf("not found: %s\n", old);
}

/* one command line; 1 to quit */
static int command(char *s)
{
    char *p = s;
    char cmd;
    int i, had;
    while (*p == ' ')
        p++;
    if (*p == '/') {                            /* /text: find */
        p++;
        for (i = 1; i <= count; i++) {
            int at = (cur - 1 + i) % count + 1;
            if (strstr(text[at - 1], p)) {
                show(at, at);
                return 0;
            }
        }
        printf("not found: %s\n", p);
        return 0;
    }
    had = range(&p, cur, cur);
    while (*p == ' ')
        p++;
    cmd = *p++;
    while (*p == ' ')
        p++;
    switch (cmd) {
    case 0:                                     /* a bare number: go there */
        if (had && !check(0))
            show(to, to);
        break;
    case 'p':
        if (!had)
            from = 1, to = count;
        if (count == 0)
            printf("the text is empty\n");
        else if (!check(0))
            show(from, to);
        break;
    case 'n':
        printf("line %d of %d%s%s\n", cur, count, name[0] ? ", file " : "", name);
        break;
    case 'a':
    case 'i':
        if (!check(1))
            input(cmd == 'a' ? to : (to > 0 ? to - 1 : 0));
        break;
    case 'c':
        if (check(0))
            break;
        drop(from, to);
        input(from - 1);
        dirty = 1;
        break;
    case 'd':
        if (count == 0)
            printf("the text is empty\n");
        else if (!check(0)) {
            drop(from, to);
            cur = from <= count ? from : count;
            dirty = 1;
            warned = 0;
        }
        break;
    case 's':
        substitute(p);
        break;
    case 'w':
        if (*p) {
            if (save(p) == 0)
                strcpy(name, p);
        } else if (!name[0])
            printf("w: no file name (w FILE)\n");
        else
            save(name);
        break;
    case 'q':
        if (dirty && !warned) {
            printf("unsaved changes (w saves, q again quits)\n");
            warned = 1;
            return 0;
        }
        return 1;
    case 'h':
    case '?':
        help();
        break;
    default:
        printf("unknown command '%c' (h lists them)\n", cmd);
    }
    return 0;
}

int main(int argc, char **argv)
{
    char *s;
    if (argc > 2) {
        printf("usage: ed [file]\n");
        return 1;
    }
    if (argc == 2) {
        if (strlen(argv[1]) >= sizeof name) {
            printf("%s: name too long\n", argv[1]);
            return 1;
        }
        strcpy(name, argv[1]);
        if (load(name))
            return 1;
    } else
        printf("ed: h lists the commands\n");
    for (;;) {
        s = get("*");
        if (s == 0) {                           /* Ctrl-D: quit, like q */
            clearerr(stdin);
            if (dirty && !warned) {
                printf("\nunsaved changes (w saves, Ctrl-D again quits)\n");
                warned = 1;
                continue;
            }
            printf("\n");
            break;
        }
        if (command(s))
            break;
    }
    return 0;
}
