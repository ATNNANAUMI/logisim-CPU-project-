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
 * Programs (Tynix: only in a program built with --exe, which the kernel runs;
 * several run at once):
 *
 *   spawnv(path, argv)   run the program in the file `path` (built with
 *                        `cc build --exe`, put on the disk) with the
 *                        arguments argv[0], argv[1], ... up to a NULL, in
 *                        the foreground, and wait for it: returns its exit
 *                        status (130 killed, 139 past its stack), -1 with
 *                        errno set if it can't be loaded (ENOEXEC: not a
 *                        program, ENOMEM: no room), or SPAWN_BACKGROUND if
 *                        the NMI menu sent it to the background (it goes on).
 *                        It starts in the caller's current directory.
 *   spawnv_to(path, argv, out)   the same, with the program's stdout (what
 *                        printf, putchar and puts write) going to the open
 *                        FILE out instead of the display; out stays the
 *                        caller's, still open when the program ends.
 *   spawn(path, argv, flags)     start it and don't wait: its pid, or -1.
 *                        flags SPAWN_FG gives it the keyboard and the screen.
 *   spawn_to(path, argv, out, flags)   the same, its stdout to out (or 0:
 *                        the caller's stdout, which is a file when the
 *                        caller's is).
 *   spawn_io(path, argv, in, out, flags)   the same, and its stdin (what
 *                        getchar, fgets and scanf read) from the open FILE in,
 *                        without echo, EOF at its end (or 0: the caller's
 *                        stdin, the keyboard unless the caller's is a file).
 *                        Keys read with key_pressed()/wait_key() still come
 *                        from the keyboard.
 *   waitpid(pid, &status, flags) wait for a child (pid -1: any) to end:
 *                        its pid, or 0 with WAIT_NOHANG while it still runs,
 *                        -1 (ECHILD) when there is none. status: as spawnv's.
 *   kill(pid, sig)       end that program (status 130); sig is not used.
 *   getpid()             this program's number; yield() lets the others run.
 *   set_foreground(pid)  give that program the keyboard and the screen.
 *   tasks(buf, max)      what runs (struct task_info, sys/tynix.h); halt_os():
 *                        close every file and stop the CPU.
 *   fs_reclaim()         the blocks no file uses (what a killed program left
 *                        half written) are freed, and chains longer than
 *                        their file's length are cut. Returns how many
 *                        blocks it freed, or -1 (errno ENODEV, no disk).
 *                        Not POSIX.
 *   isatty(fd)           1 if fd (0 keyboard, 1 stdout, 2 stderr) is the
 *                        console, 0 if it is a file: stdout when the shell
 *                        started the program with `>`, stdin when it was
 *                        started with spawn_io. Not standard in what it
 *                        covers: there are no other descriptors.
 */
#ifndef _UNISTD_H
#define _UNISTD_H

#include <stddef.h>
#include <stdio.h>

int chdir(const char *path);
char *getcwd(char *buf, size_t size);
int mkdir(const char *path, ...);
int rmdir(const char *path);
int fs_reclaim(void);

#include <sys/tynix.h>          /* SPAWN_FG, WAIT_NOHANG, struct task_info */
#define SPAWN_BACKGROUND WAIT_BACKGROUND
int spawnv(const char *path, char *const argv[]);
int spawnv_to(const char *path, char *const argv[], FILE *out);
int spawn(const char *path, char *const argv[], int flags);
int spawn_to(const char *path, char *const argv[], FILE *out, int flags);
int spawn_io(const char *path, char *const argv[], FILE *in, FILE *out, int flags);
int waitpid(int pid, int *status, int flags);
int kill(int pid, int sig);
int getpid(void);
void yield(void);
int set_foreground(int pid);
int tasks(struct task_info *buf, int max);
void halt_os(void);
int isatty(int fd);

#endif
