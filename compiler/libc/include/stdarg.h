/* stdarg.h - variable argument lists
 *
 * A variadic call pushes the variadic arguments first, then the fixed ones,
 * then how many variadic words there are; __builtin_va_start() finds the
 * first variadic word. Every argument is one word (a struct takes its size).
 */
#ifndef _STDARG_H
#define _STDARG_H

typedef char *va_list;

#define va_start(ap, last) ((ap) = __builtin_va_start())
#define va_arg(ap, type) (*(type *)(((ap) += sizeof(type)) - sizeof(type)))
#define va_end(ap) ((void)0)
#define va_copy(dst, src) ((dst) = (src))

#endif
