/* local.h - shared by the C library's own files (not a public header) */
#ifndef _LIBC_LOCAL_H
#define _LIBC_LOCAL_H

#include <stddef.h>
#include <stdarg.h>

#define _DISPLAY 0x5C
#define _KEYBOARD 0xF0

/* where formatted output goes: the display (buf == 0) or a string */
typedef struct {
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

#endif
