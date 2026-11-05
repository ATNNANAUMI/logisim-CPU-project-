/* basic.c - a home-computer BASIC (a program for Tynix, in /bin)
 *
 *   python tynix/make_disk.py              (builds it into /bin)
 *   (in the shell)   basic             type lines; numbered ones are kept, others run at once
 *                    basic prog.bas    run a file and exit (so a BASIC program works like a command)
 *
 * Commands:   RUN  LIST [a-b]  NEW  SAVE "file"  LOAD "file"  BYE
 * Statements: PRINT (; and , between items)   [LET] A=...   INPUT ["text";] A, B$
 *             IF c THEN line|statements [ELSE ...]   GOTO n   GOSUB n / RETURN
 *             FOR v=a TO b [STEP s] / NEXT [v]   WHILE c / WEND   DIM A(n), B$(n)
 *             DATA ... / READ v / RESTORE   REM   END   STOP   RANDOMIZE [n]
 *             CLS  PLOT x,y,c  LINE x,y,x2,y2,c  CIRCLE x,y,r,c  TEXT x,y,s$,c  SLEEP ms
 *             (the RGB screen through gfx.h; colours are 0-15 or a 16-bit value)
 * Several statements on a line are separated by ':'.
 * Values:     numbers (32-bit float), strings (names end in $), one-dimensional arrays
 *             (DIM A(10) has A(0) to A(10)). Names: letters and digits, case ignored.
 * Operators:  ^  unary -  * / MOD  + -  = <> < > <= >=  NOT  AND  OR   (true is -1, false 0;
 *             strings join with + and compare with = < > ...)
 * Functions:  ABS INT SQR SIN COS ATN LOG EXP SGN RND(n) LEN(s$) MID$(s$,i[,n]) LEFT$ RIGHT$
 *             CHR$ ASC STR$ VAL INKEY$ TIMER
 * Errors:     ?SYNTAX ERROR IN 120, ?TYPE MISMATCH, ?DIVISION BY ZERO, ?OUT OF DATA, ?BAD SUBSCRIPT,
 *             ?UNDEFINED LINE, ?NEXT WITHOUT FOR ... : a program stops and the prompt returns.
 *             Ctrl-D at the prompt ends the program; Ctrl-C (key 3) stops a running one at INKEY$.
 *
 * Not in this BASIC: line renumbering, PEEK/POKE, two-dimensional arrays, files other than
 * SAVE/LOAD. A line is interpreted from its text each time it runs (no tokens), which is slower
 * than a tokeniser but keeps the program short. Strings are malloc'd and freed when replaced.
 *
 * Exit status: 0, or 1 when `basic prog.bas` stops with an error (or the file is missing).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>
#include <setjmp.h>
#include <time.h>
#ifndef BASIC_TEST
#include <cpu.h>
#include <gfx.h>
#endif

#define MAX_LINES 2000
#define MAX_LEN 200
#define MAX_VARS 200
#define STACK 64
#define MAX_ARRAY 20000

typedef struct {
    int type;               /* 0 number, 1 string */
    float n;
    char *s;                /* a string value owns this (malloc'd) */
} Val;

typedef struct {
    char name[24];          /* upper case, with the $ of a string */
    int is_str, size;       /* size 0: a plain variable; else the largest index + 1 */
    float *n;
    char **s;
} Var;

typedef struct { int num; char *text; } Line;

static Line prog[MAX_LINES];
static int nlines;
static Var vars[MAX_VARS];
static int nvars;

static const char *p;               /* the cursor in the line being run */
static const char *stmt_start;      /* where the statement being run began */
static int pc;                      /* index of the line being run, -1 in direct mode */
static int done;                    /* END, STOP or a run off the end: leave the executor */
static int redirect;                /* a statement set where to go on (rpc, rp) */
static int rpc;
static const char *rp;
static jmp_buf on_error;
static int cur_num;                 /* its number (for the error message) */

typedef struct { int line; const char *pos; } Frame;
static Frame gosubs[STACK];
static int ngosub;
typedef struct { Var *v; int idx; float limit, step; int line; const char *pos; } ForFrame;
static ForFrame fors[STACK];
static int nfor;
static Frame whiles[STACK];
static int nwhile;

static int data_line, data_n;       /* READ's place: the line and the item in it */
static const char *data_pos;
static unsigned rng = 12345;

/* the source of lines at the prompt: stdin, or the self-check's list */
static char *(*get_line)(char *buf, int size);

static void fail(const char *msg)
{
    printf("?%s", msg);
    if (cur_num >= 0)
        printf(" IN %d", cur_num);
    printf("\n");
    longjmp(on_error, 1);
}
static void syntax(void) { fail("SYNTAX ERROR"); }

static void skip(void)
{
    while (*p == ' ' || *p == '\t')
        p++;
}

/* the next word (letters), upper-cased, if p is at the keyword kw; moves p past it */
static int keyword(const char *kw)
{
    int n = strlen(kw), i;
    skip();
    for (i = 0; i < n; i++)
        if (toupper((unsigned char)p[i]) != kw[i])
            return 0;
    if (isalnum((unsigned char)p[n]) && isalpha((unsigned char)kw[n - 1]) && kw[n - 1] != '$')
        return 0;
    p += n;
    return 1;
}

static int same_word(const char *t, const char *w)
{
    int n = strlen(w), i;
    for (i = 0; i < n; i++)
        if (toupper((unsigned char)t[i]) != w[i])
            return 0;
    return !isalnum((unsigned char)t[n]);
}

static int strncasecmp_(const char *t, const char *w)
{
    int i;
    for (i = 0; w[i]; i++)
        if (toupper((unsigned char)t[i]) != w[i])
            return 0;
    return 1;
}

static int at_end(void)
{
    skip();
    return *p == 0 || *p == ':' || same_word(p, "ELSE");
}

/* ------------------------------------------------------------ variables */
static Var *find_var(const char *name, int is_str, int create)
{
    int i;
    for (i = 0; i < nvars; i++)
        if (strcmp(vars[i].name, name) == 0)
            return &vars[i];
    if (!create)
        return 0;
    if (nvars == MAX_VARS)
        fail("TOO MANY VARIABLES");
    strcpy(vars[nvars].name, name);
    vars[nvars].is_str = is_str;
    vars[nvars].size = 0;
    vars[nvars].n = malloc(sizeof(float));
    vars[nvars].s = malloc(sizeof(char *));
    vars[nvars].n[0] = 0;
    vars[nvars].s[0] = 0;
    return &vars[nvars++];
}

static void clear_vars(void)
{
    int i, j;
    for (i = 0; i < nvars; i++) {
        for (j = 0; j < (vars[i].size ? vars[i].size : 1); j++)
            free(vars[i].s[j]);
        free(vars[i].n);
        free(vars[i].s);
    }
    nvars = ngosub = nfor = nwhile = 0;
}

/* a name at p: letters and digits, then an optional $; returns 0 if there is none */
static int get_name(char *name, int *is_str)
{
    int n = 0;
    skip();
    if (!isalpha((unsigned char)*p))
        return 0;
    while (isalnum((unsigned char)*p) && n < 22)
        name[n++] = toupper((unsigned char)*p++);
    *is_str = 0;
    if (*p == '$') {
        name[n++] = '$';
        p++;
        *is_str = 1;
    }
    name[n] = 0;
    return 1;
}

static Val expr(void);

static Val num(float f)
{
    Val v;
    v.type = 0;
    v.n = f;
    v.s = 0;
    return v;
}

static Val str(const char *s, int len)
{
    Val v;
    v.type = 1;
    v.n = 0;
    v.s = malloc(len + 1);
    memcpy(v.s, s, len);
    v.s[len] = 0;
    return v;
}

static float need_num(Val v)
{
    if (v.type != 0) {
        free(v.s);
        fail("TYPE MISMATCH");
    }
    return v.n;
}

static char *need_str(Val v)
{
    if (v.type != 1)
        fail("TYPE MISMATCH");
    return v.s;
}

/* the slot (a variable or one array element) named at p: the index of an
 * array element is read here; returns the variable and the element */
static Var *get_slot(int *index)
{
    char name[24];
    int is_str, i = 0;
    Var *v;
    if (!get_name(name, &is_str))
        syntax();
    skip();
    if (*p == '(') {
        float f;
        p++;
        f = need_num(expr());
        skip();
        if (*p++ != ')')
            syntax();
        v = find_var(name, is_str, 0);
        if (!v || !v->size)
            fail("BAD SUBSCRIPT");              /* an array must be DIMed */
        if (f < 0 || f >= v->size)
            fail("BAD SUBSCRIPT");
        i = (int)f;
    } else {
        v = find_var(name, is_str, 1);
        if (v->size)
            fail("BAD SUBSCRIPT");
    }
    *index = i;
    return v;
}

static void store(Var *v, int i, Val val)
{
    if (v->is_str) {
        char *s = need_str(val);
        free(v->s[i]);
        v->s[i] = s;
    } else {
        v->n[i] = need_num(val);
    }
}

/* ------------------------------------------------------------ expressions */
static unsigned next_rand(void)
{
    rng = rng * 1103515245u + 12345u;
    return (rng >> 8) & 0xFFFFFF;
}

static char *dup_str(const char *s)
{
    return str(s, strlen(s)).s;
}

static Val number_text(float f)
{
    char buf[40];
    if (f == (float)(int)f && f < 1e9f && f > -1e9f)
        sprintf(buf, "%d", (int)f);
    else
        sprintf(buf, "%g", (double)f);
    return str(buf, strlen(buf));
}

static float arg_num(void)
{
    float f;
    skip();
    if (*p++ != '(')
        syntax();
    f = need_num(expr());
    skip();
    if (*p++ != ')')
        syntax();
    return f;
}

static Val primary(void)
{
    char name[24];
    int is_str;
    skip();
    if (*p == '(') {
        Val v;
        p++;
        v = expr();
        skip();
        if (*p++ != ')')
            syntax();
        return v;
    }
    if (isdigit((unsigned char)*p) || *p == '.') {
        char *end;
        float f = strtod(p, &end);
        p = end;
        return num(f);
    }
    if (*p == '"') {
        const char *start = ++p;
        while (*p && *p != '"')
            p++;
        if (*p != '"')
            syntax();
        p++;
        return str(start, p - 1 - start);
    }
    if (keyword("ABS")) { float f = arg_num(); return num(f < 0 ? -f : f); }
    if (keyword("INT")) return num(floor(arg_num()));
    if (keyword("SQR")) {
        float f = arg_num();
        if (f < 0)
            fail("ILLEGAL QUANTITY");
        return num(sqrt(f));
    }
    if (keyword("SIN")) return num(sin(arg_num()));
    if (keyword("COS")) return num(cos(arg_num()));
    if (keyword("ATN")) return num(atan(arg_num()));
    if (keyword("EXP")) return num(exp(arg_num()));
    if (keyword("LOG")) {
        float f = arg_num();
        if (f <= 0)
            fail("ILLEGAL QUANTITY");
        return num(log(f));
    }
    if (keyword("SGN")) { float f = arg_num(); return num(f > 0 ? 1 : f < 0 ? -1 : 0); }
    if (keyword("RND")) {
        float f = arg_num();
        if (f < 0)
            rng = (unsigned)(-f);
        return num((next_rand() & 0xFFFF) / 65536.0f);
    }
    if (keyword("TIMER")) return num(clock() / 1000.0f);
    if (keyword("LEN")) {
        Val v;
        float f;
        skip();
        if (*p++ != '(')
            syntax();
        v = expr();
        skip();
        if (*p++ != ')')
            syntax();
        f = strlen(need_str(v));
        free(v.s);
        return num(f);
    }
    if (keyword("ASC")) {
        Val v;
        float f;
        skip();
        if (*p++ != '(')
            syntax();
        v = expr();
        skip();
        if (*p++ != ')')
            syntax();
        f = need_str(v)[0] ? (unsigned char)v.s[0] : 0;
        free(v.s);
        return num(f);
    }
    if (keyword("VAL")) {
        Val v;
        float f;
        skip();
        if (*p++ != '(')
            syntax();
        v = expr();
        skip();
        if (*p++ != ')')
            syntax();
        f = strtod(need_str(v), 0);
        free(v.s);
        return num(f);
    }
    if (keyword("CHR$")) {
        char c = (char)arg_num();
        return str(&c, 1);
    }
    if (keyword("STR$")) return number_text(arg_num());
    if (keyword("INKEY$")) {
#ifndef BASIC_TEST
        int k = key_pressed();
        char c = (char)k;
        if (k == 3)
            fail("BREAK");
        return k ? str(&c, 1) : str("", 0);
#else
        return str("", 0);
#endif
    }
    {
        int which = keyword("LEFT$") ? 0 : keyword("RIGHT$") ? 1 : keyword("MID$") ? 2 : -1;
        if (which >= 0) {
        Val v;
        char *s;
        int len, a, n;
        skip();
        if (*p++ != '(')
            syntax();
        v = expr();
        s = need_str(v);
        len = strlen(s);
        skip();
        if (*p++ != ',')
            syntax();
        a = (int)need_num(expr());
        n = len;
        skip();
        if (*p == ',') {
            p++;
            n = (int)need_num(expr());
        }
        skip();
        if (*p++ != ')')
            syntax();
        if (a < 0 || n < 0)
            fail("ILLEGAL QUANTITY");
        if (which == 0) {                       /* LEFT$(s, n) */
            n = a;
            a = 0;
        } else if (which == 1) {                /* RIGHT$(s, n) */
            a = len - (a > len ? len : a);
            n = len;
        } else {
            a = a > 0 ? a - 1 : 0;              /* MID$(s, start[, n]), start from 1 */
        }
        if (a > len)
            a = len;
        if (n > len - a)
            n = len - a;
        {
            Val r = str(s + a, n);
            free(v.s);
            return r;
        }
        }
    }
    if (isalpha((unsigned char)*p)) {
        Var *v;
        int i;
        const char *save = p;
        get_name(name, &is_str);
        p = save;
        v = get_slot(&i);
        return v->is_str ? str(v->s[i] ? v->s[i] : "", v->s[i] ? strlen(v->s[i]) : 0) : num(v->n[i]);
    }
    syntax();
    return num(0);
}

static Val power(void)
{
    Val a = primary();
    skip();
    while (*p == '^') {
        float x = need_num(a), y;
        p++;
        y = need_num(primary());
        a = num(pow(x, y));
        skip();
    }
    return a;
}

static Val unary(void)
{
    skip();
    if (*p == '-') {
        p++;
        return num(-need_num(unary()));
    }
    if (*p == '+') {
        p++;
        return unary();
    }
    return power();
}

static Val term(void)
{
    Val a = unary();
    for (;;) {
        skip();
        if (*p == '*' || *p == '/') {
            char op = *p++;
            float x = need_num(a), y = need_num(unary());
            if (op == '/' && y == 0)
                fail("DIVISION BY ZERO");
            a = num(op == '*' ? x * y : x / y);
        } else if (keyword("MOD")) {
            float x = need_num(a), y = need_num(unary());
            if ((int)y == 0)
                fail("DIVISION BY ZERO");
            a = num((int)x % (int)y);
        } else {
            return a;
        }
    }
}

static Val sum(void)
{
    Val a = term();
    for (;;) {
        skip();
        if (*p == '+') {
            Val b;
            p++;
            b = term();
            if (a.type == 1) {
                char *x = need_str(a), *y = need_str(b);
                Val r = str("", strlen(x) + strlen(y));
                strcpy(r.s, x);
                strcat(r.s, y);
                free(x);
                free(y);
                a = r;
            } else {
                a = num(need_num(a) + need_num(b));
            }
        } else if (*p == '-') {
            float x = need_num(a), y;
            p++;
            y = need_num(term());
            a = num(x - y);
        } else {
            return a;
        }
    }
}

static Val compare(void)
{
    Val a = sum();
    skip();
    if (*p == '=' || *p == '<' || *p == '>') {
        int lt = 0, eq = 0, gt = 0, c;
        Val b;
        while (*p == '=' || *p == '<' || *p == '>') {
            if (*p == '=') eq = 1;
            if (*p == '<') lt = 1;
            if (*p == '>') gt = 1;
            p++;
        }
        b = sum();
        if (a.type != b.type) {
            free(a.s);
            free(b.s);
            fail("TYPE MISMATCH");
        }
        if (a.type == 1) {
            c = strcmp(a.s, b.s);
            free(a.s);
            free(b.s);
        } else {
            c = a.n < b.n ? -1 : a.n > b.n ? 1 : 0;
        }
        return num(((c < 0 && lt) || (c == 0 && eq) || (c > 0 && gt)) ? -1 : 0);
    }
    return a;
}

static Val not_expr(void)
{
    if (keyword("NOT"))
        return num(~(int)need_num(not_expr()));
    return compare();
}

static Val and_expr(void)
{
    Val a = not_expr();
    while (keyword("AND")) {
        int x = (int)need_num(a);
        a = num(x & (int)need_num(not_expr()));
    }
    return a;
}

static Val expr(void)
{
    Val a = and_expr();
    while (keyword("OR")) {
        int x = (int)need_num(a);
        a = num(x | (int)need_num(and_expr()));
    }
    return a;
}

/* ------------------------------------------------------------ the program */
static int find_line(int number)
{
    int lo = 0, hi = nlines - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (prog[mid].num == number)
            return mid;
        if (prog[mid].num < number)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    return -1;
}

static void put_line(int number, const char *text)
{
    int i = 0, at;
    while (i < nlines && prog[i].num < number)
        i++;
    at = i;
    if (i < nlines && prog[i].num == number) {
        free(prog[i].text);
        if (*text) {
            prog[i].text = dup_str(text);
            return;
        }
        for (; i + 1 < nlines; i++)
            prog[i] = prog[i + 1];
        nlines--;
        return;
    }
    if (!*text)
        return;
    if (nlines == MAX_LINES) {
        printf("?PROGRAM TOO LARGE\n");
        return;
    }
    for (i = nlines; i > at; i--)
        prog[i] = prog[i - 1];
    prog[at].num = number;
    prog[at].text = dup_str(text);
    nlines++;
}

static void new_program(void)
{
    int i;
    for (i = 0; i < nlines; i++)
        free(prog[i].text);
    nlines = 0;
    clear_vars();
}

static void goto_line(int number)
{
    int i = find_line(number);
    if (i < 0)
        fail("UNDEFINED LINE");
    redirect = 1;
    rpc = i;
    rp = prog[i].text;
}

static void print_item(Val v, int *col)
{
    if (v.type == 1) {
        printf("%s", v.s);
        *col += strlen(v.s);
        free(v.s);
    } else {
        Val t = number_text(v.n);
        printf("%s ", t.s);
        *col += strlen(t.s) + 1;
        free(t.s);
    }
}

static void do_print(void)
{
    int col = 0, newline = 1;
    while (!at_end()) {
        newline = 1;
        if (*p == ';') {
            p++;
            newline = 0;
        } else if (*p == ',') {
            p++;
            do {
                putchar(' ');
                col++;
            } while (col % 8);
            newline = 0;
        } else {
            print_item(expr(), &col);
        }
    }
    if (newline)
        putchar('\n');
}

static int read_line(char *buf, int size)
{
    return get_line(buf, size) != 0;
}

static void do_input(void)
{
    char buf[MAX_LEN];
    skip();
    if (*p == '"') {
        const char *start = ++p;
        while (*p && *p != '"')
            p++;
        printf("%.*s", (int)(p - start), start);
        if (*p == '"')
            p++;
        skip();
        if (*p == ';' || *p == ',')
            p++;
    } else {
        printf("? ");
    }
    for (;;) {
        Var *v;
        int i;
        Val val;
        if (!read_line(buf, sizeof buf)) {
            printf("\n");
            fail("END OF INPUT");
        }
        buf[strcspn(buf, "\n")] = 0;
        v = get_slot(&i);
        if (v->is_str) {
            val = str(buf, strlen(buf));
        } else {
            char *end;
            float f = strtod(buf, &end);
            if (end == buf || *end) {
                printf("?REDO FROM START\n? ");
                continue;
            }
            val = num(f);
        }
        store(v, i, val);
        break;
    }
}

/* the colour: 0-15 are the usual sixteen, a bigger value is RGB565 as it is */
#ifndef BASIC_TEST
static int color_of(float f)
{
    static const int pal[16] = {
        GFX_BLACK, GFX_BLUE, GFX_GREEN, GFX_CYAN, GFX_RED, 0xF81F, GFX_ORANGE, GFX_GRAY,
        0x4208, 0x041F, 0x47E0, 0x47FF, 0xFA08, 0xFC1F, GFX_YELLOW, GFX_WHITE
    };
    int c = (int)f;
    return c >= 0 && c < 16 ? pal[c] : c;
}
static int pen = 15;
#endif

static float comma_num(void)
{
    skip();
    if (*p++ != ',')
        syntax();
    return need_num(expr());
}

static void do_graphics(int which)
{
#ifdef BASIC_TEST
    (void)which;
    fail("NO SCREEN");
#else
    float x, y, a, b, c;
    int col = pen;
    switch (which) {
    case 0: gfx_clear(); break;
    case 1:                                     /* PLOT x,y[,c] */
        x = need_num(expr());
        y = comma_num();
        skip();
        if (*p == ',') {
            c = comma_num();
            col = (int)c;
        }
        gfx_pixel((int)x, (int)y, color_of(col));
        break;
    case 2:                                     /* LINE x,y,x2,y2[,c] */
        x = need_num(expr());
        y = comma_num();
        a = comma_num();
        b = comma_num();
        skip();
        if (*p == ',')
            col = (int)comma_num();
        gfx_line((int)x, (int)y, (int)a, (int)b, color_of(col));
        break;
    case 3:                                     /* CIRCLE x,y,r[,c] */
        x = need_num(expr());
        y = comma_num();
        a = comma_num();
        skip();
        if (*p == ',')
            col = (int)comma_num();
        gfx_circle((int)x, (int)y, (int)a, color_of(col));
        break;
    case 4:                                     /* COLOR c */
        pen = (int)need_num(expr());
        break;
    case 5: {                                   /* TEXT x,y,s$[,c] */
        Val s;
        x = need_num(expr());
        y = comma_num();
        skip();
        if (*p++ != ',')
            syntax();
        s = expr();
        skip();
        if (*p == ',')
            col = (int)comma_num();
        gfx_text((int)x, (int)y, need_str(s), color_of(col), GFX_NONE);
        free(s.s);
        break;
    }
    }
    (void)c;
#endif
}

static void do_dim(void)
{
    do {
        char name[24];
        int is_str, n, j;
        Var *v;
        float f;
        if (!get_name(name, &is_str))
            syntax();
        skip();
        if (*p++ != '(')
            syntax();
        f = need_num(expr());
        skip();
        if (*p++ != ')')
            syntax();
        if (f < 0 || f >= MAX_ARRAY)
            fail("BAD SUBSCRIPT");
        n = (int)f + 1;
        v = find_var(name, is_str, 1);
        if (v->size)
            fail("REDIMENSIONED ARRAY");
        free(v->s[0]);
        free(v->n);
        free(v->s);
        v->size = n;
        v->n = malloc(n * sizeof(float));
        v->s = malloc(n * sizeof(char *));
        for (j = 0; j < n; j++) {
            v->n[j] = 0;
            v->s[j] = 0;
        }
        skip();
    } while (*p == ',' && p++);
}

/* READ: data_pos points at the next item of a DATA line (data_line is where to search
 * on when it is 0), items are separated by commas, strings may be quoted */
static int data_ready(void)
{
    while (!data_pos) {
        const char *t;
        if (data_line >= nlines)
            return 0;
        t = prog[data_line++].text;
        while (*t == ' ')
            t++;
        if (strncasecmp_(t, "DATA"))
            data_pos = t + 4;
    }
    return 1;
}

static void do_read(void)
{
    do {
        Var *v;
        int i;
        Val val;
        const char *q, *s0;
        v = get_slot(&i);
        if (!data_ready())
            fail("OUT OF DATA");
        q = data_pos;
        while (*q == ' ')
            q++;
        if (*q == '"') {
            s0 = ++q;
            while (*q && *q != '"')
                q++;
            val = str(s0, q - s0);
            if (*q == '"')
                q++;
            while (*q == ' ')
                q++;
        } else {
            const char *e;
            s0 = q;
            while (*q && *q != ',')
                q++;
            for (e = q; e > s0 && e[-1] == ' '; )
                e--;
            val = v->is_str ? str(s0, e - s0) : num(strtod(s0, 0));
        }
        data_pos = *q == ',' ? q + 1 : 0;       /* no comma: this line is used up */
        store(v, i, val);
        skip();
    } while (*p == ',' && p++);
}

static void go_to(int line, const char *pos)
{
    redirect = 1;
    rpc = line;
    rp = pos;
}

static void do_for(void)
{
    char name[24];
    int is_str, i;
    Var *v;
    float start, limit, step = 1;
    ForFrame *f;
    if (!get_name(name, &is_str) || is_str)
        syntax();
    skip();
    if (*p++ != '=')
        syntax();
    start = need_num(expr());
    if (!keyword("TO"))
        syntax();
    limit = need_num(expr());
    if (keyword("STEP"))
        step = need_num(expr());
    v = find_var(name, 0, 1);
    if (v->size)
        fail("BAD SUBSCRIPT");
    v->n[0] = start;
    for (i = 0; i < nfor; i++)                  /* the same variable again: restart its loop */
        if (fors[i].v == v) {
            nfor = i;
            break;
        }
    if (nfor == STACK)
        fail("TOO MANY LOOPS");
    f = &fors[nfor++];
    f->v = v;
    f->limit = limit;
    f->step = step;
    f->line = pc;
    f->pos = p;
}

static void do_next(void)
{
    char name[24];
    int is_str, i;
    Var *want = 0;
    ForFrame *f;
    if (get_name(name, &is_str))
        want = find_var(name, is_str, 0);
    for (i = nfor - 1; i >= 0; i--)
        if (!want || fors[i].v == want)
            break;
    if (i < 0)
        fail("NEXT WITHOUT FOR");
    nfor = i + 1;
    f = &fors[i];
    f->v->n[0] += f->step;
    if (f->step > 0 ? f->v->n[0] <= f->limit : f->v->n[0] >= f->limit)
        go_to(f->line, f->pos);
    else
        nfor = i;
}

static void statement(void);

/* a line number after THEN/GOTO/GOSUB */
static int line_number(void)
{
    char *end;
    long n;
    skip();
    if (!isdigit((unsigned char)*p))
        syntax();
    n = strtol(p, &end, 10);
    p = end;
    return (int)n;
}

static void statement(void);

static void skip_to_else_or_end(void)
{
    int quote = 0;
    while (*p) {
        if (*p == '"')
            quote = !quote;
        if (!quote && toupper((unsigned char)p[0]) == 'E' && toupper((unsigned char)p[1]) == 'L' &&
            toupper((unsigned char)p[2]) == 'S' && toupper((unsigned char)p[3]) == 'E')
            return;
        p++;
    }
}

static void do_if(void)
{
    Val c = expr();
    float f = need_num(c);
    if (!keyword("THEN"))
        syntax();
    skip();
    if (f != 0) {
        if (isdigit((unsigned char)*p))
            goto_line(line_number());
        else
            statement();                        /* the THEN part; execute() skips an ELSE after it */
    } else {
        skip_to_else_or_end();
        if (keyword("ELSE")) {
            skip();
            if (isdigit((unsigned char)*p))
                goto_line(line_number());
            else
                statement();
        } else {
            while (*p)
                p++;                            /* nothing to run on this line */
        }
    }
}

/* from p, the end of the WEND that matches the WHILE being skipped: sets p and pc */
static void find_wend(void)
{
    int depth = 1, quote = 0;
    const char *t = p;
    for (;;) {
        for (; *t; t++) {
            if (*t == '"')
                quote = !quote;
            if (quote || (t > prog[pc].text && (isalnum((unsigned char)t[-1]))))
                continue;
            if (same_word(t, "WHILE"))
                depth++;
            else if (same_word(t, "WEND") && --depth == 0) {
                p = t + 4;
                return;
            }
        }
        if (pc + 1 >= nlines)
            fail("WHILE WITHOUT WEND");
        pc++;
        t = prog[pc].text;
        quote = 0;
    }
}

static void statement(void)
{
    skip();
    stmt_start = p;
    if (*p == 0 || *p == ':')
        return;
    if (*p == '?') {
        p++;
        do_print();
        return;
    }
    if (keyword("REM") || *p == '\'') {
        while (*p)
            p++;
        return;
    }
    if (keyword("PRINT")) { do_print(); return; }
    if (keyword("LET")) {
        Var *v;
        int i;
        v = get_slot(&i);
        skip();
        if (*p++ != '=')
            syntax();
        store(v, i, expr());
        return;
    }
    if (keyword("IF")) { do_if(); return; }
    if (keyword("ELSE")) {                      /* reached after a THEN part ran: the ELSE part is not run */
        while (*p)
            p++;
        return;
    }
    if (keyword("GOTO")) { goto_line(line_number()); return; }
    if (keyword("GOSUB")) {
        int n = line_number();
        if (ngosub == STACK)
            fail("TOO MANY GOSUBS");
        gosubs[ngosub].line = pc;
        gosubs[ngosub++].pos = p;
        goto_line(n);
        return;
    }
    if (keyword("RETURN")) {
        if (!ngosub)
            fail("RETURN WITHOUT GOSUB");
        ngosub--;
        go_to(gosubs[ngosub].line, gosubs[ngosub].pos);
        return;
    }
    if (keyword("FOR")) { do_for(); return; }
    if (keyword("NEXT")) { do_next(); return; }
    if (keyword("WHILE")) {
        const char *at = stmt_start;
        int top = nwhile && whiles[nwhile - 1].line == pc && whiles[nwhile - 1].pos == at;
        if (need_num(expr()) != 0) {
            if (!top) {
                if (nwhile == STACK)
                    fail("TOO MANY LOOPS");
                whiles[nwhile].line = pc;
                whiles[nwhile++].pos = at;
            }
        } else {
            if (top)
                nwhile--;
            find_wend();                        /* leaves pc and p after the matching WEND */
            go_to(pc, p);
        }
        return;
    }
    if (keyword("WEND")) {
        if (!nwhile)
            fail("WEND WITHOUT WHILE");
        go_to(whiles[nwhile - 1].line, whiles[nwhile - 1].pos);
        return;
    }
    if (keyword("DIM")) { do_dim(); return; }
    if (keyword("INPUT")) { do_input(); return; }
    if (keyword("DATA")) {
        while (*p)
            p++;
        return;
    }
    if (keyword("READ")) { do_read(); return; }
    if (keyword("RESTORE")) {
        data_line = 0;
        data_pos = 0;
        return;
    }
    if (keyword("RANDOMIZE")) {
        rng = at_end() ? (unsigned)clock() : (unsigned)need_num(expr());
        return;
    }
    if (keyword("SLEEP")) {
        float ms = need_num(expr());
#ifndef BASIC_TEST
        wait_ms((unsigned)ms);
#else
        (void)ms;
#endif
        return;
    }
    if (keyword("CLS")) { do_graphics(0); return; }
    if (keyword("PLOT")) { do_graphics(1); return; }
    if (keyword("LINE")) { do_graphics(2); return; }
    if (keyword("CIRCLE")) { do_graphics(3); return; }
    if (keyword("COLOR")) { do_graphics(4); return; }
    if (keyword("TEXT")) { do_graphics(5); return; }
    if (keyword("END") || keyword("STOP")) {
        done = 1;
        return;
    }
    if (isalpha((unsigned char)*p)) {
        Var *v;
        int i;
        v = get_slot(&i);
        skip();
        if (*p++ != '=')
            syntax();
        store(v, i, expr());
        return;
    }
    syntax();
}

/* run statements from text (line `line`, -1 for a typed line) on, following
 * GOTO, GOSUB, NEXT ... through the program until END or the last line */
static void execute(int line, const char *text)
{
    pc = line;
    p = text;
    done = 0;
    cur_num = pc >= 0 ? prog[pc].num : -1;
    while (!done) {
        redirect = 0;
        statement();
        if (redirect) {
            pc = rpc;
            p = rp;
            cur_num = prog[pc].num;
            continue;
        }
        skip();
        if (*p == ':') {
            p++;
            continue;
        }
        if (same_word(p, "ELSE"))               /* the THEN part ran: the ELSE part is not */
            while (*p)
                p++;
        if (*p != 0)
            syntax();
        if (pc < 0 || ++pc >= nlines)
            break;                              /* the end of a typed line, or of the program */
        p = prog[pc].text;
        cur_num = prog[pc].num;
    }
    pc = -1;
}

static void run_program(int from)
{
    ngosub = nfor = nwhile = 0;
    data_line = 0;
    data_pos = 0;
    if (from < nlines)
        execute(from, prog[from].text);
}

static void list_program(const char *args)
{
    int lo = 0, hi = 1 << 30, i;
    char *end;
    while (*args == ' ')
        args++;
    if (*args) {
        if (isdigit((unsigned char)*args))
            lo = hi = (int)strtol(args, &end, 10), args = end;
        if (*args == '-') {
            args++;
            hi = isdigit((unsigned char)*args) ? (int)strtol(args, 0, 10) : 1 << 30;
        }
    }
    for (i = 0; i < nlines; i++)
        if (prog[i].num >= lo && prog[i].num <= hi)
            printf("%d %s\n", prog[i].num, prog[i].text);
}

static void file_name(const char *args, char *out)
{
    const char *q = args;
    while (*q == ' ')
        q++;
    if (*q != '"') {
        out[0] = 0;
        return;
    }
    q++;
    while (*q && *q != '"')
        *out++ = *q++;
    *out = 0;
}

static void save_program(const char *args)
{
    char name[100];
    FILE *f;
    int i;
    file_name(args, name);
    if (!name[0]) {
        printf("?SYNTAX ERROR\n");
        return;
    }
    f = fopen(name, "w");
    if (!f) {
        printf("?CANNOT WRITE %s\n", name);
        return;
    }
    for (i = 0; i < nlines; i++)
        fprintf(f, "%d %s\n", prog[i].num, prog[i].text);
    fclose(f);
}

static int enter_line(char *line);

static int load_program(const char *name)
{
    FILE *f = fopen(name, "r");
    char buf[MAX_LEN + 20];
    if (!f)
        return 0;
    new_program();
    while (fgets(buf, sizeof buf, f)) {
        buf[strcspn(buf, "\n")] = 0;
        enter_line(buf);
    }
    fclose(f);
    return 1;
}

/* one line typed at the prompt or loaded from a file: a numbered one is stored,
 * a command or a statement runs at once. Returns 0 on BYE. */
static int enter_line(char *line)
{
    char *s = line;
    while (*s == ' ')
        s++;
    if (!*s)
        return 1;
    if (isdigit((unsigned char)*s)) {
        char *end;
        long n = strtol(s, &end, 10);
        while (*end == ' ')
            end++;
        put_line((int)n, end);
        return 1;
    }
    cur_num = -1;
    if (setjmp(on_error)) {
        pc = -1;
        return 1;
    }
    {
        char up[8];
        int i;
        for (i = 0; i < 7 && s[i] && s[i] != ' '; i++)
            up[i] = toupper((unsigned char)s[i]);
        up[i] = 0;
        if (strcmp(up, "RUN") == 0) {
            clear_vars();
            run_program(0);
        } else if (strcmp(up, "LIST") == 0) {
            list_program(s + 4);
        } else if (strcmp(up, "NEW") == 0) {
            new_program();
        } else if (strcmp(up, "SAVE") == 0) {
            save_program(s + 4);
        } else if (strcmp(up, "LOAD") == 0) {
            char name[100];
            file_name(s + 4, name);
            if (!name[0] || !load_program(name))
                printf("?CANNOT READ %s\n", name);
        } else if (strcmp(up, "BYE") == 0 || strcmp(up, "QUIT") == 0 || strcmp(up, "SYSTEM") == 0) {
            return 0;
        } else {
            execute(-1, s);                     /* a GOTO typed at the prompt runs the program from there */
        }
    }
    return 1;
}

static char *stdin_line(char *buf, int size)
{
    return fgets(buf, size, stdin);
}

/* the interactive loop; returns when the input ends or BYE is entered */
int basic_loop(int prompt)
{
    char buf[MAX_LEN];
    for (;;) {
        if (prompt)
            printf("> ");
        if (!get_line(buf, sizeof buf))
            return 0;
        buf[strcspn(buf, "\n")] = 0;
        if (!enter_line(buf))
            return 0;
    }
}

/* `basic file.bas`: load and run; the error count is the exit status */
int basic_main(int argc, char **argv)
{
    get_line = stdin_line;
    if (argc >= 2) {
        if (!load_program(argv[1])) {
            printf("basic: cannot read %s\n", argv[1]);
            return 1;
        }
        {
            int errors = 0;
            cur_num = -1;
            if (setjmp(on_error))
                return 1;
            clear_vars();
            run_program(0);
            return errors;
        }
    }
    printf("tiny BASIC: type a line, RUN, LIST, NEW, SAVE \"f\", LOAD \"f\", BYE\n");
    basic_loop(1);
    return 0;
}

#ifndef BASIC_TEST
int main(int argc, char **argv)
{
    return basic_main(argc, argv);
}
#endif
