/* malloc, calloc, realloc, free.
 *
 * The heap is the RAM after the program's own variables: from _end (a label
 * the C compiler's build puts after all other RAM data) to _heap_end, a word
 * crt0 holds: the end of RAM (0x2000000, linker.py's RAM_END, one past the
 * last word), or the program area (linker.py's PROGRAM_BASE) in a program
 * that runs others with spawnv(), since they are loaded there. Each block has a one-word
 * header before it: its size in words, header included, positive when free
 * and negative when in use. malloc takes the first free block that is big
 * enough (joining free neighbours as it walks) and splits off what it
 * doesn't need.
 */
#include <stdlib.h>
#include <string.h>

extern int _end[];
extern int *const _heap_end;
#define HEAP_END _heap_end

static int *heap;            /* the first block; 0 until the first malloc */

static void setup(void)
{
    heap = _end;
    heap[0] = HEAP_END - _end;
}

void *malloc(size_t n)
{
    int *b;
    int need;
    if (n == 0 || n >= 0x1000000)       /* more than all of RAM */
        return 0;
    if (heap == 0)
        setup();
    need = n + 1;
    for (b = heap; b < HEAP_END; ) {
        int size = b[0];
        if (size < 0) {
            b -= size;               /* in use: skip it */
            continue;
        }
        if (size == 0)               /* a damaged header: b += 0 would never end */
            return 0;
        /* join the free blocks that follow */
        while (b + size < HEAP_END && b[size] > 0)
            size += b[size];
        b[0] = size;
        if (size >= need) {
            if (size - need >= 2) {  /* split, leaving a free block */
                b[need] = size - need;
                size = need;
            }
            b[0] = -size;
            return b + 1;
        }
        b += size;
    }
    return 0;
}

void free(void *p)
{
    int *b = p;
    if (b == 0 || heap == 0 || b <= heap || b > HEAP_END)
        return;
    b--;
    if (b[0] < 0)
        b[0] = -b[0];
}

void *calloc(size_t count, size_t size)
{
    size_t n = count * size;
    void *p;
    if (size && n / size != count)
        return 0;
    p = malloc(n);
    if (p)
        memset(p, 0, n);
    return p;
}

void *realloc(void *p, size_t n)
{
    int *b = p;
    int have;
    void *q;
    if (b == 0)
        return malloc(n);
    if (n == 0) {
        free(p);
        return 0;
    }
    have = -b[-1] - 1;
    if ((int)n <= have)
        return p;
    /* grow in place when the next block is free and big enough */
    {
        int *h = b - 1;
        int size = -h[0];
        while (h + size < HEAP_END && h[size] > 0)
            size += h[size];
        if (size - 1 >= (int)n) {
            if (size - 1 - (int)n >= 2) {
                h[n + 1] = size - (n + 1);
                size = n + 1;
            }
            h[0] = -size;
            return p;
        }
    }
    q = malloc(n);
    if (q == 0)
        return 0;
    memcpy(q, p, have);
    free(p);
    return q;
}
