/* abort, __assert_fail, getenv, system */
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

char *getenv(const char *name)
{
    (void)name;
    return 0;
}

int system(const char *command)
{
    return command == 0 ? 0 : -1;
}
