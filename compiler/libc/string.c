/* string.h: strings and memory blocks. A char is a whole 32-bit word. */
#include <string.h>

void *memcpy(void *dst, const void *src, size_t n)
{
    char *d = dst;
    const char *s = src;
    while (n--)
        *d++ = *s++;
    return dst;
}

void *memmove(void *dst, const void *src, size_t n)
{
    char *d = dst;
    const char *s = src;
    if (d < s) {
        while (n--)
            *d++ = *s++;
    } else if (d > s) {
        d += n;
        s += n;
        while (n--)
            *--d = *--s;
    }
    return dst;
}

void *memset(void *dst, int c, size_t n)
{
    char *d = dst;
    while (n--)
        *d++ = c;
    return dst;
}

int memcmp(const void *a, const void *b, size_t n)
{
    const unsigned char *p = a, *q = b;
    for (; n; n--, p++, q++)
        if (*p != *q)
            return *p < *q ? -1 : 1;
    return 0;
}

void *memchr(const void *s, int c, size_t n)
{
    const char *p = s;
    for (; n; n--, p++)
        if (*p == c)
            return (void *)p;
    return 0;
}

size_t strlen(const char *s)
{
    const char *p = s;
    while (*p)
        p++;
    return p - s;
}

size_t strnlen(const char *s, size_t max)
{
    size_t n = 0;
    while (n < max && s[n])
        n++;
    return n;
}

char *strcpy(char *dst, const char *src)
{
    char *d = dst;
    while ((*d++ = *src++) != 0)
        ;
    return dst;
}

char *strncpy(char *dst, const char *src, size_t n)
{
    size_t i = 0;
    for (; i < n && src[i]; i++)
        dst[i] = src[i];
    for (; i < n; i++)
        dst[i] = 0;
    return dst;
}

char *strcat(char *dst, const char *src)
{
    char *d = dst;
    while (*d)
        d++;
    while ((*d++ = *src++) != 0)
        ;
    return dst;
}

char *strncat(char *dst, const char *src, size_t n)
{
    char *d = dst;
    while (*d)
        d++;
    while (n-- && *src)
        *d++ = *src++;
    *d = 0;
    return dst;
}

int strcmp(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return *(const unsigned char *)a < *(const unsigned char *)b ? -1 :
           *(const unsigned char *)a > *(const unsigned char *)b ? 1 : 0;
}

int strncmp(const char *a, const char *b, size_t n)
{
    for (; n; n--, a++, b++) {
        if (*a != *b)
            return *(const unsigned char *)a < *(const unsigned char *)b ? -1 : 1;
        if (*a == 0)
            return 0;
    }
    return 0;
}

int strcoll(const char *a, const char *b)
{
    return strcmp(a, b);
}

size_t strxfrm(char *dst, const char *src, size_t n)
{
    size_t len = strlen(src);
    if (len < n)
        strcpy(dst, src);
    return len;
}

char *strchr(const char *s, int c)
{
    for (;; s++) {
        if (*s == c)
            return (char *)s;
        if (*s == 0)
            return 0;
    }
}

char *strrchr(const char *s, int c)
{
    const char *found = 0;
    for (;; s++) {
        if (*s == c)
            found = s;
        if (*s == 0)
            return (char *)found;
    }
}

size_t strspn(const char *s, const char *accept)
{
    size_t n = 0;
    while (s[n] && strchr(accept, s[n]))
        n++;
    return n;
}

size_t strcspn(const char *s, const char *reject)
{
    size_t n = 0;
    while (s[n] && !strchr(reject, s[n]))
        n++;
    return n;
}

char *strpbrk(const char *s, const char *accept)
{
    for (; *s; s++)
        if (strchr(accept, *s))
            return (char *)s;
    return 0;
}

char *strstr(const char *haystack, const char *needle)
{
    size_t n = strlen(needle);
    if (n == 0)
        return (char *)haystack;
    for (; *haystack; haystack++)
        if (*haystack == *needle && strncmp(haystack, needle, n) == 0)
            return (char *)haystack;
    return 0;
}

char *strtok(char *s, const char *delim)
{
    static char *next;
    char *start;
    if (s == 0)
        s = next;
    if (s == 0)
        return 0;
    s += strspn(s, delim);
    if (*s == 0) {
        next = 0;
        return 0;
    }
    start = s;
    s += strcspn(s, delim);
    if (*s) {
        *s = 0;
        next = s + 1;
    } else {
        next = 0;
    }
    return start;
}

char *strerror(int errnum)
{
    switch (errnum) {
    case 0: return "Success";
    case 33: return "Numerical argument out of domain";
    case 34: return "Numerical result out of range";
    case 84: return "Invalid or incomplete multibyte or wide character";
    default: return "Unknown error";
    }
}

