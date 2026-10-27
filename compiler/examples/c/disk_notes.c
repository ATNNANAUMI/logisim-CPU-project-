/* disk_notes.c - the disk device (simulator only): prints the text saved on
 * the disk, then saves every line you type, so the next run shows it again
 *
 *   python compiler/src/cc run compiler/examples/c/disk_notes.c --disk test.img
 *   (or, after cc run/build: python cpu_sim/src/main.py compiler/ROM/disk_notes.rom
 *    --disk test.img, or the window's "disk" button)
 *
 * Type a line and Enter to save it. !show prints the disk again, !clear
 * erases it, !quit (or Ctrl-D) stops. Without --disk: "no disk".
 *
 * On the disk: word 0 = MAGIC, word 1 = how many chars, then the chars, one
 * per word. A new disk is all zeros, so it reads as empty.
 */
#include <stdio.h>
#include <string.h>
#include <cpu.h>

#define MAGIC 0x4E4F5445        /* "NOTE" */
#define TEXT 2                  /* the word where the text starts */

static int size;                /* the disk's size in words */
static int length;              /* chars saved on the disk */

static void seek(int word)
{
    device_out(DISK_SEEK_DEVICE, word);
}

static void load(void)
{
    seek(0);
    if (device_in(DISK_DATA_DEVICE) == MAGIC)
        length = device_in(DISK_DATA_DEVICE);   /* the position moves on by itself */
    else
        length = 0;
}

static void show(void)
{
    int i;
    printf("--- on the disk: %d chars ---\n", length);
    seek(TEXT);
    for (i = 0; i < length; i++)
        putchar(device_in(DISK_DATA_DEVICE));
    printf("--- end ---\n");
}

/* the text first, then the length: a run stopped halfway loses only the new line */
static void save(const char *line)
{
    int n = strlen(line);
    int i;
    if (TEXT + length + n > size) {
        printf("disk full\n");
        return;
    }
    seek(TEXT + length);
    for (i = 0; i < n; i++)
        device_out(DISK_DATA_DEVICE, line[i]);
    length += n;
    seek(0);
    device_out(DISK_DATA_DEVICE, MAGIC);
    device_out(DISK_DATA_DEVICE, length);
}

int main(void)
{
    char line[256];

    size = device_in(DISK_SEEK_DEVICE);         /* 0: no disk attached */
    if (size == 0) {
        printf("no disk (run with --disk FILE)\n");
        return 1;
    }
    load();
    show();
    printf("Type lines to save them (!show, !clear, !quit).\n");
    while (printf("> "), fgets(line, sizeof line, stdin)) {
        if (strcmp(line, "!quit\n") == 0)
            break;
        if (strcmp(line, "!show\n") == 0) {
            show();
        } else if (strcmp(line, "!clear\n") == 0) {
            length = 0;
            seek(0);
            device_out(DISK_DATA_DEVICE, 0);    /* no MAGIC: reads as empty */
            printf("erased\n");
        } else {
            save(line);
            printf("saved (%d chars on the disk)\n", length);
        }
    }
    return 0;
}
