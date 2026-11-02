/* tree.c - show a folder and everything in it as a tree (a program for Tynix,
 * in /bin)
 *
 *   python os/make_disk.py                 (builds it into /bin)
 *   (in the shell)   tree [-s] [dir]
 *
 *   /docs
 *   |-- a.txt
 *   |-- sub
 *   |   `-- c.txt
 *   `-- b.txt
 *   1 directory, 3 files
 *
 * dir defaults to `.`. -s puts the size before each name, in brackets: chars
 * for a text file, words for a program, <dir> for a folder (as `ls -l`).
 * The last line counts what is under dir, not dir itself. Names are in the
 * order the disk keeps them. Plain ASCII, so it fits the text display.
 *
 * Errors: tree: PATH: reason, exit status 1.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>

#define PATH_MAX 512
#define INDENT_MAX 256

struct entry {
    char *name;
    int dir;
    unsigned size;
};

static int sizes;
static int dirs, files, failed;
static char indent[INDENT_MAX];

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
        l[n].dir = e->d_type == DT_DIR;
        l[n++].size = e->d_size;
    }
    closedir(d);
    *list = l;
    return n;
}

static void walk(const char *dir)
{
    struct entry *list;
    char sub[PATH_MAX];
    int n = entries(dir, &list), i, len = strlen(dir), depth = strlen(indent);
    if (n < 0) {
        printf("tree: %s: %s\n", dir, strerror(errno));
        failed = 1;
        return;
    }
    for (i = 0; i < n; i++) {
        int last = i == n - 1;
        printf("%s%s", indent, last ? "`-- " : "|-- ");
        if (sizes) {
            if (list[i].dir)
                printf("[   <dir>]  ");
            else
                printf("[%8u]  ", list[i].size);
        }
        printf("%s\n", list[i].name);
        if (list[i].dir) {
            dirs++;
            if (len + strlen(list[i].name) + 2 > PATH_MAX || depth + 4 >= INDENT_MAX) {
                printf("%s    (too deep)\n", indent);
            } else {
                sprintf(sub, "%s%s%s", dir, len && dir[len - 1] == '/' ? "" : "/", list[i].name);
                strcat(indent, last ? "    " : "|   ");
                walk(sub);
                indent[depth] = 0;
            }
        } else
            files++;
        free(list[i].name);
    }
    free(list);
}

int main(int argc, char **argv)
{
    int i = 1;
    DIR *d;
    const char *root = ".";
    if (i < argc && strcmp(argv[i], "-s") == 0) {
        sizes = 1;
        i++;
    }
    if (argc - i > 1) {
        printf("usage: tree [-s] [dir]\n");
        return 1;
    }
    if (i < argc)
        root = argv[i];
    if ((d = opendir(root)) == 0) {             /* before printing anything */
        printf("tree: %s: %s\n", root, strerror(errno));
        return 1;
    }
    closedir(d);
    printf("%s\n", root);
    walk(root);
    if (failed)
        return 1;
    printf("%d director%s, %d file%s\n", dirs, dirs == 1 ? "y" : "ies", files, files == 1 ? "" : "s");
    return 0;
}
