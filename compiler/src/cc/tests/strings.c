/* string.h, ctype.h, stdlib.h conversions, sprintf/sscanf, qsort */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

static int compare(const void *a, const void *b)
{
    int x = *(const int *)a, y = *(const int *)b;
    return x < y ? -1 : x > y;
}

static int compare_str(const void *a, const void *b)
{
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

int main(void)
{
    char buf[64];
    char copy[32];
    char *tok;
    int nums[] = { 42, -7, 0, 99, 13, 13, -100, 5 };
    const char *words[] = { "pear", "apple", "fig", "banana", "cherry" };
    int i, x, y, n;
    float f;
    char word[16];

    strcpy(buf, "hello");
    strcat(buf, ", world");
    printf("%s %d\n", buf, (int)strlen(buf));
    printf("%d %d %d\n", strcmp("abc", "abd") < 0, strcmp("b", "a") > 0, strcmp("x", "x"));
    printf("%d %d\n", strncmp("hello", "help", 3), strncmp("hello", "help", 4) < 0);
    printf("%s %s\n", strchr(buf, 'o'), strrchr(buf, 'o'));
    printf("%s %d\n", strstr(buf, "wor"), strstr(buf, "xyz") == NULL);
    printf("%d %d\n", (int)strspn("aabbcd", "ab"), (int)strcspn("hello world", " "));
    strncpy(copy, "abcdef", 3);
    copy[3] = 0;
    printf("%s\n", copy);
    memset(copy, 'z', 5);
    copy[5] = 0;
    printf("%s\n", copy);
    memcpy(copy, "12345678", 9);
    memmove(copy + 2, copy, 5);
    printf("%s %d\n", copy, memcmp("abc", "abd", 3) < 0);

    strcpy(buf, "one,two,,three");
    for (tok = strtok(buf, ","); tok; tok = strtok(NULL, ","))
        printf("<%s>", tok);
    printf("\n");

    for (i = 0; i < 5; i++)
        printf("%c%c", toupper("hello"[i]), tolower("WORLD"[i]));
    printf(" %d%d%d%d\n", !!isdigit('5'), !!isalpha('5'), !!isspace('\t'), !!ispunct('!'));

    printf("%d %d %d %d\n", atoi("123"), atoi("-45x"), (int)strtol("ff", NULL, 16),
           (int)strtol("0x1A", NULL, 0));
    printf("%d %u\n", (int)strtol("  -077", NULL, 0), (unsigned)strtoul("4000000000", NULL, 10));
    printf("%.3f %.3f\n", atof("3.25"), strtod("-1.5e2", NULL));

    n = sprintf(buf, "%d-%s-%.2f", 7, "ab", 1.255f);
    printf("%s %d\n", buf, n);
    n = snprintf(buf, 6, "%s", "truncated");
    printf("%s %d\n", buf, n);

    n = sscanf("12 34 5.5 word", "%d %d %f %s", &x, &y, &f, word);
    printf("%d: %d %d %.1f %s\n", n, x, y, f, word);
    n = sscanf("x=10,y=-3", "x=%d,y=%d", &x, &y);
    printf("%d: %d %d\n", n, x, y);
    n = sscanf("abc", "%d", &x);
    printf("%d\n", n);

    qsort(nums, 8, sizeof nums[0], compare);
    for (i = 0; i < 8; i++)
        printf("%d ", nums[i]);
    printf("\n");
    qsort(words, 5, sizeof words[0], compare_str);
    for (i = 0; i < 5; i++)
        printf("%s ", words[i]);
    printf("\n");
    {
        int key = 13;
        int *found = bsearch(&key, nums, 8, sizeof nums[0], compare);
        printf("found %d at %d\n", *found, (int)(found - nums));
    }
    return 0;
}
