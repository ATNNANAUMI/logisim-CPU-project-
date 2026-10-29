/* loader.c - runs programs from the disk (simulator only): type a program's
 * name and its arguments, it is loaded from /bin and run with spawnv(), and
 * its exit status is shown; then the next one. A first step towards the
 * OS's shell.
 *
 *   python compiler/src/disk format test.img        (once: an empty disk)
 *   python compiler/src/disk mkdir test.img /bin
 *   python compiler/src/cc build compiler/examples/c/os/echo.c --exe
 *   python compiler/src/disk put test.img compiler/ROM/echo.exe /bin/echo
 *   (any C program works: cc build compiler/examples/c/basics/primes.c --exe, ...)
 *   python compiler/src/cc build compiler/examples/c/os/loader.c
 *   python cpu_sim/src/main.py compiler/ROM/loader.rom --disk test.img
 *   (or: python compiler/src/cc run compiler/examples/c/os/loader.c
 *    --disk test.img --keys $'echo hello world\n\x04')
 *
 * A name with a '/' is a path (/bin/echo, ../x); without, it is looked up
 * in /bin. An empty line lists /bin; Ctrl-D stops.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <unistd.h>

#define MAX_ARGS 16

static void list_bin(void)
{
    DIR *d = opendir("/bin");
    struct dirent *e;
    if (d == 0) {
        printf("no /bin: %s\n", strerror(errno));
        return;
    }
    printf("programs in /bin:");
    while ((e = readdir(d)))
        printf(" %s", e->d_name);
    printf("\n");
    closedir(d);
}

int main(void)
{
    char line[200], path[220], *argv[MAX_ARGS + 1];
    int argc, status;
    for (;;) {
        printf("run> ");
        if (fgets(line, sizeof line, stdin) == 0)
            return 0;
        argc = 0;
        argv[0] = strtok(line, " \n");
        while (argv[argc] && argc < MAX_ARGS)
            argv[++argc] = strtok(0, " \n");
        argv[argc] = 0;
        if (argc == 0) {
            list_bin();
            continue;
        }
        if (strchr(argv[0], '/'))
            strcpy(path, argv[0]);
        else
            sprintf(path, "/bin/%s", argv[0]);
        status = spawnv(path, argv);
        if (status == -1 && errno)
            printf("%s: %s\n", path, strerror(errno));
        else
            printf("[%s: exit status %d]\n", argv[0], status);
        errno = 0;
    }
}
