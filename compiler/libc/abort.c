/* abort, __assert_fail, system (getenv is in env.c) */
#include <stdlib.h>
#include <stdio.h>

void abort(void)
{
    fputs("Aborted\n", stderr);
    _Exit(134);
}

void __assert_fail(const char *expr, const char *file, int line, const char *func)
{
    fprintf(stderr, "%s:%d: %s: Assertion `%s' failed.\n", file, line, func, expr);
    abort();
}

int system(const char *command)
{
    return command == 0 ? 0 : -1;
}
