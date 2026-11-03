/* env.c for a program for Tynix (cc build --exe; it replaces
 * compiler/libc/env.c, which it follows line for line): getenv, setenv,
 * unsetenv. environ is sys.c's, set by _tx_start() to the list the kernel
 * copied from the parent (the block's B_ENV). After every change the
 * block's B_ENV points at the new list, so the programs this one starts
 * get it.
 *
 * The first change copies the list into malloc'd memory; strings that
 * setenv made are freed when they are replaced or removed (the others
 * belong to whoever made them).
 */
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/tynix.h>

extern unsigned *_tx_block;     /* sys.c */

static char **list;     /* environ once it is ours, or 0 */
static char *made;      /* made[i]: 1 if setenv malloc'd list[i] */
static int room;        /* how many pointers list holds, its 0 included */

static int named(const char *s, const char *name, int len)
{
    return strncmp(s, name, len) == 0 && s[len] == '=';
}

static int find(const char *name, int len)
{
    int i;
    for (i = 0; environ[i]; i++)
        if (named(environ[i], name, len))
            return i;
    return -1;
}

static int bad_name(const char *name)
{
    if (name == 0 || *name == 0 || strchr(name, '=')) {
        errno = EINVAL;
        return 1;
    }
    return 0;
}

/* make environ our own list with room for one more; 0, or -1 (ENOMEM) */
static int own(void)
{
    int n = 0, i;
    char **l;
    char *m;
    while (environ[n])
        n++;
    if (environ == list && n + 2 <= room)
        return 0;
    l = malloc((n + 9) * sizeof *l);
    m = malloc(n + 9);
    if (l == 0 || m == 0) {
        free(l);
        free(m);
        errno = ENOMEM;
        return -1;
    }
    for (i = 0; i <= n; i++) {
        l[i] = environ[i];
        m[i] = environ == list && made[i];
    }
    free(list);
    free(made);
    environ = list = l;
    made = m;
    room = n + 9;
    _tx_block[B_ENV] = (unsigned)list;      /* what a child gets from now on */
    return 0;
}

char *getenv(const char *name)
{
    int len, i;
    if (name == 0 || environ == 0)
        return 0;
    len = strlen(name);
    i = find(name, len);
    return i < 0 ? 0 : environ[i] + len + 1;
}

int setenv(const char *name, const char *value, int overwrite)
{
    int len, i;
    char *s;
    if (bad_name(name))
        return -1;
    len = strlen(name);
    i = find(name, len);
    if (i >= 0 && !overwrite)
        return 0;
    if (value == 0)
        value = "";
    if ((s = malloc(len + strlen(value) + 2)) == 0) {
        errno = ENOMEM;
        return -1;
    }
    strcpy(s, name);
    s[len] = '=';
    strcpy(s + len + 1, value);
    if (own()) {
        free(s);
        return -1;
    }
    if (i < 0) {
        for (i = 0; list[i]; i++)
            ;
        list[i + 1] = 0;
    } else if (made[i])
        free(list[i]);
    list[i] = s;
    made[i] = 1;
    return 0;
}

int unsetenv(const char *name)
{
    int i;
    if (bad_name(name))
        return -1;
    if ((i = find(name, strlen(name))) < 0)
        return 0;
    if (own())
        return -1;
    if (made[i])
        free(list[i]);
    for (; list[i]; i++) {
        list[i] = list[i + 1];
        made[i] = made[i + 1];
    }
    return 0;
}
