/* dir.c - directories on the disk: mkdir, rmdir, chdir, getcwd, and
 * opendir/readdir/closedir. The filesystem itself is in fs.c. */
#include <dirent.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
#include "local.h"

#define MAX_DIRS 4

struct _DIR {
    _Node node;
    unsigned next;          /* the next entry to look at */
    struct dirent entry;
};

static DIR dirs[MAX_DIRS];
static int dir_used[MAX_DIRS];

int mkdir(const char *path, ...)
{
    _Node dir, node;
    char name[_FS_NAME];
    if (_fs_lookup(path, &node) == 0) {
        errno = EEXIST;
        return -1;
    }
    if (errno != ENOENT || _fs_parent(path, &dir, name))
        return -1;
    return _fs_add(&dir, name, _FS_DIR, &node);
}

int rmdir(const char *path)
{
    _Node node;
    if (_fs_lookup(path, &node))
        return -1;
    if (node.root) {
        errno = EBUSY;
        return -1;
    }
    if (!(node.flags & _FS_DIR)) {
        errno = ENOTDIR;
        return -1;
    }
    if (!_fs_empty(&node)) {
        errno = ENOTEMPTY;
        return -1;
    }
    _fs_unlink(&node);
    return 0;
}

int chdir(const char *path)
{
    _Node node;
    char full[_FS_PATH];
    if (_fs_lookup(path, &node) || _fs_normalize(path, full))
        return -1;
    if (!(node.flags & _FS_DIR)) {
        errno = ENOTDIR;
        return -1;
    }
    strcpy(_fs_cwd, full);
    return 0;
}

char *getcwd(char *buf, size_t size)
{
    if (strlen(_fs_cwd) + 1 > size) {
        errno = ERANGE;
        return 0;
    }
    strcpy(buf, _fs_cwd);
    return buf;
}

DIR *opendir(const char *path)
{
    int i;
    _Node node;
    if (_fs_lookup(path, &node))
        return 0;
    if (!(node.flags & _FS_DIR)) {
        errno = ENOTDIR;
        return 0;
    }
    for (i = 0; i < MAX_DIRS && dir_used[i]; i++)
        ;
    if (i == MAX_DIRS) {
        errno = EMFILE;
        return 0;
    }
    dir_used[i] = 1;
    dirs[i].node = node;
    dirs[i].next = 0;
    return &dirs[i];
}

struct dirent *readdir(DIR *dir)
{
    unsigned count = dir->node.length / _FS_ENTRY, base, flags, k;
    while (dir->next < count) {
        base = dir->next++ * _FS_ENTRY;
        flags = _fs_word(dir->node.first, base + _FS_NAME + 2);
        if (!(flags & _FS_USED))
            continue;
        for (k = 0; k < _FS_NAME; k++)
            dir->entry.d_name[k] = _fs_word(dir->node.first, base + k);
        dir->entry.d_name[_FS_NAME - 1] = 0;
        dir->entry.d_size = _fs_word(dir->node.first, base + _FS_NAME + 1);
        dir->entry.d_type = flags & _FS_DIR ? DT_DIR : DT_REG;
        return &dir->entry;
    }
    return 0;
}

int closedir(DIR *dir)
{
    int i;
    for (i = 0; i < MAX_DIRS; i++)
        if (dir == &dirs[i])
            dir_used[i] = 0;
    return 0;
}
