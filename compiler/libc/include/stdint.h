/* stdint.h - integer types
 *
 * Every integer type is 32 bits (the CPU addresses 32-bit words), so the
 * exact-width types that exist are int32_t and uint32_t. int8_t, int16_t,
 * int64_t and their unsigned forms are left out on purpose: a 32-bit stand-in
 * would not wrap around where a program expects. The least/fast types are
 * 32 bits. intmax_t is 32 bits too (no 64-bit integers).
 */
#ifndef _STDINT_H
#define _STDINT_H

typedef int int32_t;
typedef unsigned int uint32_t;

typedef int int_least8_t;
typedef int int_least16_t;
typedef int int_least32_t;
typedef unsigned int uint_least8_t;
typedef unsigned int uint_least16_t;
typedef unsigned int uint_least32_t;

typedef int int_fast8_t;
typedef int int_fast16_t;
typedef int int_fast32_t;
typedef unsigned int uint_fast8_t;
typedef unsigned int uint_fast16_t;
typedef unsigned int uint_fast32_t;

typedef int intptr_t;
typedef unsigned int uintptr_t;
typedef int intmax_t;
typedef unsigned int uintmax_t;

#define INT32_MIN (-2147483647 - 1)
#define INT32_MAX 2147483647
#define UINT32_MAX 4294967295U

#define INT_LEAST8_MIN INT32_MIN
#define INT_LEAST8_MAX INT32_MAX
#define UINT_LEAST8_MAX UINT32_MAX
#define INT_LEAST16_MIN INT32_MIN
#define INT_LEAST16_MAX INT32_MAX
#define UINT_LEAST16_MAX UINT32_MAX
#define INT_LEAST32_MIN INT32_MIN
#define INT_LEAST32_MAX INT32_MAX
#define UINT_LEAST32_MAX UINT32_MAX

#define INT_FAST8_MIN INT32_MIN
#define INT_FAST8_MAX INT32_MAX
#define UINT_FAST8_MAX UINT32_MAX
#define INT_FAST16_MIN INT32_MIN
#define INT_FAST16_MAX INT32_MAX
#define UINT_FAST16_MAX UINT32_MAX
#define INT_FAST32_MIN INT32_MIN
#define INT_FAST32_MAX INT32_MAX
#define UINT_FAST32_MAX UINT32_MAX

#define INTPTR_MIN INT32_MIN
#define INTPTR_MAX INT32_MAX
#define UINTPTR_MAX UINT32_MAX
#define INTMAX_MIN INT32_MIN
#define INTMAX_MAX INT32_MAX
#define UINTMAX_MAX UINT32_MAX

#define PTRDIFF_MIN INT32_MIN
#define PTRDIFF_MAX INT32_MAX
#define SIZE_MAX UINT32_MAX
#define WCHAR_MIN INT32_MIN
#define WCHAR_MAX INT32_MAX

#define INT8_C(c) c
#define INT16_C(c) c
#define INT32_C(c) c
#define UINT8_C(c) c ## U
#define UINT16_C(c) c ## U
#define UINT32_C(c) c ## U
#define INTMAX_C(c) c
#define UINTMAX_C(c) c ## U

#endif
