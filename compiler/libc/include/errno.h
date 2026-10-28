/* errno.h (the numbers are Linux's) */
#ifndef _ERRNO_H
#define _ERRNO_H

extern int errno;

#define ENOENT 2        /* no such file or directory */
#define EBADF 9         /* not a file on the disk */
#define EBUSY 16        /* the root directory */
#define EEXIST 17
#define ENODEV 19       /* no disk, or not formatted */
#define ENOTDIR 20
#define EISDIR 21
#define EINVAL 22
#define EMFILE 24       /* too many open files */
#define ENOSPC 28       /* disk full */
#define ERANGE 34
#define EDOM 33
#define ENAMETOOLONG 36
#define ENOTEMPTY 39
#define EILSEQ 84

#endif
