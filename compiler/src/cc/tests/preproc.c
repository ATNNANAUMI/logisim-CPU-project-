/* the preprocessor */
#include <stdio.h>

#define SQUARE(x) ((x) * (x))
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define STR(x) #x
#define XSTR(x) STR(x)
#define CAT(a, b) a##b
#define VERSION 3
#define LOG(fmt, ...) printf("log: " fmt "\n", __VA_ARGS__)
#define EMPTY
#define LIST(X) X(red) X(green) X(blue)
#define AS_STRING(n) #n,
#define COUNT(n) +1

#if VERSION > 2 && defined(VERSION)
#define NEW 1
#else
#define NEW 0
#endif

#ifdef UNDEFINED_THING
#error "should not happen"
#endif

static const char *colors[] = { LIST(AS_STRING) };

int main(void)
{
    int CAT(my, var) = 5;
    printf("%d %d %d\n", SQUARE(3 + 1), MAX(4, 9), myvar);
    printf("%s %s %s\n", STR(a + b), XSTR(VERSION), STR("quoted"));
    LOG("%d and %s", 1, "two");
    printf("%d %d\n", NEW, 0 LIST(COUNT));
    printf("%s %s %s\n", colors[0], colors[1], colors[2]);
#if 0
    printf("hidden\n");
#elif NEW
    printf("elif taken\n");
#endif
    printf("line %d\n", __LINE__);
#undef SQUARE
#define SQUARE(x) 0
    printf("%d\n", SQUARE(5));
    EMPTY printf("done\n");
    return 0;
}
