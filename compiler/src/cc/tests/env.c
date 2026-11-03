/* getenv, setenv, unsetenv (stdlib.h): names a program sets for itself.
   Only names made up here are looked at, so the output is the same
   whatever environment gcc's build starts with. */
#define _POSIX_C_SOURCE 200112L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static void show(const char *name)
{
    const char *v = getenv(name);
    printf("%s: %s\n", name, v ? v : "(not set)");
}

int main(void)
{
    int i;
    char name[32], value[32];
    show("TINYC_A");
    printf("set: %d\n", setenv("TINYC_A", "one", 1));
    show("TINYC_A");
    printf("no overwrite: %d\n", setenv("TINYC_A", "two", 0));
    show("TINYC_A");
    printf("overwrite: %d\n", setenv("TINYC_A", "three", 1));
    show("TINYC_A");
    printf("empty value: %d\n", setenv("TINYC_B", "", 1));
    show("TINYC_B");
    errno = 0;
    printf("name with =: %d", setenv("TINYC_C=x", "y", 1));
    printf(" errno EINVAL: %d\n", errno == EINVAL);
    errno = 0;
    printf("empty name: %d", setenv("", "y", 1));
    printf(" errno EINVAL: %d\n", errno == EINVAL);
    show("TINYC_C=x");
    show("TINYC");                      /* a prefix of TINYC_A is not it */
    for (i = 0; i < 40; i++) {          /* the list grows past its first room */
        sprintf(name, "TINYC_N%d", i);
        sprintf(value, "%d", i * i);
        setenv(name, value, 1);
    }
    show("TINYC_N0");
    show("TINYC_N39");
    printf("unset: %d\n", unsetenv("TINYC_A"));
    show("TINYC_A");
    show("TINYC_B");
    printf("unset again: %d\n", unsetenv("TINYC_A"));
    for (i = 0; i < 40; i += 2) {
        sprintf(name, "TINYC_N%d", i);
        unsetenv(name);
    }
    show("TINYC_N20");
    show("TINYC_N21");
    show("TINYC_N39");
    return 0;
}
