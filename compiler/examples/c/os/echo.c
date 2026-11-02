/* echo.c - a program for the OS (Tynix runs it from /bin; make_disk.py puts
 * it there): prints its arguments on one line, like Unix echo; with none,
 * says how it was called
 *
 *   python compiler/src/cc build compiler/examples/c/os/echo.c --exe
 *   python compiler/src/disk put tynix/disk.img compiler/ROM/echo.exe /bin/echo
 *
 * then, in the shell (or loader.c): echo hello world  ->  hello world
 */
#include <stdio.h>

int main(int argc, char **argv)
{
    int i;
    if (argc < 2) {
        printf("%s: no arguments (argc = %d)\n", argc ? argv[0] : "echo", argc);
        return 1;
    }
    for (i = 1; i < argc; i++)
        printf(i > 1 ? " %s" : "%s", argv[i]);
    printf("\n");
    return 0;
}
