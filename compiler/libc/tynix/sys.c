/* sys.c - the start of a program for Tynix (cc build --exe) and the
 * wrappers of the kernel's calls (sys/tynix.h). crt0 calls _tx_start()
 * with the block the kernel passed in R1, before main(). */
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <unistd.h>
#include <sys/tynix.h>
#include "../local.h"

#define OUT_BUF 64

unsigned *_tx_block;            /* the block (sys/tynix.h: B_ARGC ...) */

int _syscall(int n, int a, int b, int c, int d);       /* sys.asm */
void _set_stdout(int (*put)(int, FILE *), int (*flush)(FILE *));   /* file.c */

/* a call whose negative answer is -errno: -1 and errno */
int _tx_call(int n, int a, int b, int c, int d)
{
    int r = _syscall(n, a, b, c, d);
    if (r < 0 && r > -200) {
        errno = -r;
        return -1;
    }
    return r;
}

/* stdout to a file (the shell's >): the words go to the kernel in groups */
static unsigned out_buf[OUT_BUF];
static int out_len;

static void out_flush(void)
{
    if (out_len)
        _syscall(SYS_WRITE, 1, (int)out_buf, out_len, 0);
    out_len = 0;
}

/* fflush(stdout): a program that writes to the same file another way (a
   child it starts gets the same file) sends its own words first */
static int out_fflush(FILE *unused)
{
    out_flush();
    return 0;
}

static int out_put(int c, FILE *unused)
{
    out_buf[out_len++] = c;
    if (out_len == OUT_BUF)
        out_flush();
    return c;
}

/* stdin from a file (SPAWN_IN, or the parent's): getchar reads it here */
extern int (*_stdin_get)(void);        /* getchar.c */
static unsigned in_buf[OUT_BUF];
static int in_len, in_pos, in_end;

static int in_get(void)
{
    if (in_pos == in_len) {
        if (in_end)
            return EOF;
        in_len = _syscall(SYS_READ, 0, (int)in_buf, OUT_BUF, 0);
        in_pos = 0;
        if (in_len <= 0) {
            in_len = 0;
            in_end = 1;
            return EOF;
        }
    }
    return in_buf[in_pos++] & 0xFF;
}

void _tx_start(unsigned *block)
{
    _tx_block = block;
    if (block[B_OUT]) {
        _set_stdout(out_put, out_fflush);
        atexit(out_flush);
    }
    if (block[B_IN])
        _stdin_get = in_get;
}
