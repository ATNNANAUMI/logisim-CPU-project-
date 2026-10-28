/* dirent.h - list a directory on the disk (see stdio.h)
 *
 *   DIR *d = opendir("/notes");
 *   struct dirent *e;
 *   while ((e = readdir(d)))
 *       printf("%s %d\n", e->d_name, e->d_size);
 *   closedir(d);
 *
 * d_type is DT_DIR or DT_REG; d_size (not standard) is the length: chars
 * for a text file, words for a binary one or a directory. "." and ".." are
 * not listed. At most 4 directories are open at once.
 */
#ifndef _DIRENT_H
#define _DIRENT_H

#define DT_DIR 4
#define DT_REG 8

struct dirent {
    char d_name[128];
    int d_type;
    unsigned d_size;
};

typedef struct _DIR DIR;

DIR *opendir(const char *path);
struct dirent *readdir(DIR *dir);
int closedir(DIR *dir);

#endif
