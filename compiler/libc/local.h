/* local.h - shared by the C library's own files (not a public header) */
#ifndef _LIBC_LOCAL_H
#define _LIBC_LOCAL_H

#include <stddef.h>
#include <stdarg.h>

#define _DISPLAY 0x5C
#define _KEYBOARD 0xF0

/* where formatted output goes: a file on the disk (file != 0), the display
   (buf == 0) or a string */
typedef struct {
    struct _FILE *file;
    char *buf;
    size_t size;        /* room in buf, the final 0 included */
    size_t len;         /* characters produced so far (even past size) */
} _Sink;

int _format(_Sink *out, const char *fmt, va_list ap);

/* float -> decimal digits, exactly. Fills digits[] (characters '0'..'9')
   and returns how many; *point = how many of them come before the
   decimal point (can be <= 0 or more than the count). */
int _float_digits(float x, char *digits, int max, int *point, int mode, int prec);
#define _FIXED 0        /* prec digits after the decimal point */
#define _SCIENTIFIC 1   /* prec + 1 significant digits */

int _read_key(void);    /* wait for a key, no echo */

/* what FILE is (stdio.h only names it). stdin, stdout and stderr use only
   the first three fields; a file on the disk (fs.c) sets get/put/flush, so
   the stdio functions reach fs.c through them and a program that never
   calls fopen doesn't link it. */
struct _FILE {
    int output;          /* 1 for stdout/stderr and files open for writing */
    int eof;
    int error;
    int (*get)(struct _FILE *);
    int (*put)(int, struct _FILE *);
    int (*flush)(struct _FILE *);
    int input;           /* open for reading */
    int append;          /* every write goes to the end */
    int packed;          /* a text file: 4 chars a word */
    int pushed;          /* ungetc's char, or EOF */
    unsigned pos;        /* where the next char (or word) is */
    unsigned first, length, flags;      /* as in the file's directory entry */
    unsigned dir_first, index;          /* where that entry is */
    unsigned word_at;    /* packed files: which word `word` holds (-1: none) */
    unsigned word;
    int word_dirty;
    int entry_dirty;     /* first or length changed since the entry was saved */
};

/* the filesystem (fs.c, TFS1: the format is in compiler/src/disk/fs.py) */
#define _FS_BLOCK 256
#define _FS_ENTRY 132
#define _FS_NAME 128         /* name words in an entry: up to 127 chars + 0 */
#define _FS_USED 1
#define _FS_DIR 2
#define _FS_PACKED 4
#define _FS_PATH 512         /* longest path, its final 0 included */

typedef struct {
    unsigned first, length, flags;
    unsigned dir_first, index;      /* where its entry is */
    int root;                       /* the root directory: its entry is the superblock */
} _Node;

int _fs_mount(void);
unsigned _fs_word(unsigned first, unsigned offset);     /* a word of a chain (0 past its end) */
int _fs_lookup(const char *path, _Node *node);          /* 0, or -1 with errno set */
int _fs_parent(const char *path, _Node *dir, char *name);
int _fs_add(_Node *dir, const char *name, unsigned flags, _Node *node);
void _fs_save(_Node *node);
void _fs_unlink(_Node *node);   /* free its blocks and its entry */
int _fs_empty(_Node *dir);
int _fs_normalize(const char *path, char *out);
extern char _fs_cwd[_FS_PATH];

#endif
