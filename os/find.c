/* find.c - list the files and folders whose names contain some text (a program
 * for Tynix, in /bin)
 *
 *   python os/make_disk.py                 (builds it into /bin)
 *   (in the shell)   find [dir] text
 *
 * Every path under dir (default `.`, all the subfolders too, dir itself not
 * listed) whose last name contains text, one per line, a folder with a `/`
 * after it. text is plain text, capitals matter. The paths start with dir as
 * it was typed (`.` gives ./docs/a.txt, `/` gives /docs/a.txt).
 *
 * Errors: find: PATH: reason, the rest goes on, exit status 1.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>

#define PATH_MAX 512

struct entry {
    char *name;
    int dir;
};

static const char *needle;
static int failed;

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
        printf("find: %s: %s\n", dir, strerror(errno));
        failed = 1;
        return;
    }
    for (i = 0; i < n; i++) {
        if (len + strlen(list[i].name) + 2 > PATH_MAX) {
            printf("find: %s/%s: %s\n", dir, list[i].name, strerror(ENAMETOOLONG));
            failed = 1;
        } else {
            sprintf(sub, "%s%s%s", dir, len && dir[len - 1] == '/' ? "" : "/", list[i].name);
            if (strstr(list[i].name, needle))
                printf("%s%s\n", sub, list[i].dir ? "/" : "");
            if (list[i].dir)
                walk(sub);
        }
        free(list[i].name);
    }
    free(list);
}

int main(int argc, char **argv)
{
    if (argc != 2 && argc != 3) {
        printf("usage: find [dir] text\n");
        return 1;
    }
    needle = argv[argc - 1];
    walk(argc == 3 ? argv[1] : ".");
    return failed;
}
