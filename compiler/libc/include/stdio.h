/* stdio.h - input and output
 *
 * Output goes to the text display (device 0x5C), stdout and stderr alike.
 * Input comes from the keyboard (device 0xF0) a line at a time, echoed as it
 * is typed, with backspace editing. Ctrl-D (0x04) at the start of a line
 * means end of file. There are no files on disk: fopen always fails.
 */
#ifndef _STDIO_H
#define _STDIO_H

#include <stddef.h>

#define EOF (-1)
#define BUFSIZ 256
#define FILENAME_MAX 64
#define FOPEN_MAX 3

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

int feof(FILE *stream);
int ferror(FILE *stream);
void clearerr(FILE *stream);
FILE *fopen(const char *path, const char *mode);
int fclose(FILE *stream);
void perror(const char *s);
int remove(const char *path);
int rename(const char *from, const char *to);

#endif
