/* memcpy and memset: empty, one element, long, from a string literal, return values, neighbours
   untouched (sizes in sizeof(int); memset values 0 and -1 mean the same for any int size) */
#include <stdio.h>
#include <string.h>

static int buf[300], src[300];

static int sum(const int *p, int n)
{
    int i, s = 0;
    for (i = 0; i < n; i++)
        s = s * 31 + p[i] + i;
    return s;
}

int main(void)
{
    int i;
    char text[16];
    for (i = 0; i < 300; i++) {
        src[i] = i * 7 + 1;
        buf[i] = -1;
    }
    printf("%d\n", memcpy(buf + 10, src, 0) == buf + 10);
    printf("%d %d\n", buf[9], buf[10]);                    /* n = 0 writes nothing */
    printf("%d\n", memcpy(buf + 10, src + 5, sizeof(int)) == buf + 10);
    printf("%d %d %d\n", buf[9], buf[10], buf[11]);
    memcpy(buf, src, 300 * sizeof(int));
    printf("%d\n", sum(buf, 300) == sum(src, 300));
    memset(buf + 1, 0, 0);
    printf("%d\n", buf[1] == src[1]);
    printf("%d\n", memset(buf + 100, 0, sizeof(int)) == buf + 100);
    printf("%d %d %d\n", buf[99] == src[99], buf[100], buf[101] == src[101]);
    memset(buf, 0, 300 * sizeof(int));
    printf("%d %d %d\n", buf[0], buf[150], buf[299]);
    memset(buf + 1, -1, 298 * sizeof(int));
    printf("%d %d %d %d\n", buf[0], buf[1], buf[298], buf[299]);
    memcpy(text, "hello, world", 13);                      /* from ROM data */
    printf("%s\n", text);
    memset(text + 5, '-', 2);
    printf("%s\n", text);
    return 0;
}
