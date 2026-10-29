/* sys/stat.h - what a file on the disk is (see stdio.h)
 *
 *   struct stat st;
 *   if (stat("/notes.txt", &st) == 0 && S_ISREG(st.st_mode))
 *       printf("%u chars%s\n", st.st_size, S_ISTEXT(st.st_mode) ? "" : " (words)");
 *
 * st_size is the length the directory keeps: chars for a text file (the
 * kind fopen makes with "w"), words for a binary one ("wb"). S_ISTEXT is
 * not standard: it tells the two apart (a text file packs 4 chars a word,
 * so copying one as words, or reading a program as text, goes wrong). A
 * directory is neither. There are no times, owners or permissions; st_mode
 * has only the type and S_ISTEXT, st_ino is the file's first block (0: an
 * empty file), st_nlink is 1 and st_blksize is 256. For a directory st_size
 * is the words its entries take (132 an entry).
 * Returns 0, or -1 with errno set (ENOENT, ENOTDIR, ENODEV).
 */
#ifndef _SYS_STAT_H
#define _SYS_STAT_H

typedef unsigned mode_t;
typedef unsigned ino_t;

#define S_IFMT   0170000
#define S_IFDIR  0040000
#define S_IFREG  0100000
#define S_ITEXT  0001000        /* not standard: a text file (packed) */

#define S_ISDIR(m)  (((m) & S_IFMT) == S_IFDIR)
#define S_ISREG(m)  (((m) & S_IFMT) == S_IFREG)
#define S_ISTEXT(m) (((m) & S_ITEXT) != 0)

struct stat {
    mode_t st_mode;
    ino_t st_ino;
    unsigned st_nlink;
    unsigned st_size;
    unsigned st_blksize;
    unsigned st_blocks;         /* 256-word blocks the file takes */
};

int stat(const char *path, struct stat *buf);

#endif
