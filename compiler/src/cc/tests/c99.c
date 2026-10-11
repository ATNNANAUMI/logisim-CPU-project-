/* C99 features: declarations anywhere, compound literals, designated
 * initializers, bool, inline, __func__, // comments, mixed declarations */
#include <stdio.h>
#include <stdbool.h>
#include <string.h>

struct vec { float x, y; };

static inline float dot(struct vec a, struct vec b) { return a.x * b.x + a.y * b.y; }

static int sum(const int *p, int n)
{
    int s = 0;
    for (int i = 0; i < n; i++)  // a declaration in the for
        s += p[i];
    return s;
}

enum color { RED, GREEN = 5, BLUE };
typedef enum color Color;

int main(void)
{
    bool flag = true;
    int total = sum((int[]){ 1, 2, 3, 4 }, 4);
    printf("%d %d\n", flag, total);
    struct vec v = { .y = 2.0f, .x = 1.5f };
    printf("%.2f\n", dot(v, (struct vec){ 2.0f, 0.5f }));
    printf("%s\n", __func__);
    Color c = BLUE;
    printf("%d %d %d\n", RED, GREEN, c);
    int squares[] = { [4] = 16, [2] = 4 };
    printf("%d %d\n", (int)(sizeof squares / sizeof squares[0]), squares[2]);
    bool b2 = 42;
    printf("%d %d\n", b2, (bool)0.0f);
    for (int i = 0, j = 10; i < j; i += 3, j -= 3)
        printf("%d-%d ", i, j);
    printf("\n");
    char name[] = "x";
    printf("%d\n", (int)strlen(name));
    return 0;
}
