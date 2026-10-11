/* signal, raise: handlers are only called by raise() */
#include <signal.h>
#include <stdlib.h>

static void (*handlers[16])(int);

void (*signal(int sig, void (*handler)(int)))(int)
{
    void (*old)(int);
    if (sig < 1 || sig >= 16)
        return SIG_ERR;
    old = handlers[sig];
    handlers[sig] = handler;
    return old;
}

int raise(int sig)
{
    void (*h)(int);
    if (sig < 1 || sig >= 16)
        return -1;
    h = handlers[sig];
    if (h == SIG_IGN)
        return 0;
    if (h == SIG_DFL)
        _Exit(128 + sig);
    handlers[sig] = SIG_DFL;
    h(sig);
    return 0;
}
