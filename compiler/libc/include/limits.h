/* limits.h - sizes of integer types
 *
 * The CPU addresses 32-bit words, not bytes: char, short, int and long are
 * all 32 bits wide and sizeof gives 1 for each. long long is not supported.
 */
#ifndef _LIMITS_H
#define _LIMITS_H

#define CHAR_BIT 32
#define MB_LEN_MAX 1

#define SCHAR_MIN (-2147483647 - 1)
#define SCHAR_MAX 2147483647
#define UCHAR_MAX 4294967295U
#define CHAR_MIN SCHAR_MIN
#define CHAR_MAX SCHAR_MAX

#define SHRT_MIN (-2147483647 - 1)
#define SHRT_MAX 2147483647
#define USHRT_MAX 4294967295U

#define INT_MIN (-2147483647 - 1)
#define INT_MAX 2147483647
#define UINT_MAX 4294967295U

#define LONG_MIN (-2147483647L - 1)
#define LONG_MAX 2147483647L
#define ULONG_MAX 4294967295UL

#endif
