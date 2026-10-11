/* structs, unions, bit-fields, structs by value, linked lists */
#include <stdio.h>
#include <stdlib.h>

struct point { int x, y; };
struct rect { struct point a, b; const char *name; };

typedef struct node {
    int value;
    struct node *next;
} Node;

union word { int i; unsigned u; float f; char c; };

struct flags {
    unsigned ready : 1;
    unsigned mode : 3;
    int delta : 5;
    unsigned big : 20;
};

struct with_array { int n; int items[4]; };

static struct point make(int x, int y)
{
    struct point p;
    p.x = x;
    p.y = y;
    return p;
}

static struct point add(struct point a, struct point b)
{
    return make(a.x + b.x, a.y + b.y);
}

static int area(const struct rect *r)
{
    return (r->b.x - r->a.x) * (r->b.y - r->a.y);
}

static Node *push(Node *head, int v)
{
    Node *n = malloc(sizeof *n);
    n->value = v;
    n->next = head;
    return n;
}

static struct with_array twice(struct with_array w)
{
    int i;
    for (i = 0; i < w.n; i++)
        w.items[i] *= 2;
    return w;
}

int main(void)
{
    struct point p = { 3, 4 }, q;
    struct rect r = { { 1, 2 }, { 11, 7 }, "box" };
    struct rect s;
    Node *list = 0, *n;
    union word w;
    struct flags f = { 1, 5, -3, 1000 };
    struct with_array arr = { 3, { 1, 2, 3, 99 } }, doubled;
    int sum = 0, i;

    q = p;
    q.x += 10;
    printf("%d %d %d %d\n", p.x, p.y, q.x, q.y);
    q = add(p, make(100, 200));
    printf("%d %d\n", q.x, q.y);
    printf("%s %d\n", r.name, area(&r));
    s = r;
    s.b.x = 21;
    printf("%d %d %d\n", area(&r), area(&s), s.a.y);

    for (i = 1; i <= 5; i++)
        list = push(list, i * i);
    for (n = list; n; n = n->next)
        sum += n->value;
    printf("list sum %d first %d\n", sum, list->value);
    while (list) {
        n = list->next;
        free(list);
        list = n;
    }

    w.i = 0x41;
    printf("%c %u\n", w.c, w.u);
    w.f = 1.0f;
    printf("%x\n", w.u);

    printf("%u %u %d %u\n", f.ready, f.mode, f.delta, f.big);
    f.mode = 9;          /* keeps the low 3 bits */
    f.delta += 20;       /* -3 + 20 = 17, wraps to -15 in 5 bits */
    f.big = f.big * 3 + 1;
    printf("%u %u %d %u\n", f.ready, f.mode, f.delta, f.big);
    f.ready = 0;
    printf("%u %u %d %u\n", f.ready, f.mode, f.delta, f.big);

    doubled = twice(arr);
    printf("%d %d %d %d | %d %d\n", doubled.items[0], doubled.items[1], doubled.items[2],
           doubled.items[3], arr.items[0], arr.n);

    {
        struct point pts[3] = { { 1, 1 }, { 2, 4 }, { 3, 9 } };
        struct point *pp = pts;
        int t = 0;
        for (i = 0; i < 3; i++, pp++)
            t += pp->x * pp->y;
        printf("%d %d\n", t, pts[2].y);
    }
    return 0;
}
