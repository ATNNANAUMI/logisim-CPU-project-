/* stdio.h - input and output
 *
 * Output goes to the text display (device 0x5C), stdout and stderr alike.
 * Input comes from the keyboard (device 0xF0) a line at a time, echoed as it
 * is typed, with backspace editing. Ctrl-D (0x04) at the start of a line
 * means end of file.
 *
 * Files are on the disk (the simulator's --disk FILE, formatted with
 * python compiler/src/disk format). fopen modes r w a, + and b: a text file
 * (no b) holds 4 chars a word, so only the low 8 bits of each char are kept;
 * a binary file (b) holds one whole word per char, so fgetc can return a
 * word equal to EOF (check feof, or use fread). The kind is fixed when the
 * file is created. Paths start at the root ("/a/b") or at the current
 * directory (unistd.h: chdir, getcwd, mkdir, rmdir; dirent.h lists one).
 * Open files are saved by fclose, fflush, exit and the end of main.
 */
#ifndef _STDIO_H
#define _STDIO_H

#include <stddef.h>

#define EOF (-1)
#define BUFSIZ 256
#define FILENAME_MAX 512
#define FOPEN_MAX 11
#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2

typedef struct _FILE FILE;
typedef char *__va_list;

extern FILE *stdin;
extern FILE *stdout;
extern FILE *stderr;

int putchar(int c);
int puts(const char *s);
int printf(const char *fmt, ...);
int vprintf(const char *fmt, __va_list ap);
int sprintf(char *buf, const char *fmt, ...);
int vsprintf(char *buf, const char *fmt, __va_list ap);
int snprintf(char *buf, size_t size, const char *fmt, ...);
int vsnprintf(char *buf, size_t size, const char *fmt, __va_list ap);

int fputc(int c, FILE *stream);
int putc(int c, FILE *stream);
int fputs(const char *s, FILE *stream);
int fprintf(FILE *stream, const char *fmt, ...);
int vfprintf(FILE *stream, const char *fmt, __va_list ap);
int fflush(FILE *stream);
size_t fwrite(const void *ptr, size_t size, size_t count, FILE *stream);

int getchar(void);
int fgetc(FILE *stream);
int getc(FILE *stream);
int ungetc(int c, FILE *stream);
char *fgets(char *buf, int size, FILE *stream);
size_t fread(void *ptr, size_t size, size_t count, FILE *stream);
int scanf(const char *fmt, ...);
int vscanf(const char *fmt, __va_list ap);
int sscanf(const char *s, const char *fmt, ...);
int vsscanf(const char *s, const char *fmt, __va_list ap);
int fscanf(FILE *stream, const char *fmt, ...);
int vfscanf(FILE *stream, const char *fmt, __va_list ap);

int feof(FILE *stream);
int ferror(FILE *stream);
void clearerr(FILE *stream);
FILE *fopen(const char *path, const char *mode);
int fclose(FILE *stream);
int fseek(FILE *stream, long offset, int whence);
long ftell(FILE *stream);
void rewind(FILE *stream);
void perror(const char *s);
int remove(const char *path);
int rename(const char *from, const char *to);

#endif
