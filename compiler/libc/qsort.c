/* qsort (quicksort, median of three, insertion sort for short runs), bsearch */
#include <stdlib.h>

static void swap(char *a, char *b, size_t size)
{
    while (size--) {
        char t = *a;
        *a++ = *b;
        *b++ = t;
    }
}

static void sort(char *lo, char *hi, size_t size, int (*cmp)(const void *, const void *))
{
    /* sorts lo .. hi, both included */
    while (hi > lo) {
        size_t n = (hi - lo) / size + 1;
        char *mid, *i, *j;
        if (n <= 8) {
            for (i = lo + size; i <= hi; i += size)
                for (j = i; j > lo && cmp(j - size, j) > 0; j -= size)
                    swap(j - size, j, size);
            return;
        }
        mid = lo + (n / 2) * size;
        if (cmp(mid, lo) < 0)
            swap(mid, lo, size);
        if (cmp(hi, lo) < 0)
            swap(hi, lo, size);
        if (cmp(hi, mid) < 0)
            swap(hi, mid, size);
        /* the pivot (the median) goes next to the end */
        swap(mid, hi - size, size);
        i = lo;
        j = hi - size;
        for (;;) {
            do i += size; while (cmp(i, hi - size) < 0);
            do j -= size; while (j > lo && cmp(j, hi - size) > 0);
            if (i >= j)
                break;
            swap(i, j, size);
        }
        swap(i, hi - size, size);
        /* recurse into the smaller side, loop on the bigger one */
        if (i - lo < hi - i) {
            sort(lo, i - size, size, cmp);
            lo = i + size;
        } else {
            sort(i + size, hi, size, cmp);
            hi = i - size;
        }
    }
}

void qsort(void *base, size_t count, size_t size, int (*cmp)(const void *, const void *))
{
    if (count > 1 && size > 0)
        sort(base, (char *)base + (count - 1) * size, size, cmp);
}

void *bsearch(const void *key, const void *base, size_t count, size_t size,
              int (*cmp)(const void *, const void *))
{
    const char *lo = base;
    while (count > 0) {
        const char *mid = lo + (count / 2) * size;
        int c = cmp(key, mid);
        if (c == 0)
            return (void *)mid;
        if (c > 0) {
            lo = mid + size;
            count -= count / 2 + 1;
        } else {
            count /= 2;
        }
    }
    return 0;
}
