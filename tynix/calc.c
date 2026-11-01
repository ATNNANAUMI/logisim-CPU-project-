/* calc.c - a 32-bit integer calculator (a program for Tynix, in /bin)
 *
 *   python tynix/make_disk.py              (builds it into /bin)
 *   (in the shell)   calc expr        calc 2 * (3 + 4)  ->  14
 *                    calc             type an expression a line, Ctrl-D ends
 *
 * The result is printed in decimal; when the 32-bit value is negative as a
 * signed number, its unsigned value follows:  calc -1  ->  -1 (4294967295 unsigned)
 *
 * Numbers: decimal, 0x hex, 0b binary, 'c' a char ('\n' '\t' '\\' '\'' '\0'
 * work too). Operators, from tight to loose, as in C:
 *     ( )   unary - + ~   * / %   + -   << >>   &   ^   |
 * Values are 32 bits and wrap round; / and % are signed and truncate toward
 * zero, >> copies the sign bit, a shift count is 0 to 31. A division by zero,
 * a number past 32 bits or a bad character gives an error message, not a crash.
 *
 * The shell splits the line into words and joins them again with spaces, so
 * `calc 2 * (3 + 4)` works as typed. Two things the shell itself takes: a >
 * starts a redirect, so quote an expression with a shift: calc "256 >> 4";
 * and it removes quotes, so write a char as calc "'a'" (typed to calc with no
 * argument, 'a' needs no care).
 *
 * Exit status: 0, or 1 for an error in `calc expr` (with no argument, 0).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define LINE_MAX 256

static const char *p;           /* the next char of the expression */
static const char *error;       /* what went wrong, 0 if nothing */
static int bad;                 /* the char it went wrong at, or 0 */

static void space(void)
{
    while (*p == ' ' || *p == '\t')
        p++;
}

static unsigned expr(int level);

static int digit(int c, int base)
{
    int v;
    if (c >= '0' && c <= '9')
        v = c - '0';
    else if (c >= 'a' && c <= 'f')
        v = c - 'a' + 10;
    else if (c >= 'A' && c <= 'F')
        v = c - 'A' + 10;
    else
        return -1;
    return v < base ? v : -1;
}

static unsigned number(void)
{
    unsigned v = 0;
    int base = 10, d, any = 0;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X'))
        base = 16, p += 2;
    else if (p[0] == '0' && (p[1] == 'b' || p[1] == 'B'))
        base = 2, p += 2;
    while ((d = digit(*p, base)) >= 0) {
        if (v > (0xFFFFFFFFu - d) / base) {
            error = "number does not fit in 32 bits";
            return 0;
        }
        v = v * base + d;
        p++;
        any = 1;
    }
    if (!any || isalnum(*p) || *p == '_') {
        error = "bad number";
        return 0;
    }
    return v;
}

static unsigned character(void)
{
    unsigned v;
    p++;                                /* the opening ' */
    if (*p == '\\') {
        p++;
        switch (*p) {
        case 'n': v = '\n'; break;
        case 't': v = '\t'; break;
        case '0': v = 0; break;
        case '\\': case '\'': v = *p; break;
        default:
            error = "unknown escape in a char";
            return 0;
        }
    } else if (*p && *p != '\'')
        v = *p;
    else {
        error = "empty char";
        return 0;
    }
    p++;
    if (*p != '\'') {
        error = "missing ' after the char";
        return 0;
    }
    p++;
    return v;
}

static unsigned primary(void)
{
    unsigned v;
    space();
    if (*p == '(') {
        p++;
        v = expr(0);
        space();
        if (error)
            return 0;
        if (*p != ')') {
            error = "missing )";
            return 0;
        }
        p++;
        return v;
    }
    if (*p == '-') {
        p++;
        return -primary();
    }
    if (*p == '+') {
        p++;
        return primary();
    }
    if (*p == '~') {
        p++;
        return ~primary();
    }
    if (*p == '\'')
        return character();
    if (isdigit(*p))
        return number();
    if (*p == 0)
        error = "the expression ends too soon";
    else {
        error = "unexpected character";
        bad = *p;
    }
    return 0;
}

/* binary operators by level: 1 | , 2 ^ , 3 & , 4 << >> , 5 + - , 6 * / % */
static int op_level(int *len)
{
    space();
    *len = 1;
    switch (*p) {
    case '|': return 1;
    case '^': return 2;
    case '&': return 3;
    case '+': case '-': return 5;
    case '*': case '/': case '%': return 6;
    case '<':
        if (p[1] == '<') {
            *len = 2;
            return 4;
        }
        break;
    case '>':
        if (p[1] == '>') {
            *len = 2;
            return 4;
        }
        break;
    }
    return 0;
}

static unsigned apply(char op, unsigned a, unsigned b)
{
    int x = a, y = b;
    switch (op) {
    case '|': return a | b;
    case '^': return a ^ b;
    case '&': return a & b;
    case '+': return a + b;
    case '-': return a - b;
    case '*': return a * b;
    case '<':
    case '>':
        if (b > 31) {
            error = "a shift count is 0 to 31";
            return 0;
        }
        return op == '<' ? a << b : x >> b;
    }
    if (y == 0) {
        error = "division by zero";
        return 0;
    }
    if (x == (int)0x80000000 && y == -1)        /* the one case that overflows */
        return op == '/' ? a : 0;
    return op == '/' ? x / y : x % y;
}

/* an expression whose operators are at least `level` (0: any) */
static unsigned expr(int level)
{
    unsigned left = primary(), right;
    int len, here;
    char c;
    while (!error && (here = op_level(&len)) > 0 && here >= level) {
        c = *p;
        p += len;
        right = expr(here + 1);
        if (error)
            return 0;
        left = apply(c, left, right);
    }
    return left;
}

/* evaluate s and print the result; 0, or -1 after printing the error */
static int calc(const char *s)
{
    unsigned v;
    p = s;
    error = 0;
    bad = 0;
    v = expr(0);
    space();
    if (!error && *p) {
        error = *p == ')' ? "unmatched )" : "unexpected character";
        bad = *p == ')' ? 0 : *p;
    }
    if (error) {
        if (bad)
            printf("calc: %s '%c'\n", error, bad);
        else
            printf("calc: %s\n", error);
        return -1;
    }
    if ((int)v < 0)
        printf("%d (%u unsigned)\n", (int)v, v);
    else
        printf("%d\n", (int)v);
    return 0;
}

int main(int argc, char **argv)
{
    static char line[LINE_MAX];
    int i, n = 0;
    if (argc > 1) {
        for (i = 1; i < argc; i++) {
            if (n + strlen(argv[i]) + 2 > LINE_MAX) {
                printf("calc: the expression is longer than %d chars\n", LINE_MAX - 1);
                return 1;
            }
            n += sprintf(line + n, i > 1 ? " %s" : "%s", argv[i]);
        }
        return calc(line) ? 1 : 0;
    }
    for (;;) {
        printf("calc> ");
        if (fgets(line, sizeof line, stdin) == 0)
            break;
        line[strcspn(line, "\n")] = 0;
        p = line;
        space();
        if (*p)
            calc(line);
    }
    clearerr(stdin);
    printf("\n");
    return 0;
}
