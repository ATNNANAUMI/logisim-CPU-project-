/* diff.c - the lines that differ between two text files (a program for Tynix,
 * in /bin)
 *
 *   python tynix/make_disk.py              (builds it into /bin)
 *   (in the shell)   diff from to
 *
 * Unix's normal format: a header like 2c2 (line 2 of `from` was changed to
 * line 2 of `to`), 5a6 (after line 5 of `from`, line 6 of `to` was added) or
 * 3d2 (line 3 of `from` was deleted; `to` is at line 2 there), then the lines:
 * `< ` the old ones, `---` between old and new when both exist, `> ` the new.
 * Ranges are N or N,M.
 *
 * It finds a longest common subsequence of the lines, with a table of
 * (lines + 1) x (lines + 1) words: both files may have at most 1000 lines,
 * bigger ones are refused with a message, never cut. Lines the files share at
 * the start and the end are skipped first, so the table only covers the
 * middle. A missing newline at the end of a file is not reported (the last
 * line counts as a line).
 *
 * Exit status: 0 the same, 1 different, 2 an error (`diff: PATH: reason`,
 * a binary file, too many lines, out of memory).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>

#define MAX_LINES 1000

struct text {
    char **line;                /* line[0 .. n-1], malloc'd */
    unsigned *hash;
    int n;
};

static struct text a, b;
static unsigned *table;

static unsigned hash_of(const char *s)
{
    unsigned h = 5381;
    for (; *s; s++)
        h = h * 33 + *s;
    return h;
}

/* the lines of the file at path into t; 0, or -1 after printing why not */
static int load(const char *path, struct text *t)
{
    struct stat st;
    FILE *f;
    char *buf = malloc(128), *bigger;
    int cap = 128, len, c;
    if (stat(path, &st)) {
        printf("diff: %s: %s\n", path, strerror(errno));
        return -1;
    }
    if (!S_ISREG(st.st_mode) || !S_ISTEXT(st.st_mode)) {
        printf("diff: %s: not a text file\n", path);
        return -1;
    }
    if ((f = fopen(path, "r")) == 0) {
        printf("diff: %s: %s\n", path, strerror(errno));
        return -1;
    }
    t->line = malloc(MAX_LINES * sizeof(char *));
    t->hash = malloc(MAX_LINES * sizeof(unsigned));
    if (buf == 0 || t->line == 0 || t->hash == 0) {
        printf("diff: %s: out of memory\n", path);
        return -1;
    }
    for (;;) {
        len = 0;
        while ((c = fgetc(f)) != EOF && c != '\n') {
            if (len + 1 >= cap) {
                if ((bigger = realloc(buf, cap + 128)) == 0) {
                    printf("diff: %s: out of memory\n", path);
                    return -1;
                }
                buf = bigger;
                cap += 128;
            }
            buf[len++] = c;
        }
        if (c == EOF && len == 0)
            break;
        if (t->n == MAX_LINES) {
            printf("diff: %s: more than %d lines, too big to compare\n", path, MAX_LINES);
            return -1;
        }
        buf[len] = 0;
        if ((t->line[t->n] = malloc(len + 1)) == 0) {
            printf("diff: %s: out of memory\n", path);
            return -1;
        }
        strcpy(t->line[t->n], buf);
        t->hash[t->n++] = hash_of(buf);
        if (c == EOF)
            break;
    }
    fclose(f);
    free(buf);
    return 0;
}

static int same(int i, int j)
{
    return a.hash[i] == b.hash[j] && strcmp(a.line[i], b.line[j]) == 0;
}

/* "N" or "N,M" for the 1-based lines first..last */
static void range(int first, int last)
{
    if (first == last)
        printf("%d", first);
    else
        printf("%d,%d", first, last);
}

int main(int argc, char **argv)
{
    int prefix = 0, suffix, na, nb, w, i, j, ai, bj, differ = 0, k;
    if (argc != 3) {
        printf("usage: diff from to\n");
        return 1;
    }
    if (load(argv[1], &a) || load(argv[2], &b))
        return 2;
    while (prefix < a.n && prefix < b.n && same(prefix, prefix))
        prefix++;
    suffix = 0;
    while (suffix < a.n - prefix && suffix < b.n - prefix
           && same(a.n - 1 - suffix, b.n - 1 - suffix))
        suffix++;
    na = a.n - prefix - suffix;         /* the middle: a[prefix .. prefix+na-1] */
    nb = b.n - prefix - suffix;
    w = nb + 1;
    table = calloc((na + 1) * w, sizeof(unsigned));
    if (table == 0) {
        printf("diff: out of memory\n");
        return 2;
    }
    /* table[i * w + j]: the longest common subsequence of a[i ..] and b[j ..] */
    for (i = na - 1; i >= 0; i--)
        for (j = nb - 1; j >= 0; j--) {
            if (same(prefix + i, prefix + j))
                table[i * w + j] = table[(i + 1) * w + j + 1] + 1;
            else if (table[(i + 1) * w + j] >= table[i * w + j + 1])
                table[i * w + j] = table[(i + 1) * w + j];
            else
                table[i * w + j] = table[i * w + j + 1];
        }
    i = j = 0;
    while (i < na || j < nb) {
        if (i < na && j < nb && same(prefix + i, prefix + j)) {
            i++;
            j++;
            continue;
        }
        ai = i;                         /* a hunk: lines a[ai .. i-1] became b[bj .. j-1] */
        bj = j;
        while (i < na || j < nb) {
            if (i < na && j < nb && same(prefix + i, prefix + j))
                break;
            if (j >= nb || (i < na && table[(i + 1) * w + j] >= table[i * w + j + 1]))
                i++;
            else
                j++;
        }
        differ = 1;
        if (i > ai && j > bj) {
            range(prefix + ai + 1, prefix + i);
            printf("c");
            range(prefix + bj + 1, prefix + j);
        } else if (i > ai) {
            range(prefix + ai + 1, prefix + i);
            printf("d%d", prefix + bj);
        } else {
            printf("%da", prefix + ai);
            range(prefix + bj + 1, prefix + j);
        }
        printf("\n");
        for (k = ai; k < i; k++)
            printf("< %s\n", a.line[prefix + k]);
        if (i > ai && j > bj)
            printf("---\n");
        for (k = bj; k < j; k++)
            printf("> %s\n", b.line[prefix + k]);
    }
    return differ;
}
