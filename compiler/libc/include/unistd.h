/* unistd.h - directories on the disk (see stdio.h)
 *
 *   chdir(path)          make path the current directory (relative paths start there)
 *   getcwd(buf, size)    the current directory ("/" at start), or 0 if it doesn't fit
 *   mkdir(path, ...)     a new empty directory (a mode, as POSIX passes, is ignored;
 *                        POSIX declares mkdir in sys/stat.h)
 *   rmdir(path)          delete an empty directory
 *
 * All return 0, or -1 with errno set (errno.h).
 */
#ifndef _UNISTD_H
#define _UNISTD_H

#include <stddef.h>

int chdir(const char *path);
char *getcwd(char *buf, size_t size);
int mkdir(const char *path, ...);
int rmdir(const char *path);

#endif
