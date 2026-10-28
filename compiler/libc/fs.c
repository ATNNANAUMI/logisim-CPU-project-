/* fs.c - files on the disk: fopen, fclose, fseek, ftell, rewind, remove,
 * rename, and the filesystem under them (also used by dir.c).
 *
 * The disk is the simulator's disk device (0x8C seek, 0x8D data; run with
 * --disk FILE). Its filesystem is TFS1; compiler/src/disk/fs.py is the
 * reference for the format and makes disks (python compiler/src/disk format).
 * Blocks of 256 words are chained by a FAT; a directory is a file of
 * 132-word entries; a text file holds 4 chars a word, a binary file ("b"
 * in the mode) one word per char.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "local.h"

#define SEEK_PORT 0x8C
#define DATA_PORT 0x8D
#define MAGIC 0x31534654        /* "TFS1" */
#define END 0xFFFFFFFF
#define E_FIRST 128             /* words of an entry after the name */
#define E_LENGTH 129
#define E_FLAGS 130
#define SB_ROOT 6               /* superblock: the root's first block, length */
#define SB_ROOT_LEN 7
#define MAX_OPEN 8

char _fs_cwd[_FS_PATH] = "/";

static int mounted;
static unsigned blocks, fat_start, hint;
static unsigned cache_first, cache_n, cache_block;     /* the last _fs_block() walk */
static FILE files[MAX_OPEN];
static int in_use[MAX_OPEN];
static int closer_set;

static unsigned disk_read(unsigned addr)
{
    __builtin_out(SEEK_PORT, addr);
    return __builtin_in(DATA_PORT);
}

static void disk_write(unsigned addr, unsigned value)
{
    __builtin_out(SEEK_PORT, addr);
    __builtin_out(DATA_PORT, value);
}

int _fs_mount(void)
{
    if (mounted)
        return 0;
    if (__builtin_in(SEEK_PORT) == 0 || disk_read(0) != MAGIC
            || disk_read(1) != 1 || disk_read(2) != _FS_BLOCK) {
        errno = ENODEV;         /* no disk, or not formatted */
        return -1;
    }
    blocks = disk_read(3);
    fat_start = disk_read(4);
    mounted = 1;
    return 0;
}

/* ------------------------------------------------------------ blocks */

static unsigned fat(unsigned block)
{
    return disk_read(fat_start * _FS_BLOCK + block);
}

static void set_fat(unsigned block, unsigned value)
{
    disk_write(fat_start * _FS_BLOCK + block, value);
}

/* a free block, filled with zeros and marked as a chain's end; 0 if the disk is full */
static unsigned alloc(void)
{
    unsigned n, b, i;
    for (n = 0; n < blocks; n++) {
        b = (hint + n) % blocks;
        if (fat(b) == 0) {
            set_fat(b, END);
            hint = b + 1;
            __builtin_out(SEEK_PORT, b * _FS_BLOCK);
            for (i = 0; i < _FS_BLOCK; i++)
                __builtin_out(DATA_PORT, 0);    /* the position moves on by itself */
            return b;
        }
    }
    errno = ENOSPC;
    return 0;
}

static void free_chain(unsigned first)
{
    unsigned b = first, next;
    while (b != 0 && b != END) {
        next = fat(b);
        set_fat(b, 0);
        b = next;
    }
    hint = 0;
    cache_first = 0;
}

/* block n of a chain, or 0 past its end */
static unsigned nth_block(unsigned first, unsigned n)
{
    unsigned b = first, i = 0;
    if (first == 0)
        return 0;
    if (cache_first == first && cache_n <= n) {
        b = cache_block;
        i = cache_n;
    }
    for (; i < n; i++) {
        b = fat(b);
        if (b == END)
            return 0;
    }
    cache_first = first;
    cache_n = n;
    cache_block = b;
    return b;
}

unsigned _fs_word(unsigned first, unsigned offset)
{
    unsigned b = nth_block(first, offset / _FS_BLOCK);
    return b ? disk_read(b * _FS_BLOCK + offset % _FS_BLOCK) : 0;
}

/* the disk address of word `offset` of a node, adding blocks as needed
   (a node that had none gets its first block, saved to its entry);
   0 if the disk is full */
static unsigned word_addr(_Node *node, unsigned offset)
{
    unsigned n = offset / _FS_BLOCK, b, next, i;
    if (node->first == 0) {
        b = alloc();
        if (b == 0)
            return 0;
        node->first = b;
        _fs_save(node);
    }
    b = nth_block(node->first, n);
    if (b == 0) {                       /* past the end: walk to the last block, then grow */
        b = node->first;
        for (i = 0; i < n; i++) {
            next = fat(b);
            if (next == END) {
                next = alloc();
                if (next == 0)
                    return 0;
                set_fat(b, next);
            }
            b = next;
        }
        cache_first = 0;
    }
    return b * _FS_BLOCK + offset % _FS_BLOCK;
}

static int write_word(_Node *node, unsigned offset, unsigned value)
{
    unsigned addr = word_addr(node, offset);
    if (addr == 0)
        return -1;
    disk_write(addr, value);
    return 0;
}

/* ------------------------------------------------------------ directories */

/* a word of an entry that exists (never adds blocks) */
static void set_entry_word(unsigned dir_first, unsigned offset, unsigned value)
{
    unsigned b = nth_block(dir_first, offset / _FS_BLOCK);
    if (b)
        disk_write(b * _FS_BLOCK + offset % _FS_BLOCK, value);
}

void _fs_save(_Node *node)
{
    unsigned base;
    if (node->root) {
        disk_write(SB_ROOT, node->first);
        disk_write(SB_ROOT_LEN, node->length);
        return;
    }
    base = node->index * _FS_ENTRY;
    set_entry_word(node->dir_first, base + E_FIRST, node->first);
    set_entry_word(node->dir_first, base + E_LENGTH, node->length);
    set_entry_word(node->dir_first, base + E_FLAGS, node->flags);
}

static void root(_Node *node)
{
    node->first = disk_read(SB_ROOT);
    node->length = disk_read(SB_ROOT_LEN);
    node->flags = _FS_USED | _FS_DIR;
    node->root = 1;
}

/* the entry called name in dir; returns 0 and fills node (which can be
   dir itself), or -1 */
static int find(_Node *dir, const char *name, _Node *node)
{
    unsigned first = dir->first, count = dir->length / _FS_ENTRY, i, k, base;
    for (i = 0; i < count; i++) {
        base = i * _FS_ENTRY;
        if (!(_fs_word(first, base + E_FLAGS) & _FS_USED))
            continue;
        for (k = 0; k < _FS_NAME; k++) {
            unsigned c = _fs_word(first, base + k);
            if (c != (unsigned)name[k])
                break;
            if (c == 0) {
                node->first = _fs_word(first, base + E_FIRST);
                node->length = _fs_word(first, base + E_LENGTH);
                node->flags = _fs_word(first, base + E_FLAGS);
                node->dir_first = first;
                node->index = i;
                node->root = 0;
                return 0;
            }
        }
    }
    return -1;
}

/* add the names of p to the path out[0 .. *len], working out "." and ".." */
static int add_names(char *out, int *len, const char *p)
{
    while (*p) {
        const char *q;
        int n;
        while (*p == '/')
            p++;
        q = p;
        while (*q && *q != '/')
            q++;
        n = q - p;
        if (n == 0 || (n == 1 && p[0] == '.')) {
            /* nothing */
        } else if (n == 2 && p[0] == '.' && p[1] == '.') {
            while (*len > 0 && out[*len - 1] != '/')
                (*len)--;
            if (*len > 0)
                (*len)--;               /* the '/' before the name */
        } else {
            if (n >= _FS_NAME || *len + 1 + n >= _FS_PATH) {
                errno = ENAMETOOLONG;
                return -1;
            }
            out[*len] = '/';
            memcpy(out + *len + 1, p, n);
            *len += 1 + n;
        }
        p = q;
    }
    return 0;
}

/* path (from the root, or from the current directory) -> "/a/b" with
   "." and ".." worked out; -1 if it is too long or a name is */
int _fs_normalize(const char *path, char *out)
{
    int len = 0;
    if (path[0] != '/' && add_names(out, &len, _fs_cwd))
        return -1;
    if (add_names(out, &len, path))
        return -1;
    if (len == 0)
        out[len++] = '/';
    out[len] = 0;
    return 0;
}

int _fs_lookup(const char *path, _Node *node)
{
    char full[_FS_PATH], name[_FS_NAME];
    const char *p;
    if (_fs_mount() || _fs_normalize(path, full))
        return -1;
    root(node);
    for (p = full; *p; ) {
        int n = 0;
        while (*p == '/')
            p++;
        if (!*p)
            break;
        while (*p && *p != '/')
            name[n++] = *p++;
        name[n] = 0;
        if (!(node->flags & _FS_DIR)) {
            errno = ENOTDIR;
            return -1;
        }
        if (find(node, name, node)) {
            errno = ENOENT;
            return -1;
        }
    }
    return 0;
}

/* the directory a new path goes into, and its last name */
int _fs_parent(const char *path, _Node *dir, char *name)
{
    char full[_FS_PATH];
    char *slash;
    const char *c;
    if (_fs_mount() || _fs_normalize(path, full))
        return -1;
    slash = strrchr(full, '/');
    strcpy(name, slash + 1);
    if (!name[0]) {                     /* the root itself */
        errno = EISDIR;
        return -1;
    }
    for (c = name; *c; c++)
        if (*c == ' ' || (unsigned)*c < 32) {
            errno = EINVAL;
            return -1;
        }
    if (slash == full)
        slash[1] = 0;                   /* "/name" -> "/" */
    else
        *slash = 0;
    if (_fs_lookup(full, dir))
        return -1;
    if (!(dir->flags & _FS_DIR)) {
        errno = ENOTDIR;
        return -1;
    }
    return 0;
}

/* a new entry in dir (reusing a deleted one) */
int _fs_add(_Node *dir, const char *name, unsigned flags, _Node *node)
{
    unsigned count = dir->length / _FS_ENTRY, i, k, base;
    int ended = 0;
    for (i = 0; i < count; i++)
        if (!(_fs_word(dir->first, i * _FS_ENTRY + E_FLAGS) & _FS_USED))
            break;
    base = i * _FS_ENTRY;
    for (k = 0; k < _FS_ENTRY; k++) {
        unsigned c = 0;
        if (k < _FS_NAME && !ended) {
            c = (unsigned)name[k];
            ended = c == 0;
        } else if (k == E_FLAGS) {
            c = flags | _FS_USED;
        }
        if (write_word(dir, base + k, c))
            return -1;
    }
    if (i == count) {
        dir->length += _FS_ENTRY;
        _fs_save(dir);
    }
    node->first = 0;
    node->length = 0;
    node->flags = flags | _FS_USED;
    node->dir_first = dir->first;
    node->index = i;
    node->root = 0;
    return 0;
}

void _fs_unlink(_Node *node)
{
    free_chain(node->first);
    node->first = 0;
    node->length = 0;
    node->flags = 0;
    _fs_save(node);
}

int _fs_empty(_Node *dir)
{
    unsigned count = dir->length / _FS_ENTRY, i;
    for (i = 0; i < count; i++)
        if (_fs_word(dir->first, i * _FS_ENTRY + E_FLAGS) & _FS_USED)
            return 0;
    return 1;
}

/* ------------------------------------------------------------ open files */

static void node_of(FILE *f, _Node *node)
{
    node->first = f->first;
    node->length = f->length;
    node->flags = f->flags;
    node->dir_first = f->dir_first;
    node->index = f->index;
    node->root = 0;
}

static unsigned file_addr(FILE *f, unsigned offset)
{
    _Node node;
    unsigned addr;
    node_of(f, &node);
    addr = word_addr(&node, offset);
    f->first = node.first;
    return addr;
}

static int flush_word(FILE *f)
{
    unsigned addr;
    if (!f->word_dirty)
        return 0;
    addr = file_addr(f, f->word_at);
    if (addr == 0) {
        f->error = 1;
        return -1;
    }
    disk_write(addr, f->word);
    f->word_dirty = 0;
    return 0;
}

static int load_word(FILE *f, unsigned at)
{
    if (f->word_at == at)
        return 0;
    if (flush_word(f))
        return -1;
    f->word = _fs_word(f->first, at);
    f->word_at = at;
    return 0;
}

static int file_flush(FILE *f)
{
    _Node node;
    if (flush_word(f))
        return EOF;
    if (f->entry_dirty) {
        node_of(f, &node);
        _fs_save(&node);
        f->entry_dirty = 0;
    }
    return 0;
}

static int file_get(FILE *f)
{
    unsigned shift, c;
    if (f->pushed != EOF) {
        c = f->pushed;
        f->pushed = EOF;
        f->pos++;
        return c;
    }
    if (!f->input) {
        f->error = 1;
        return EOF;
    }
    if (f->pos >= f->length) {
        f->eof = 1;
        return EOF;
    }
    if (f->packed) {
        if (load_word(f, f->pos / 4))
            return EOF;
        shift = f->pos % 4 * 8;
        c = (f->word >> shift) & 0xFF;
    } else {
        c = _fs_word(f->first, f->pos);
    }
    f->pos++;
    return c;
}

static int file_put(int c, FILE *f)
{
    unsigned shift, addr;
    if (!f->output) {
        f->error = 1;
        return EOF;
    }
    if (f->append)
        f->pos = f->length;
    f->pushed = EOF;
    if (f->packed) {
        c &= 0xFF;
        if (load_word(f, f->pos / 4))
            return EOF;
        shift = f->pos % 4 * 8;
        f->word = (f->word & ~(0xFFu << shift)) | ((unsigned)c << shift);
        f->word_dirty = 1;
    } else {
        addr = file_addr(f, f->pos);
        if (addr == 0) {
            f->error = 1;
            return EOF;
        }
        disk_write(addr, c);
    }
    f->pos++;
    if (f->pos > f->length) {
        f->length = f->pos;
        f->entry_dirty = 1;
    }
    return c;
}

static void close_all(void)
{
    int i;
    for (i = 0; i < MAX_OPEN; i++)
        if (in_use[i])
            fclose(&files[i]);
}

FILE *fopen(const char *path, const char *mode)
{
    _Node dir, node;
    char name[_FS_NAME];
    int i, plus = strchr(mode, '+') != 0, binary = strchr(mode, 'b') != 0;
    unsigned kind = binary ? 0 : _FS_PACKED;
    FILE *f;
    if (mode[0] != 'r' && mode[0] != 'w' && mode[0] != 'a') {
        errno = EINVAL;
        return 0;
    }
    for (i = 0; i < MAX_OPEN && in_use[i]; i++)
        ;
    if (i == MAX_OPEN) {
        errno = EMFILE;
        return 0;
    }
    if (_fs_lookup(path, &node) == 0) {
        if (node.flags & _FS_DIR) {
            errno = EISDIR;
            return 0;
        }
        if (mode[0] == 'w') {           /* empty it; text or binary as the mode says */
            _fs_unlink(&node);
            node.flags = _FS_USED | kind;
            _fs_save(&node);
        }
    } else {
        if (errno != ENOENT || mode[0] == 'r')
            return 0;
        if (_fs_parent(path, &dir, name) || _fs_add(&dir, name, kind, &node))
            return 0;
    }
    f = &files[i];
    memset(f, 0, sizeof *f);
    f->get = file_get;
    f->put = file_put;
    f->flush = file_flush;
    f->input = mode[0] == 'r' || plus;
    f->output = mode[0] != 'r' || plus;
    f->append = mode[0] == 'a';
    f->packed = (node.flags & _FS_PACKED) != 0;
    f->pushed = EOF;
    f->first = node.first;
    f->length = node.length;
    f->flags = node.flags;
    f->dir_first = node.dir_first;
    f->index = node.index;
    f->pos = f->append ? node.length : 0;
    f->word_at = (unsigned)-1;
    in_use[i] = 1;
    if (!closer_set) {
        atexit(close_all);              /* exit() and the end of main() save open files */
        closer_set = 1;
    }
    return f;
}

int fclose(FILE *stream)
{
    int i, result = 0;
    for (i = 0; i < MAX_OPEN; i++)
        if (stream == &files[i] && in_use[i]) {
            result = file_flush(stream);
            in_use[i] = 0;
            stream->get = 0;
            stream->put = 0;
            stream->flush = 0;
        }
    return result;
}

int fseek(FILE *stream, long offset, int whence)
{
    long base;
    if (!stream->get) {
        errno = EBADF;
        return -1;
    }
    base = whence == SEEK_SET ? 0 : whence == SEEK_CUR ? (long)stream->pos
         : whence == SEEK_END ? (long)stream->length : -1;
    if (base < 0 || base + offset < 0) {
        errno = EINVAL;
        return -1;
    }
    stream->pos = base + offset;
    stream->pushed = EOF;
    stream->eof = 0;
    return 0;
}

long ftell(FILE *stream)
{
    if (!stream->get) {
        errno = EBADF;
        return -1;
    }
    return stream->pos;                 /* ungetc steps it back */
}

void rewind(FILE *stream)
{
    fseek(stream, 0, SEEK_SET);
    stream->error = 0;
}

int remove(const char *path)
{
    _Node node;
    if (_fs_lookup(path, &node))
        return -1;
    if (node.root) {
        errno = EBUSY;
        return -1;
    }
    if ((node.flags & _FS_DIR) && !_fs_empty(&node)) {
        errno = ENOTEMPTY;
        return -1;
    }
    _fs_unlink(&node);
    return 0;
}

int rename(const char *from, const char *to)
{
    _Node node, dir, moved;
    char name[_FS_NAME], a[_FS_PATH], b[_FS_PATH];
    size_t n;
    if (_fs_lookup(from, &node))
        return -1;
    if (node.root) {
        errno = EBUSY;
        return -1;
    }
    if (_fs_normalize(from, a) || _fs_normalize(to, b))
        return -1;
    n = strlen(a);
    if ((node.flags & _FS_DIR) && strncmp(a, b, n) == 0 && (b[n] == '/' || b[n] == 0)) {
        errno = EINVAL;                 /* a directory into itself */
        return -1;
    }
    if (_fs_lookup(to, &moved) == 0) {
        errno = EEXIST;
        return -1;
    }
    if (_fs_parent(to, &dir, name) || _fs_add(&dir, name, node.flags & ~_FS_USED, &moved))
        return -1;
    moved.first = node.first;
    moved.length = node.length;
    _fs_save(&moved);
    _fs_lookup(from, &node);            /* again: its directory may have grown */
    node.flags = 0;
    _fs_save(&node);
    return 0;
}
