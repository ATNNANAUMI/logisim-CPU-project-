/* errno.h (the numbers are Linux's) */
#ifndef _ERRNO_H
#define _ERRNO_H

extern int errno;

#define ENOENT 2        /* no such file or directory */
#define ESRCH 3         /* no such program running (kill) */
#define EIO 5           /* the kernel couldn't read the file */
#define ENOEXEC 8       /* not a program (spawnv) */
#define EBADF 9         /* not a file on the disk */
#define ECHILD 10       /* no child to wait for */
#define EAGAIN 11       /* Tynix: no free task (16 at most) */
#define ENOMEM 12       /* Tynix: no RAM for the program */
#define EBUSY 16        /* the root directory */
#define EEXIST 17
#define ENODEV 19       /* no disk, or not formatted */
#define ENOTDIR 20
#define EISDIR 21
#define EINVAL 22
#define ENFILE 23       /* Tynix: too many files open in all */
#define EMFILE 24       /* too many open files */
#define ENOSPC 28       /* disk full */
#define EPIPE 32        /* Tynix: a pipe with no reader left */
#define ERANGE 34
#define EDOM 33
#define ENAMETOOLONG 36
#define ENOSYS 38       /* not a system call */
#define ENOTEMPTY 39
#define EILSEQ 84

#endif
