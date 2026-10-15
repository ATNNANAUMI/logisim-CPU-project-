/* a recursive-descent calculator for integer expressions */
#include <stdio.h>
#include <ctype.h>

static const char *p;
static int error;

static int expr(void);

static void skip(void)
{
    while (*p == ' ')
        p++;
}

static int primary(void)
{
    int v = 0;
    skip();
    if (*p == '(') {
        p++;
        v = expr();
        skip();
        if (*p == ')')
            p++;
        else
            error = 1;
        return v;
    }
    if (*p == '-') {
        p++;
        return -primary();
    }
    if (!isdigit(*p)) {
        error = 1;
        return 0;
    }
    while (isdigit(*p))
        v = v * 10 + (*p++ - '0');
    return v;
}

static int term(void)
{
    int v = primary();
    for (;;) {
        skip();
        if (*p == '*') {
            p++;
            v *= primary();
        } else if (*p == '/') {
            int d;
            p++;
            d = primary();
            if (d == 0) {
                error = 2;
                return 0;
            }
            v /= d;
        } else if (*p == '%') {
            p++;
            v %= primary();
        } else {
            return v;
        }
    }
}

static int expr(void)
{
    int v = term();
    for (;;) {
        skip();
        if (*p == '+') {
            p++;
            v += term();
        } else if (*p == '-') {
            p++;
            v -= term();
        } else {
            return v;
        }
    }
}

int main(void)
{
    static const char *tests[] = {
        "1 + 2 * 3", "(1 + 2) * 3", "100 / 7 % 4", "-(3 - 10) * -2",
        "2 * (3 + (4 - 1) * 5) - 6", "8 / 0", "(1 + 2", "42",
    };
    int i;
    for (i = 0; i < (int)(sizeof tests / sizeof tests[0]); i++) {
        int v;
        p = tests[i];
        error = 0;
        v = expr();
        if (error == 2)
            printf("%-28s division by zero\n", tests[i]);
        else if (error || *p)
            printf("%-28s syntax error\n", tests[i]);
        else
            printf("%-28s = %d\n", tests[i], v);
    }
    return 0;
}
