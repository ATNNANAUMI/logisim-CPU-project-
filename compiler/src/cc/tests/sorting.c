/* sorting algorithms on pseudo-random numbers (a fixed LCG, not rand()) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define N 60

static unsigned seed = 12345;

static int next_random(void)
{
    seed = seed * 1103515245u + 12345u;
    return (seed >> 16) % 1000;
}

static void insertion(int *a, int n)
{
    int i, j;
    for (i = 1; i < n; i++) {
        int v = a[i];
        for (j = i - 1; j >= 0 && a[j] > v; j--)
            a[j + 1] = a[j];
        a[j + 1] = v;
    }
}

static void merge_sort(int *a, int *tmp, int n)
{
    int mid = n / 2, i = 0, j = mid, k = 0;
    if (n < 2)
        return;
    merge_sort(a, tmp, mid);
    merge_sort(a + mid, tmp, n - mid);
    while (i < mid && j < n)
        tmp[k++] = a[i] <= a[j] ? a[i++] : a[j++];
    while (i < mid)
        tmp[k++] = a[i++];
    while (j < n)
        tmp[k++] = a[j++];
    memcpy(a, tmp, n * sizeof *a);
}

static void sift(int *a, int start, int end)
{
    int root = start;
    while (2 * root + 1 <= end) {
        int child = 2 * root + 1, swap = root;
        if (a[swap] < a[child])
            swap = child;
        if (child + 1 <= end && a[swap] < a[child + 1])
            swap = child + 1;
        if (swap == root)
            return;
        {
            int t = a[root];
            a[root] = a[swap];
            a[swap] = t;
        }
        root = swap;
    }
}

static void heap_sort(int *a, int n)
{
    int start, end;
    for (start = (n - 2) / 2; start >= 0; start--)
        sift(a, start, n - 1);
    for (end = n - 1; end > 0; end--) {
        int t = a[end];
        a[end] = a[0];
        a[0] = t;
        sift(a, 0, end - 1);
    }
}

static int sorted(const int *a, int n)
{
    int i;
    for (i = 1; i < n; i++)
        if (a[i - 1] > a[i])
            return 0;
    return 1;
}

static int checksum(const int *a, int n)
{
    int i, s = 0;
    for (i = 0; i < n; i++)
        s = s * 31 + a[i];
    return s;
}

int main(void)
{
    int a[N], b[N], c[N], tmp[N];
    int i;
    for (i = 0; i < N; i++)
        a[i] = b[i] = c[i] = next_random();
    printf("first: %d %d %d\n", a[0], a[1], a[2]);
    insertion(a, N);
    merge_sort(b, tmp, N);
    heap_sort(c, N);
    printf("sorted: %d %d %d\n", sorted(a, N), sorted(b, N), sorted(c, N));
    printf("same: %d %d\n", memcmp(a, b, sizeof a) == 0, memcmp(a, c, sizeof a) == 0);
    printf("min %d max %d checksum %d\n", a[0], a[N - 1], checksum(a, N));
    return 0;
}
