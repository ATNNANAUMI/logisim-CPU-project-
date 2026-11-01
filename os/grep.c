/* grep.c - print the lines that contain some text (a program for Tynix, in /bin)
 *
 *   python os/make_disk.py                 (builds it into /bin)
 *   (in the shell)   grep [-i] [-n] [-v] text [path...]
 *
 * text is plain text, not a regular expression. -i ignores case, -n puts the
 * line number before each line, -v prints the lines that do NOT contain
 * text. Flags may be joined (-in). A directory is searched file by file
 * through all its subfolders; its binary files (programs) are skipped, but a
 * binary file named on the command line is an error. With several paths,
 * or a directory, each line starts with `path:` (then `N:` with -n). With no
 * path it reads the keyboard up to Ctrl-D.
 *
 * Exit status: 0 if a line was printed, 1 if none, 2 on an error (a path
 * that can't be read: `grep: PATH: reason`; the other paths go on).
 * A line can be any length; a last line without a newline counts as a line.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include <dirent.h>
#include <sys/stat.h>

#define PATH_MAX 512

struct entry {
    char *name;
    int dir;
};

static int ignore_case, numbers, invert;
static int prefix;              /* lines start with the path */
static int matched, failed;
static char *needle;

static void lower(char *s)
{
    for (; *s; s++)
        *s = tolower(*s);
}

static int no_memory(const char *name)
{
    printf("grep: %s: %s\n", name, "out of memory");
    failed = 1;
    return 0;
}

/* the lines of the open file f, named name; 0 if memory ran out */
static int search(FILE *f, const char *name)
{
    char *line = malloc(128), *copy = 0;
    int cap = 128, n, c, number = 0, hit, ok = 1;
    if (line == 0)
        return no_memory(name);
    for (;;) {
        n = 0;
        while ((c = fgetc(f)) != EOF && c != '\n') {
            if (n + 1 >= cap) {
                char *bigger = realloc(line, cap + 128);
                if (bigger == 0) {
                    ok = no_memory(name);
                    goto done;
                }
                line = bigger;
                cap += 128;
            }
            line[n++] = c;
        }
        if (c == EOF && n == 0)
            break;
        line[n] = 0;
        number++;
        if (ignore_case) {
            free(copy);
            if ((copy = malloc(n + 1)) == 0) {
                ok = no_memory(name);
                goto done;
            }
            strcpy(copy, line);
            lower(copy);
            hit = strstr(copy, needle) != 0;
        } else
            hit = strstr(line, needle) != 0;
        if (hit != invert) {
            matched = 1;
            if (prefix)
                printf("%s:", name);
            if (numbers)
                printf("%d:", number);
            printf("%s\n", line);
        }
        if (c == EOF)
            break;
    }
done:
    free(line);
    free(copy);
    return ok;
}

/* one file; named: it was on the command line (a binary one is an error),
   else it was found in a directory (a binary one is skipped) */
static void file(const char *name, int named)
{
    struct stat st;
    FILE *f;
    if (stat(name, &st)) {
        printf("grep: %s: %s\n", name, strerror(errno));
        failed = 1;
        return;
    }
    if (!S_ISTEXT(st.st_mode)) {
        if (named) {
            printf("grep: %s: not a text file\n", name);
            failed = 1;
        }
        return;
    }
    if ((f = fopen(name, "r")) == 0) {
        printf("grep: %s: %s\n", name, strerror(errno));
        failed = 1;
        return;
    }
    search(f, name);
    fclose(f);
}

/* the entries of directory dir, copied, so that it can be closed before the
   subfolders are opened (only 4 directories can be open at once); -1 with
   errno set if it can't be read */
static int entries(const char *dir, struct entry **list)
{
    DIR *d = opendir(dir);
    struct dirent *e;
    struct entry *l = 0, *bigger;
    int n = 0, room = 0;
    if (d == 0)
        return -1;
    while ((e = readdir(d))) {
        if (n == room) {
            if ((bigger = realloc(l, (room + 16) * sizeof *l)) == 0)
                break;
            l = bigger;
            room += 16;
        }
        if ((l[n].name = malloc(strlen(e->d_name) + 1)) == 0)
            break;
        strcpy(l[n].name, e->d_name);
        l[n++].dir = e->d_type == DT_DIR;
    }
    closedir(d);
    *list = l;
    return n;
}

static void walk(const char *dir)
{
    struct entry *list;
    char sub[PATH_MAX];
    int n = entries(dir, &list), i, len = strlen(dir);
    if (n < 0) {
        printf("grep: %s: %s\n", dir, strerror(errno));
        failed = 1;
        return;
    }
    for (i = 0; i < n; i++) {
        if (len + strlen(list[i].name) + 2 > PATH_MAX) {
            printf("grep: %s/%s: %s\n", dir, list[i].name, strerror(ENAMETOOLONG));
            failed = 1;
        } else {
            sprintf(sub, "%s%s%s", dir, len && dir[len - 1] == '/' ? "" : "/", list[i].name);
            if (list[i].dir)
                walk(sub);
            else
                file(sub, 0);
        }
        free(list[i].name);
    }
    free(list);
}

int main(int argc, char **argv)
{
    int i = 1, paths;
    struct stat st;
    while (i < argc && argv[i][0] == '-' && argv[i][1]) {
        const char *f;
        for (f = argv[i] + 1; *f; f++) {
            if (*f == 'i')
                ignore_case = 1;
            else if (*f == 'n')
                numbers = 1;
            else if (*f == 'v')
                invert = 1;
            else {
                printf("usage: grep [-i] [-n] [-v] text [path...]\n");
                return 1;
            }
        }
        i++;
    }
    if (i >= argc) {
        printf("usage: grep [-i] [-n] [-v] text [path...]\n");
        return 1;
    }
    needle = argv[i++];
    if (ignore_case)
        lower(needle);
    paths = argc - i;
    if (paths == 0) {
        search(stdin, "");
        clearerr(stdin);
        return failed ? 2 : !matched;
    }
    prefix = paths > 1;
    for (; i < argc; i++) {
        if (stat(argv[i], &st) == 0 && S_ISDIR(st.st_mode)) {
            prefix = 1;
            walk(argv[i]);
        } else
            file(argv[i], 1);
    }
    return failed ? 2 : !matched;
}
