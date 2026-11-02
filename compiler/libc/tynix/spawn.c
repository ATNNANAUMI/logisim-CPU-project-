/* spawn.c for a program for Tynix: running other programs (unistd.h).
 * Every program can start others now: each gets its own region of RAM
 * from the kernel. */
#include <stdio.h>
#include <errno.h>
#include <unistd.h>
#include <sys/tynix.h>
#include "../local.h"

int _tx_call(int n, int a, int b, int c, int d);       /* sys.c */
int _syscall(int n, int a, int b, int c, int d);       /* sys.asm */

int spawn(const char *path, char *const argv[], int flags)
{
    return _tx_call(SYS_SPAWN, (int)path, (int)argv, 1, flags);
}

int spawn_to(const char *path, char *const argv[], FILE *out, int flags)
{
    if (out)
        fflush(out);
    return _tx_call(SYS_SPAWN, (int)path, (int)argv, out ? out->fd : 1, flags);
}

int spawn_io(const char *path, char *const argv[], FILE *in, FILE *out, int flags)
{
    if (in && in->fd < 3) {             /* stdin: not a file of the kernel's */
        errno = EBADF;
        return -1;
    }
    return spawn_to(path, argv, out, flags | (in ? SPAWN_IN(in->fd) : 0));
}

int waitpid(int pid, int *status, int flags)
{
    int who = pid, r = _syscall(SYS_WAIT, pid, flags, (int)&who, 0);
    if (r == WAIT_RUNNING)
        return 0;
    if (r < 0 && r > -200) {
        errno = -r;
        return -1;
    }
    if (status)
        *status = r;
    return who;
}

int spawnv_to(const char *path, char *const argv[], FILE *out)
{
    int pid = spawn_to(path, argv, out, SPAWN_FG), status;
    if (pid < 0 || waitpid(pid, &status, 0) < 0)
        return -1;
    return status;
}

int spawnv(const char *path, char *const argv[])
{
    return spawnv_to(path, argv, 0);
}

int kill(int pid, int sig)
{
    return _tx_call(SYS_KILL, pid, sig, 0, 0);
}

int getpid(void)
{
    return _syscall(SYS_GETPID, 0, 0, 0, 0);
}

void yield(void)
{
    _syscall(SYS_YIELD, 0, 0, 0, 0);
}

int set_foreground(int pid)
{
    return _tx_call(SYS_FOREGROUND, pid, 0, 0, 0);
}

int tasks(struct task_info *buf, int max)
{
    return _tx_call(SYS_TASKS, (int)buf, max, 0, 0);
}

void halt_os(void)
{
    _syscall(SYS_HALT, 0, 0, 0, 0);
}
