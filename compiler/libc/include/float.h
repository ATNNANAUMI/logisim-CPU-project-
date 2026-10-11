/* float.h - floating types
 *
 * The CPU has a 32-bit IEEE-754 float unit only: float, double and
 * long double are all the same 32-bit type.
 */
#ifndef _FLOAT_H
#define _FLOAT_H

#define FLT_RADIX 2
#define FLT_ROUNDS 1
#define FLT_EVAL_METHOD 0
#define DECIMAL_DIG 9

#define FLT_MANT_DIG 24
#define FLT_DIG 6
#define FLT_MIN_EXP (-125)
#define FLT_MIN_10_EXP (-37)
#define FLT_MAX_EXP 128
#define FLT_MAX_10_EXP 38
#define FLT_MAX 3.40282347e+38F
#define FLT_EPSILON 1.19209290e-07F
#define FLT_MIN 1.17549435e-38F
#define FLT_TRUE_MIN 1.40129846e-45F

#define DBL_MANT_DIG FLT_MANT_DIG
#define DBL_DIG FLT_DIG
#define DBL_MIN_EXP FLT_MIN_EXP
#define DBL_MIN_10_EXP FLT_MIN_10_EXP
#define DBL_MAX_EXP FLT_MAX_EXP
#define DBL_MAX_10_EXP FLT_MAX_10_EXP
#define DBL_MAX FLT_MAX
#define DBL_EPSILON FLT_EPSILON
#define DBL_MIN FLT_MIN
#define DBL_TRUE_MIN FLT_TRUE_MIN

#define LDBL_MANT_DIG FLT_MANT_DIG
#define LDBL_DIG FLT_DIG
#define LDBL_MIN_EXP FLT_MIN_EXP
#define LDBL_MIN_10_EXP FLT_MIN_10_EXP
#define LDBL_MAX_EXP FLT_MAX_EXP
#define LDBL_MAX_10_EXP FLT_MAX_10_EXP
#define LDBL_MAX FLT_MAX
#define LDBL_EPSILON FLT_EPSILON
#define LDBL_MIN FLT_MIN
#define LDBL_TRUE_MIN FLT_TRUE_MIN

#endif
