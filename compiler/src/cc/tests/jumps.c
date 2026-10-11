/* setjmp/longjmp, signal/raise, setlocale */
#include <stdio.h>
#include <setjmp.h>
#include <signal.h>
#include <locale.h>

static jmp_buf env;
static int depth;
static volatile int signalled;

static void dive(int n)
{
    depth = n;
    if (n == 5)
        longjmp(env, n * 10);
    dive(n + 1);
    printf("never printed\n");
}

static void on_signal(int sig)
{
    signalled = sig;
}

int main(void)
{
    volatile int tries = 0;
    int r;
    r = setjmp(env);
    tries++;
    printf("setjmp returned %d (try %d)\n", r, tries);
    if (r == 0)
        dive(1);
    printf("depth %d\n", depth);
    if (setjmp(env) == 0)
        longjmp(env, 0);
    else
        printf("longjmp with 0 gives 1\n");
    signal(SIGINT, on_signal);
    raise(SIGINT);
    printf("signal %d\n", signalled);
    printf("locale %s\n", setlocale(LC_ALL, "C"));
    return 0;
}
