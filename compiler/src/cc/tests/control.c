/* statements: if, loops, break/continue, switch, goto */
#include <stdio.h>

static const char *name(int n)
{
    switch (n) {
    case 0: return "zero";
    case 1: return "one";
    case 2: return "two";
    case 3: return "three";
    case 4: return "four";
    case 5: return "five";
    case 7: return "seven";
    default: return "many";
    }
}

static int classify(int c)
{
    switch (c) {
    case 'a': case 'e': case 'i': case 'o': case 'u':
        return 1;
    case ' ':
        return 2;
    case '0' ... '9':
        return 3;
    }
    return 0;
}

int main(void)
{
    int i, j, total = 0, count = 0;

    for (i = 0; i < 10; i++) {
        if (i == 3)
            continue;
        if (i == 8)
            break;
        total += i;
    }
    printf("for: %d\n", total);

    i = 0;
    while (1) {
        if (++i > 5)
            break;
    }
    printf("while: %d\n", i);

    i = 10;
    do {
        i -= 3;
    } while (i > 0);
    printf("do: %d\n", i);

    for (i = 0; i < 5; i++)
        for (j = 0; j < 5; j++) {
            if (j > i)
                break;
            count++;
        }
    printf("nested: %d\n", count);

    for (i = 0; i <= 8; i++)
        printf("%s ", name(i));
    printf("\n");

    {
        const char *s = "hi 42 you";
        int k[4] = { 0, 0, 0, 0 };
        for (; *s; s++)
            k[classify(*s)]++;
        printf("classes: %d %d %d %d\n", k[0], k[1], k[2], k[3]);
    }

    /* fall through */
    for (i = 0; i < 4; i++) {
        int x = 0;
        switch (i) {
        case 0:
            x += 1;
        case 1:
            x += 10;
            break;
        case 2:
            x += 100;
        default:
            x += 1000;
        }
        printf("%d ", x);
    }
    printf("\n");

    /* goto */
    i = 0;
again:
    i++;
    if (i < 5)
        goto again;
    printf("goto: %d\n", i);

    /* if / else chains */
    for (i = -2; i <= 2; i++) {
        if (i < 0)
            printf("neg ");
        else if (i == 0)
            printf("zero ");
        else
            printf("pos ");
    }
    printf("\n");

    /* conditional expressions */
    for (i = 0; i < 6; i++)
        printf("%d", i % 3 == 0 ? 0 : i % 3 == 1 ? 1 : 2);
    printf("\n");
    return 0;
}
