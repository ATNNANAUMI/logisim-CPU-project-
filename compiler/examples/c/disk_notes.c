/* disk_notes.c - files on the disk (simulator only): prints the notes saved
 * in /notes.txt, then adds every line you type to it, so the next run shows
 * them again
 *
 *   python compiler/src/disk format test.img        (once: an empty disk)
 *   python compiler/src/cc build compiler/examples/c/disk_notes.c
 *   python cpu_sim/src/main.py compiler/ROM/disk_notes.rom --disk test.img
 *   (or: python compiler/src/cc run compiler/examples/c/disk_notes.c
 *    --disk test.img --keys $'a note\n!quit\n')
 *
 * Type a line and Enter to save it. !show prints the notes again, !ls lists
 * the disk's root directory, !clear empties the notes, !quit (or Ctrl-D)
 * stops. On the PC: python compiler/src/disk cat test.img /notes.txt
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>

#define NOTES "/notes.txt"

static void show(void)
{
    FILE *f = fopen(NOTES, "r");
    int c, n = 0;
    printf("--- %s ---\n", NOTES);
    if (f) {
        while ((c = fgetc(f)) != EOF) {
            putchar(c);
            n++;
        }
        fclose(f);
    }
    printf("--- %d chars ---\n", n);
}

static void list(void)
{
    DIR *d = opendir("/");
    struct dirent *e;
    while ((e = readdir(d)))
        printf("%8u %s%s\n", e->d_size, e->d_name, e->d_type == DT_DIR ? "/" : "");
    closedir(d);
}

int main(void)
{
    char line[256];
    FILE *f;

    f = fopen(NOTES, "a");              /* also checks the disk */
    if (!f) {
        if (errno == ENODEV)
            printf("no formatted disk: python compiler/src/disk format FILE, "
                   "then run with --disk FILE\n");
        else
            perror(NOTES);
        return 1;
    }
    fclose(f);
    show();
    printf("Type lines to save them (!show, !ls, !clear, !quit).\n");
    while (printf("> "), fgets(line, sizeof line, stdin)) {
        if (strcmp(line, "!quit\n") == 0)
            break;
        if (strcmp(line, "!show\n") == 0) {
            show();
        } else if (strcmp(line, "!ls\n") == 0) {
            list();
        } else if (strcmp(line, "!clear\n") == 0) {
            fclose(fopen(NOTES, "w"));  /* "w" empties it */
            printf("cleared\n");
        } else {
            f = fopen(NOTES, "a");
            fputs(line, f);
            printf("saved (%ld chars)\n", ftell(f));
            fclose(f);
        }
    }
    return 0;
}
