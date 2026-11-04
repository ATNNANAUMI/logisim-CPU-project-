/* fs.c for a program for Tynix: fopen, fclose, fseek, ftell, rewind, remove,
 * rename, statvfs, stat and fs_reclaim, as in compiler/libc/fs.c, plus pipe
 * and fdopen (unistd.h), but the
 * filesystem is the kernel's (tynix/kernel.c): an open file is the kernel's
 * number for it, and its words go back and forth 64 at a time.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/statvfs.h>
#include <sys/stat.h>
#include <sys/tynix.h>
#include "../local.h"

#define MAX_OPEN 16
#define BUF 64

int _tx_call(int n, int a, int b, int c, int d);       /* sys.c */

static FILE files[MAX_OPEN];
static unsigned bufs[MAX_OPEN][BUF];
static int in_use[MAX_OPEN];
static int closer_set;

/* the words waiting in buf go to the kernel */
static int flush_out(FILE *f)
{
    int n = f->buf_len;
    f->buf_len = f->buf_pos = 0;
    f->buf_out = 0;
    if (n && _tx_call(SYS_WRITE, f->fd, (int)f->buf, n, 0) != n) {
        f->error = 1;
        return -1;
    }
    return 0;
}

/* words read ahead and not used: the kernel's position goes back over them */
static void drop_in(FILE *f)
{
    int unread = f->buf_len - f->buf_pos;
    f->buf_len = f->buf_pos = 0;
    if (unread)
        _tx_call(SYS_SEEK, f->fd, -unread, SEEK_CUR, 0);
}

static int file_flush(FILE *f)
{
    if (f->buf_out)
        return flush_out(f) ? EOF : 0;
    return 0;
}

static int file_get(FILE *f)
{
    int n;
    if (f->pushed != EOF) {
        n = f->pushed;
        f->pushed = EOF;
        return n;
    }
    if (!f->input) {
        f->error = 1;
        return EOF;
    }
    if (f->buf_out && flush_out(f))
        return EOF;
    if (f->buf_pos == f->buf_len) {
        n = _tx_call(SYS_READ, f->fd, (int)f->buf, BUF, 0);
        f->buf_pos = f->buf_len = 0;
        if (n <= 0) {
            if (n < 0)
                f->error = 1;
            else
                f->eof = 1;
            return EOF;
        }
        f->buf_len = n;
    }
    return f->buf[f->buf_pos++];
}

static int file_put(int c, FILE *f)
{
    if (!f->output) {
        f->error = 1;
        return EOF;
    }
    f->pushed = EOF;
    if (!f->buf_out) {
        drop_in(f);
        f->buf_out = 1;
    }
    f->buf[f->buf_len++] = c;
    if (f->buf_len == BUF && flush_out(f))
        return EOF;
    return f->packed ? c & 0xFF : c;
}

static void close_all(void)
{
    int i;
    for (i = 0; i < MAX_OPEN; i++)
        if (in_use[i])
            fclose(&files[i]);
}

/* a free FILE, or -1 (EMFILE) */
static int free_file(const char *mode)
{
    int i;
    if (mode[0] != 'r' && mode[0] != 'w' && mode[0] != 'a') {
        errno = EINVAL;
        return -1;
    }
    for (i = 0; i < MAX_OPEN && in_use[i]; i++)
        ;
    if (i == MAX_OPEN) {
        errno = EMFILE;
        return -1;
    }
    return i;
}

static FILE *new_file(int i, int fd, const char *mode, int packed)
{
    int plus = strchr(mode, '+') != 0;
    FILE *f = &files[i];
    memset(f, 0, sizeof *f);
    f->get = file_get;
    f->put = file_put;
    f->flush = file_flush;
    f->input = mode[0] == 'r' || plus;
    f->output = mode[0] != 'r' || plus;
    f->append = mode[0] == 'a';
    f->packed = packed;
    f->pushed = EOF;
    f->fd = fd;
    f->buf = bufs[i];
    in_use[i] = 1;
    if (!closer_set) {
        atexit(close_all);              /* exit() and the end of main() save open files */
        closer_set = 1;
    }
    return f;
}

FILE *fopen(const char *path, const char *mode)
{
    int i = free_file(mode), fd;
    struct stat st;
    if (i < 0 || (fd = _tx_call(SYS_OPEN, (int)path, (int)mode, 0, 0)) < 0)
        return 0;
    return new_file(i, fd, mode, stat(path, &st) == 0 && S_ISTEXT(st.st_mode));
}

/* an open number (an end of a pipe) as a FILE: one word a char */
FILE *fdopen(int fd, const char *mode)
{
    int i = free_file(mode);
    if (i < 0)
        return 0;
    return new_file(i, fd, mode, 0);
}

int pipe(int fds[2])
{
    return _tx_call(SYS_PIPE, (int)fds, 0, 0, 0);
}

int fclose(FILE *stream)
{
    int i, result = 0;
    for (i = 0; i < MAX_OPEN; i++)
        if (stream == &files[i] && in_use[i]) {
            result = file_flush(stream);
            if (_tx_call(SYS_CLOSE, stream->fd, 0, 0, 0))
                result = EOF;
            in_use[i] = 0;
            stream->get = 0;
            stream->put = 0;
            stream->flush = 0;
        }
    return result;
}

int fseek(FILE *stream, long offset, int whence)
{
    if (!stream->get) {
        errno = EBADF;
        return -1;
    }
    if (stream->buf_out) {
        if (flush_out(stream))
            return -1;
    } else
        drop_in(stream);
    if (_tx_call(SYS_SEEK, stream->fd, offset, whence, 0) < 0)
        return -1;
    stream->pushed = EOF;
    stream->eof = 0;
    return 0;
}

long ftell(FILE *stream)
{
    long at;
    if (!stream->get) {
        errno = EBADF;
        return -1;
    }
    if (stream->buf_out && flush_out(stream))
        return -1;
    at = _tx_call(SYS_SEEK, stream->fd, 0, SEEK_CUR, 0);
    if (at < 0)
        return -1;
    at -= stream->buf_len - stream->buf_pos;    /* read ahead, not used yet */
    if (stream->pushed != EOF)
        at--;                           /* ungetc steps it back */
    return at;
}

void rewind(FILE *stream)
{
    fseek(stream, 0, SEEK_SET);
    stream->error = 0;
}

int remove(const char *path)
{
    return _tx_call(SYS_REMOVE, (int)path, 0, 0, 0);
}

int rename(const char *from, const char *to)
{
    return _tx_call(SYS_RENAME, (int)from, (int)to, 0, 0);
}

int statvfs(const char *path, struct statvfs *buf)
{
    return _tx_call(SYS_STATVFS, (int)path, (int)buf, 0, 0);
}

int stat(const char *path, struct stat *buf)
{
    return _tx_call(SYS_STAT, (int)path, (int)buf, 0, 0);
}

int fs_reclaim(void)
{
    return _tx_call(SYS_RECLAIM, 0, 0, 0, 0);
}
