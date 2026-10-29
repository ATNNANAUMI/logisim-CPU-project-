/* structs.c - a small inventory: structs, arrays of structs, qsort, malloc
 *
 *   python compiler/src/cc run compiler/examples/c/basics/structs.c
 *
 * prints the items sorted by value, then the total.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct item {
    char name[12];
    int count;
    float price;
};

static int by_value(const void *a, const void *b)
{
    const struct item *x = a, *y = b;
    float vx = x->count * x->price, vy = y->count * y->price;
    return (vx < vy) - (vx > vy);            /* biggest first */
}

int main(void)
{
    static const struct item stock[] = {
        { "bolts", 120, 0.15f }, { "gears", 8, 4.75f }, { "wire", 30, 1.20f },
        { "relays", 5, 12.50f }, { "lamps", 14, 2.10f },
    };
    int n = sizeof stock / sizeof stock[0], i;
    struct item *copy = malloc(sizeof stock);
    float total = 0;

    memcpy(copy, stock, sizeof stock);
    qsort(copy, n, sizeof copy[0], by_value);
    for (i = 0; i < n; i++) {
        float value = copy[i].count * copy[i].price;
        printf("%-8s %4d x %6.2f = %7.2f\n", copy[i].name, copy[i].count, copy[i].price, value);
        total += value;
    }
    printf("total %.2f\n", total);
    free(copy);
    return 0;
}
