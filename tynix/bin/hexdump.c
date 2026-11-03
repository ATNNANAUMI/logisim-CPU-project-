/* hexdump.c - show the values in files as hexadecimal (a program for Tynix, in /bin)
 *
 *   python tynix/make_disk.py              (builds it into /bin)
 *   (in the shell)   hexdump file...
 *
 *   000000: 00000068 00000065 0000006c 0000006c 0000006f 0000000a 00000000 00000000  hello.
 *
 * 8 values a line: the number of the first one as %06x and a colon, the
 * values as %08x, then a column with the char of each value (a dot for the
 * ones outside 32-126). Any file works: a text file gives its chars (the
 * disk packs 4 a word, but fgetc unpacks them), a binary file (a program)
 * gives its whole words. With several files each starts with `name:`.
 *
 * A full line is 89 columns wide, more than the circuit's 64-column text
 * display (it wraps there); change PER_LINE to 4 for a display-sized dump.
 *
 * Errors: hexdump: PATH: reason, the other files go on, exit status 1.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>

#define PER_LINE 8

static int dump(const char *name)
{
    struct stat st;
    FILE *f;
    unsigned value[PER_LINE];
    unsigned offset = 0;
    int c, n, i;
    if (stat(name, &st)) {
        printf("hexdump: %s: %s\n", name, strerror(errno));
        return 1;
    }
    if (!S_ISREG(st.st_mode)) {
        printf("hexdump: %s: not a file\n", name);
        return 1;
    }
    if ((f = fopen(name, S_ISTEXT(st.st_mode) ? "r" : "rb")) == 0) {
        printf("hexdump: %s: %s\n", name, strerror(errno));
        return 1;
    }
    n = 0;
    for (;;) {
        c = fgetc(f);
        if (c == EOF && feof(f))        /* a binary word of -1 reads as EOF too */
            break;
        value[n++] = c;
        if (n == PER_LINE) {
            printf("%06x:", offset);
            for (i = 0; i < n; i++)
                printf(" %08x", value[i]);
            printf("  ");
            for (i = 0; i < n; i++)
                putchar(value[i] >= 32 && value[i] <= 126 ? value[i] : '.');
            printf("\n");
            offset += n;
            n = 0;
        }
    }
    if (n) {
        printf("%06x:", offset);
        for (i = 0; i < PER_LINE; i++)
            if (i < n)
                printf(" %08x", value[i]);
            else
                printf("         ");
        printf("  ");
        for (i = 0; i < n; i++)
            putchar(value[i] >= 32 && value[i] <= 126 ? value[i] : '.');
        printf("\n");
    }
    c = ferror(f);
    fclose(f);
    if (c) {
        printf("hexdump: %s: read error\n", name);
        return 1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    int i, status = 0;
    if (argc < 2) {
        printf("usage: hexdump file...\n");
        return 1;
    }
    for (i = 1; i < argc; i++) {
        if (argc > 2)
            printf("%s:\n", argv[i]);
        status |= dump(argv[i]);
    }
    return status;
}
