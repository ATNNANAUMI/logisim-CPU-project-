/* setlocale, localeconv: the "C" locale only */
#include <locale.h>
#include <string.h>

static struct lconv c_locale = {
    ".", "", "", "", "", "", "", "", "", "", 127, 127, 127, 127, 127, 127, 127, 127
};

char *setlocale(int category, const char *locale)
{
    (void)category;
    if (locale == 0 || locale[0] == 0 || strcmp(locale, "C") == 0 || strcmp(locale, "POSIX") == 0)
        return "C";
    return 0;
}

struct lconv *localeconv(void)
{
    return &c_locale;
}
