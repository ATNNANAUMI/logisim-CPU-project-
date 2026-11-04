/* dir.c for a program for Tynix: mkdir, rmdir, chdir, getcwd and
 * opendir/readdir/closedir through the kernel (the directories are its;
 * each program has its own current directory there). */
#include <dirent.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
#include <sys/tynix.h>
#include "../local.h"

#define MAX_DIRS 4

struct _DIR {
    int fd;
    struct dirent entry;
};

int _tx_call(int n, int a, int b, int c, int d);       /* sys.c */

static DIR dirs[MAX_DIRS];
static int dir_used[MAX_DIRS];

int mkdir(const char *path, ...)
{
    return _tx_call(SYS_MKDIR, (int)path, 0, 0, 0);
}

int rmdir(const char *path)
{
    return _tx_call(SYS_RMDIR, (int)path, 0, 0, 0);
}

int chdir(const char *path)
{
    return _tx_call(SYS_CHDIR, (int)path, 0, 0, 0);
}

char *getcwd(char *buf, size_t size)
{
    return _tx_call(SYS_GETCWD, (int)buf, size, 0, 0) ? 0 : buf;
}

DIR *opendir(const char *path)
{
    int i, fd;
    for (i = 0; i < MAX_DIRS && dir_used[i]; i++)
        ;
    if (i == MAX_DIRS) {
        errno = EMFILE;
        return 0;
    }
    if ((fd = _tx_call(SYS_OPENDIR, (int)path, 0, 0, 0)) < 0)
        return 0;
    dir_used[i] = 1;
    dirs[i].fd = fd;
    return &dirs[i];
}

struct dirent *readdir(DIR *dir)
{
    return _tx_call(SYS_READDIR, dir->fd, (int)&dir->entry, 0, 0) > 0 ? &dir->entry : 0;
}

int closedir(DIR *dir)
{
    int i;
    for (i = 0; i < MAX_DIRS; i++)
        if (dir == &dirs[i] && dir_used[i]) {
            dir_used[i] = 0;
            _tx_call(SYS_CLOSE, dir->fd, 0, 0, 0);
        }
    return 0;
}
