/* du.c - how much disk space folders and files take (a program for Tynix, in /bin)
 *
 *   python os/make_disk.py                 (builds it into /bin)
 *   (in the shell)   du [-a] [path...]
 *
 * Sizes are in disk KB, like `du -k`: one block (256 words) is 1 KB. A text
 * file holds 4 chars a word, so 1024 chars fit in a block; a program takes a
 * block for every 256 words; an empty file takes none. A folder takes its own
 * directory file too (132 words an entry) plus everything under it. One line
 * per folder, the subfolders first and the folder itself last, so the total
 * is the last line of each path. -a adds a line for every file. A file as
 * the path gets one line. The path defaults to `.`.
 *
 * Errors: du: PATH: reason, the rest goes on, exit status 1.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <sys/stat.h>

#define PATH_MAX 512

static int all, failed;

/* the names in directory dir, copied, so that it can be closed before the
   subfolders are opened (only 4 directories can be open at once); -1 with
   errno set if it can't be read */
static int names(const char *dir, char ***list)
{
    DIR *d = opendir(dir);
    struct dirent *e;
    char **l = 0, **bigger;
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
        if ((l[n] = malloc(strlen(e->d_name) + 1)) == 0)
            break;
        strcpy(l[n++], e->d_name);
    }
    closedir(d);
    *list = l;
    return n;
}

/* the KB under path (a file or a folder), printing the lines; top: it was on
   the command line, so a failed stat is its own error */
static unsigned size(const char *path)
{
    struct stat st;
    unsigned total;
    if (stat(path, &st)) {
        printf("du: %s: %s\n", path, strerror(errno));
        failed = 1;
        return 0;
    }
    total = st.st_blocks;
    if (S_ISDIR(st.st_mode)) {
        char **list, sub[PATH_MAX];
        int n = names(path, &list), i, len = strlen(path);
        if (n < 0) {
            printf("du: %s: %s\n", path, strerror(errno));
            failed = 1;
        }
        for (i = 0; i < n; i++) {
            if (len + strlen(list[i]) + 2 > PATH_MAX) {
                printf("du: %s/%s: %s\n", path, list[i], strerror(ENAMETOOLONG));
                failed = 1;
            } else {
                sprintf(sub, "%s%s%s", path, len && path[len - 1] == '/' ? "" : "/", list[i]);
                total += size(sub);
            }
            free(list[i]);
        }
        if (n >= 0)
            free(list);
    }
    if (S_ISDIR(st.st_mode) || all)
        printf("%-6u %s\n", total, path);
    return total;
}

int main(int argc, char **argv)
{
    int i = 1;
    struct stat st;
    if (i < argc && strcmp(argv[i], "-a") == 0) {
        all = 1;
        i++;
    }
    if (i == argc) {
        size(".");
        return failed;
    }
    for (; i < argc; i++) {
        if (stat(argv[i], &st) == 0 && !S_ISDIR(st.st_mode)) {
            printf("%-6u %s\n", st.st_blocks, argv[i]);
        } else
            size(argv[i]);
    }
    return failed;
}
