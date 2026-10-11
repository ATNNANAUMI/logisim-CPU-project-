/* less common C features */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TYPE_NAME(x) _Generic((x), int: "int", float: "float", char *: "char *", default: "other")

struct shape {
    int kind;
    union {                       /* anonymous union */
        struct { int w, h; };     /* anonymous struct */
        int radius;
    };
};

struct message {
    int len;
    char text[];                  /* flexible array member */
};

struct big { int v[20]; };

static const int lookup[8] = { 1, 1, 2, 6, 24, 120, 720, 5040 };

static int area(const struct shape *s)
{
    return s->kind == 0 ? s->w * s->h : 3 * s->radius * s->radius;
}

static struct big fill(int start)
{
    struct big b;
    int i;
    for (i = 0; i < 20; i++)
        b.v[i] = start + i;
    return b;
}

static int total(struct big b)
{
    int i, t = 0;
    for (i = 0; i < 20; i++)
        t += b.v[i];
    return t;
}

int main(void)
{
    struct shape rect = { 0, { { 3, 4 } } }, circle;
    struct message *m;
    struct big a, b;
    typeof(rect.w) twice = rect.w * 2;
    int i;
    float f = 1.0f;
    char *s = "x";

    printf("%s %s %s %s\n", TYPE_NAME(1), TYPE_NAME(f), TYPE_NAME(s), TYPE_NAME(2.0f * 3));
    circle.kind = 1;
    circle.radius = 5;
    printf("%d %d %d\n", area(&rect), area(&circle), twice);

    m = malloc(sizeof *m + 6);
    m->len = 5;
    strcpy(m->text, "hello");
    printf("%d %s\n", m->len, m->text);
    free(m);

    a = fill(10);
    b = a;                        /* a 20-word copy */
    b.v[0] = 100;
    printf("%d %d %d %d\n", total(a), total(b), a.v[19], b.v[0]);
    printf("%d\n", total(fill(1)));

    for (i = 0; i < 8; i++)
        printf("%d ", lookup[i]);
    printf("\n");

    {
        struct shape *list[2] = { &rect, &circle };
        int sum = 0;
        for (i = 0; i < 2; i++)
            sum += area(list[i]);
        printf("sum %d\n", sum);
    }
    {
        unsigned u = 7;
        switch (u) {
        case 0 ... 5: printf("low\n"); break;
        case 6 ... 10: printf("mid\n"); break;
        default: printf("high\n");
        }
    }
    return 0;
}
