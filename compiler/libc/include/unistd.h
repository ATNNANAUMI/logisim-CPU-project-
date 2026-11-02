/* unistd.h - directories on the disk (see stdio.h), and running programs
 *
 *   chdir(path)          make path the current directory (relative paths start there)
 *   getcwd(buf, size)    the current directory ("/" at start), or 0 if it doesn't fit
 *   mkdir(path, ...)     a new empty directory (a mode, as POSIX passes, is ignored;
 *                        POSIX declares mkdir in sys/stat.h)
 *   rmdir(path)          delete an empty directory
 *
 * All return 0, or -1 with errno set (errno.h).
 *
 *   spawnv(path, argv)   run the program in the file `path` (built with
 *                        `cc build --exe`, put on the disk) with the
 *                        arguments argv[0], argv[1], ... up to a NULL, and
 *                        wait for it: returns its exit status, or -1 with
 *                        errno set if it can't be loaded (ENOEXEC: not a
 *                        program). It starts in the current directory. Like
 *                        DOS's spawnv(P_WAIT, ...). Not in a program built
 *                        with --exe itself.
 *   spawnv_to(path, argv, out)   the same, with the program's stdout (what
 *                        printf, putchar and puts write) going to the open
 *                        FILE out instead of the display; out is the
 *                        caller's, still open when the program ends. The
 *                        program should not rewrite that file itself.
 *   isatty(fd)           1 if fd (0 keyboard, 1 stdout, 2 stderr) is the
 *                        console, 0 if it is a file: only stdout can be, when
 *                        the shell started the program with `>`. Not standard
 *                        in what it covers: there are no other descriptors.
 */
#ifndef _UNISTD_H
#define _UNISTD_H

#include <stddef.h>
#include <stdio.h>

int chdir(const char *path);
char *getcwd(char *buf, size_t size);
int mkdir(const char *path, ...);
int rmdir(const char *path);
int spawnv(const char *path, char *const argv[]);
int spawnv_to(const char *path, char *const argv[], FILE *out);
int isatty(int fd);

#endif
