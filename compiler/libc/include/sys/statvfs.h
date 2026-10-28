/* sys/statvfs.h - the size of the disk and its free space (see stdio.h)
 *
 *   struct statvfs s;
 *   if (statvfs("/", &s) == 0)
 *       printf("%u of %u blocks free\n", s.f_bfree, s.f_blocks);
 *
 * Sizes are in blocks of f_bsize chars (256: a char is a word, so a block
 * holds 256 binary words or 1024 chars of a text file). path is any file or
 * directory on the disk; there is only one disk. f_files, f_ffree and
 * f_favail are 0 (no limit on the number of files), f_fsid is the
 * filesystem's magic number. Counting the free blocks reads the whole FAT:
 * 14 instructions a block, 0.9 million on a 64 MB disk (64K blocks).
 * Returns 0, or -1 with errno set (ENODEV: no disk, or not formatted).
 */
#ifndef _SYS_STATVFS_H
#define _SYS_STATVFS_H

typedef unsigned fsblkcnt_t;
typedef unsigned fsfilcnt_t;

struct statvfs {
    unsigned long f_bsize;      /* block size */
    unsigned long f_frsize;     /* the same here */
    fsblkcnt_t f_blocks;        /* blocks on the disk, its own FAT and superblock included */
    fsblkcnt_t f_bfree;         /* free blocks */
    fsblkcnt_t f_bavail;        /* the same here */
    fsfilcnt_t f_files;
    fsfilcnt_t f_ffree;
    fsfilcnt_t f_favail;
    unsigned long f_fsid;
    unsigned long f_flag;
    unsigned long f_namemax;    /* longest name: 127 chars */
};

int statvfs(const char *path, struct statvfs *buf);

#endif
