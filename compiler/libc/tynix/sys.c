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
void _set_stdout(int (*put)(int, FILE *));            /* file.c */

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

static int out_put(int c, FILE *unused)
{
    out_buf[out_len++] = c;
    if (out_len == OUT_BUF)
        out_flush();
    return c;
}

void _tx_start(unsigned *block)
{
    _tx_block = block;
    if (block[B_OUT]) {
        _set_stdout(out_put);
        atexit(out_flush);
    }
}
