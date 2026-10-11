/* count words with a hash table of malloc'd nodes, then sort them */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

struct word {
    char *text;
    int count;
    struct word *next;
};

#define BUCKETS 31

static struct word *table[BUCKETS];
static int distinct;

static unsigned hash(const char *s)
{
    unsigned h = 5381;
    while (*s)
        h = h * 33 + *s++;
    return h % BUCKETS;
}

static void add(const char *s)
{
    unsigned h = hash(s);
    struct word *w;
    for (w = table[h]; w; w = w->next)
        if (strcmp(w->text, s) == 0) {
            w->count++;
            return;
        }
    w = malloc(sizeof *w);
    w->text = malloc(strlen(s) + 1);
    strcpy(w->text, s);
    w->count = 1;
    w->next = table[h];
    table[h] = w;
    distinct++;
}

static int by_count(const void *a, const void *b)
{
    const struct word *x = *(struct word *const *)a;
    const struct word *y = *(struct word *const *)b;
    if (x->count != y->count)
        return y->count - x->count;
    return strcmp(x->text, y->text);
}

int main(void)
{
    const char *text = "the quick brown fox jumps over the lazy dog the fox "
                       "and the dog are friends and the end";
    char buf[32];
    struct word **all;
    int i, n = 0, k = 0;
    while (*text) {
        while (*text && !isalpha(*text))
            text++;
        n = 0;
        while (isalpha(*text))
            buf[n++] = *text++;
        buf[n] = 0;
        if (n)
            add(buf);
    }
    all = malloc(distinct * sizeof *all);
    for (i = 0; i < BUCKETS; i++) {
        struct word *w;
        for (w = table[i]; w; w = w->next)
            all[k++] = w;
    }
    qsort(all, distinct, sizeof *all, by_count);
    printf("%d distinct words\n", distinct);
    for (i = 0; i < 6; i++)
        printf("%-6s %d\n", all[i]->text, all[i]->count);
    return 0;
}
