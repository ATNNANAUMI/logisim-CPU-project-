/* more.c - show text files a page at a time (a program for Tynix, in /bin)
 *
 *   python os/make_disk.py                 (builds it into /bin)
 *   (in the shell)   more [-n N] file...
 *
 * Shows N lines (default PAGE_LINES), then the prompt
 *   --more-- (space: page, Enter: line, q: quit)
 * and waits for one key (wait_key(): no echo, no Enter needed): space shows
 * the next page, Enter one more line, q stops (so does Ctrl-D, Tynix's
 * end of input). With several files each starts under a "::::: name" line.
 * When stdout goes to a file (`more a.txt > b.txt`) it only copies the
 * files, no prompt. A binary file (a program) is refused.
 *
 * PAGE_LINES is a guess: the circuit's TTY has cols=64 and no rows
 * attribute, so Logisim's default of 8 rows applies, and 7 lines plus the
 * prompt fill it. A line longer than 64 chars wraps and counts for every
 * row it takes. -n overrides the number.
 *
 * Errors: more: PATH: reason, the other files go on, exit status 1.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include <cpu.h>

#define PAGE_LINES 7            /* a guess, see above */
#define WIDTH 64                /* the text display's columns */

static int page = PAGE_LINES;
static int tty;                 /* stdout is the display: prompt between pages */
static int rows;                /* rows shown since the last prompt */
static int col;                 /* where the cursor is on its row */
static int quit;

/* the prompt; true to go on, false to quit. Space: a page, Enter: a line */
static int ask(void)
{
    int k;
    printf("--more-- (space: page, Enter: line, q: quit)");
    do
        k = wait_key();
    while (k != ' ' && k != '\n' && k != 'q' && k != 'Q' && k != 4);
    printf("\n");
    col = 0;
    if (k == 'q' || k == 'Q' || k == 4)
        return 0;
    rows = k == '\n' ? page - 1 : 0;
    return 1;
}

/* one char out; on the display a full page stops first at the prompt.
   Returns 0 when the reader quit */
static int emit(int c)
{
    if (tty && c != '\n' && col == WIDTH) {            /* the row is full: it wraps */
        rows++;
        col = 0;
    }
    if (tty && rows >= page && !ask())
        return 0;
    putchar(c);
    if (c == '\n') {
        col = 0;
        rows++;
    } else
        col++;
    return 1;
}

static int show(const char *name, int heading)
{
    struct stat st;
    FILE *f;
    int c;
    const char *p;
    if (stat(name, &st)) {
        printf("more: %s: %s\n", name, strerror(errno));
        return 1;
    }
    if (!S_ISREG(st.st_mode) || !S_ISTEXT(st.st_mode)) {
        printf("more: %s: not a text file\n", name);
        return 1;
    }
    if ((f = fopen(name, "r")) == 0) {
        printf("more: %s: %s\n", name, strerror(errno));
        return 1;
    }
    if (heading && tty) {
        if (col > 0)
            emit('\n');
        for (p = "::::: "; *p && !quit; p++)
            quit = !emit(*p);
        for (p = name; *p && !quit; p++)
            quit = !emit(*p);
        if (!quit)
            quit = !emit('\n');
    }
    while (!quit && (c = fgetc(f)) != EOF)
        quit = !emit(c);
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    int i = 1, status = 0, files;
    if (argc > 2 && strcmp(argv[1], "-n") == 0) {
        char *end;
        page = strtol(argv[2], &end, 10);
        if (*end || end == argv[2] || page < 1) {
            printf("more: -n needs a number of lines, 1 or more\n");
            return 1;
        }
        i = 3;
    }
    if (i >= argc) {
        printf("usage: more [-n N] file...\n");
        return 1;
    }
    tty = isatty(1);
    files = argc - i;
    for (; i < argc && !quit; i++)
        status |= show(argv[i], files > 1);
    if (tty && col > 0)
        printf("\n");
    return status;
}
