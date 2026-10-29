/* grapher.c - a graphing calculator on the RGB screen
 *
 * python compiler/src/cc build compiler/examples/c/graphics/grapher.c, then open
 *     compiler/ROM/grapher.rom in the simulator window (the "RGB screen"
 *     tab) and type on its keyboard
 * python compiler/src/cc run compiler/examples/c/graphics/grapher.c --steps 50000000 \
 *     --keys $'sin(x)\nx^2/4-3\nclear\n' --screen graph.png
 *
 * At the start the screen lists what can be typed (and so does the text
 * display). Type a function of x on the bottom line and press Enter: it is
 * drawn on top of the ones before (up to six, each in its own colour, two
 * pixels thick) over a grid with numbers on the axes. "y=" or
 * "f(x)=" in front is allowed. The expression is parsed into a little stack
 * program once, then run for every column of pixels.
 *
 *   numbers     2, 0.5, 1e3        x, pi, e
 *   operators   + - * / ^ (power, right to left: 2^3^2 = 512), unary -,
 *               ( ), |x| for abs, and implied products: 2x, 3sin(x), x(x+1)
 *   functions   sin cos tan asin acos atan sinh cosh tanh sqrt abs exp
 *               ln log (base 10) floor ceil round sign
 *
 * Commands (typed the same way, then Enter):
 *   clear              remove every function
 *   reset              back to x -8..8, y -7..7
 *   zoom f             zoom in by f around the middle (zoom 0.5 zooms out)
 *   in, out            zoom 2, zoom 0.5
 *   move dx dy         slide the view by (dx, dy) in graph units
 *   view x0 x1 y0 y1   show exactly that window
 *   demo               draw a few example functions
 *   help               the list of what can be typed, again
 *
 * Values that are not numbers (sqrt(-1), ln(0)) leave a gap, and so do
 * jumps like tan's: two neighbouring columns are joined only if the value
 * halfway between them lies between theirs. The text display gets each
 * function, every view change and the time a drawing took.
 *
 * Drawing one function takes 100-200 ms in the simulator under plain
 * python. Not for the circuit (160 instructions a second, and it still has
 * the old memory map).
 *
 * Expected output with --keys $'sin(x)\nx^2/4-3\nclear\n' (the times change):
 *   Grapher: type a function of x, then Enter
 *     numbers     2, 0.5, 1e3        x, pi, e
 *     ... (the rest of the list)
 *   y1 = sin(x)  (149 ms)
 *   y2 = x^2/4-3  (173 ms)
 *   cleared
 */
#include <cpu.h>
#include <gfx.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define GRAPH_H 112                     /* rows 0-111 graph, 112-119 status, 120-127 input */
#define STATUS_Y 112
#define INPUT_Y 120
#define MAX_LINE 60
#define MAX_CODE 128                    /* stack program words */
#define MAX_CONST 32
#define MAX_STACK 64
#define MAX_FUNCS 6

#define BACKGROUND GFX_WHITE
#define GRID       GFX_RGB(225, 225, 225)
#define AXES       GFX_RGB(110, 110, 110)
#define BAR        GFX_RGB(30, 20, 40)
#define BAR_TEXT   GFX_WHITE
#define ERROR      GFX_RGB(255, 90, 90)

static const int colors[MAX_FUNCS] = {
    GFX_RGB(0x82, 0x0A, 0xD1),          /* purple */
    GFX_RGB(0, 150, 220),               /* blue */
    GFX_RGB(240, 120, 0),               /* orange */
    GFX_RGB(0, 160, 70),                /* green */
    GFX_RGB(220, 30, 60),               /* red */
    GFX_RGB(200, 160, 0),               /* yellow */
};

/* ---- the stack program ---------------------------------------------- */

enum {
    OP_CONST, OP_X, OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_POW, OP_NEG,
    OP_SIN, OP_COS, OP_TAN, OP_ASIN, OP_ACOS, OP_ATAN, OP_SINH, OP_COSH,
    OP_TANH, OP_SQRT, OP_ABS, OP_EXP, OP_LN, OP_LOG, OP_FLOOR, OP_CEIL,
    OP_ROUND, OP_SIGN
};

struct func {
    char text[MAX_LINE + 1];
    int code[MAX_CODE];                 /* OP_CONST is followed by a constant's index */
    int length;
    double consts[MAX_CONST];
    int nconsts;
};

static struct func funcs[MAX_FUNCS];
static int nfuncs;

static double eval(const struct func *f, double x)
{
    double stack[MAX_STACK];
    int sp = 0, pc = 0;
    double a;
    while (pc < f->length) {
        int op = f->code[pc++];
        if (op == OP_CONST) {
            stack[sp++] = f->consts[f->code[pc++]];
            continue;
        }
        if (op == OP_X) {
            stack[sp++] = x;
            continue;
        }
        if (op <= OP_POW) {             /* two operands */
            double b = stack[--sp];
            a = stack[sp - 1];
            switch (op) {
            case OP_ADD: a = a + b; break;
            case OP_SUB: a = a - b; break;
            case OP_MUL: a = a * b; break;
            case OP_DIV: a = a / b; break;
            default:     a = pow(a, b); break;
            }
            stack[sp - 1] = a;
            continue;
        }
        a = stack[sp - 1];
        switch (op) {
        case OP_NEG:   a = -a; break;
        case OP_SIN:   a = sin(a); break;
        case OP_COS:   a = cos(a); break;
        case OP_TAN:   a = tan(a); break;
        case OP_ASIN:  a = asin(a); break;
        case OP_ACOS:  a = acos(a); break;
        case OP_ATAN:  a = atan(a); break;
        case OP_SINH:  a = sinh(a); break;
        case OP_COSH:  a = cosh(a); break;
        case OP_TANH:  a = tanh(a); break;
        case OP_SQRT:  a = sqrt(a); break;
        case OP_ABS:   a = fabs(a); break;
        case OP_EXP:   a = exp(a); break;
        case OP_LN:    a = log(a); break;
        case OP_LOG:   a = log10(a); break;
        case OP_FLOOR: a = floor(a); break;
        case OP_CEIL:  a = ceil(a); break;
        case OP_ROUND: a = round(a); break;
        default:       a = a > 0 ? 1.0 : a < 0 ? -1.0 : a; break;
        }
        stack[sp - 1] = a;
    }
    return stack[0];
}

/* ---- the parser: recursive descent, writing the stack program ------- */

struct name {
    const char *text;
    int op;                             /* -1 x, -2 pi, -3 e */
};

static const struct name names[] = {
    {"asin", OP_ASIN}, {"acos", OP_ACOS}, {"atan", OP_ATAN},
    {"sinh", OP_SINH}, {"cosh", OP_COSH}, {"tanh", OP_TANH},
    {"sin", OP_SIN}, {"cos", OP_COS}, {"tan", OP_TAN},
    {"sqrt", OP_SQRT}, {"abs", OP_ABS}, {"exp", OP_EXP},
    {"ln", OP_LN}, {"log", OP_LOG}, {"floor", OP_FLOOR},
    {"ceil", OP_CEIL}, {"round", OP_ROUND}, {"sign", OP_SIGN},
    {"pi", -2}, {"x", -1}, {"e", -3},
};
#define NNAMES ((int)(sizeof(names) / sizeof(names[0])))

static const char *src;                 /* the expression being parsed */
static int pos;
static const char *error;               /* the first error, or 0 */
static int error_pos;
static struct func *out;
static int depth, max_depth;            /* stack use of the program so far */

static void fail(const char *message)
{
    if (!error) {
        error = message;
        error_pos = pos;
    }
}

static void skip_spaces(void)
{
    while (src[pos] == ' ')
        pos++;
}

static void emit(int op)
{
    if (out->length >= MAX_CODE) {
        fail("too long");
        return;
    }
    out->code[out->length++] = op;
    if (op == OP_X)
        depth++;
    else if (op >= OP_ADD && op <= OP_POW)
        depth--;
    if (depth > max_depth)
        max_depth = depth;
}

static void emit_const(double value)
{
    if (out->nconsts >= MAX_CONST) {
        fail("too many numbers");
        return;
    }
    emit(OP_CONST);
    emit(out->nconsts);
    out->consts[out->nconsts++] = value;
    depth++;
    if (depth > max_depth)
        max_depth = depth;
}

/* the longest name starting at pos, or -1 */
static int match_name(void)
{
    int i, best = -1, best_len = 0;
    for (i = 0; i < NNAMES; i++) {
        int len = strlen(names[i].text);
        if (len > best_len && strncmp(src + pos, names[i].text, len) == 0) {
            best = i;
            best_len = len;
        }
    }
    return best;
}

static int starts_primary(void)
{
    char c;
    skip_spaces();
    c = src[pos];
    return (c >= '0' && c <= '9') || c == '.' || c == '(' || match_name() >= 0;
}

static void parse_expr(void);
static void parse_unary(void);

static void expect(char c)
{
    skip_spaces();
    if (src[pos] == c)
        pos++;
    else if (c == ')')
        fail("missing )");
    else
        fail("missing |");
}

static void parse_primary(void)
{
    char c;
    int n;
    skip_spaces();
    c = src[pos];
    if ((c >= '0' && c <= '9') || c == '.') {
        char *end;
        double value = strtod(src + pos, &end);
        if (end == src + pos) {
            fail("bad number");
            return;
        }
        pos = end - src;
        emit_const(value);
    } else if (c == '(') {
        pos++;
        parse_expr();
        expect(')');
    } else if (c == '|') {
        pos++;
        parse_expr();
        expect('|');
        emit(OP_ABS);
    } else if ((n = match_name()) >= 0) {
        pos += strlen(names[n].text);
        if (names[n].op == -1)
            emit(OP_X);
        else if (names[n].op == -2)
            emit_const(M_PI);
        else if (names[n].op == -3)
            emit_const(M_E);
        else {
            /* a function: sin(x), or sin x, or sin 2x */
            skip_spaces();
            if (src[pos] == '(') {
                pos++;
                parse_expr();
                expect(')');
            } else
                parse_unary();
            emit(names[n].op);
        }
    } else if (c == 0)
        fail("unfinished");
    else
        fail("unexpected character");
}

static void parse_power(void)
{
    parse_primary();
    skip_spaces();
    if (src[pos] == '^') {
        pos++;
        parse_unary();                  /* right to left, and 2^-x works */
        emit(OP_POW);
    }
}

static void parse_unary(void)
{
    skip_spaces();
    if (src[pos] == '-') {
        pos++;
        parse_unary();
        emit(OP_NEG);
    } else if (src[pos] == '+') {
        pos++;
        parse_unary();
    } else
        parse_power();
}

static void parse_term(void)
{
    parse_unary();
    while (!error) {
        skip_spaces();
        if (src[pos] == '*' || src[pos] == '/') {
            int op = src[pos] == '*' ? OP_MUL : OP_DIV;
            pos++;
            parse_unary();
            emit(op);
        } else if (starts_primary()) {
            parse_power();              /* 2x, 3sin(x), x(x+1); never "|", which may close an |abs| */
            emit(OP_MUL);
        } else
            break;
    }
}

static void parse_expr(void)
{
    parse_term();
    while (!error) {
        skip_spaces();
        if (src[pos] == '+' || src[pos] == '-') {
            int op = src[pos] == '+' ? OP_ADD : OP_SUB;
            pos++;
            parse_term();
            emit(op);
        } else
            break;
    }
}

/* parse text into f; 0 if it worked, else error/error_pos say why */
static int compile(const char *text, struct func *f)
{
    const char *eq = strchr(text, '=');
    src = eq ? eq + 1 : text;           /* y=..., f(x)=... */
    pos = 0;
    error = 0;
    out = f;
    f->length = 0;
    f->nconsts = 0;
    depth = max_depth = 0;
    parse_expr();
    skip_spaces();
    if (!error && src[pos] == ')')
        fail("extra )");
    if (!error && src[pos] != 0)
        fail("unexpected character");
    if (!error && max_depth > MAX_STACK)
        fail("too deep");
    if (eq)
        error_pos += eq + 1 - text;
    return error != 0;
}

/* ---- the view and the drawing ---------------------------------------- */

static double x0, x1, y0, y1;           /* the window, in graph units */

static int to_row(double y)             /* clamped far outside the graph */
{
    double r = (y1 - y) / (y1 - y0) * GRAPH_H;
    if (r < -1000)
        r = -1000;
    if (r > 1000 + GRAPH_H)
        r = 1000 + GRAPH_H;
    return (int)floor(r);
}

static int to_column(double x)
{
    return (int)floor((x - x0) / (x1 - x0) * GFX_WIDTH);
}

static double column_x(double column)
{
    return x0 + (column + 0.5) * (x1 - x0) / GFX_WIDTH;
}

/* a round grid step (1, 2 or 5 times a power of 10) giving 4-10 lines */
static double grid_step(double range)
{
    double raw = range / 7, mag = pow(10, floor(log10(raw))), n = raw / mag;
    return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag;
}

/* the axes' numbers: x ones under the x axis, y ones right of the y axis;
   at the graph's edge when an axis is off the screen. A number that would
   touch the one before is left out, and so is 0. */
static void draw_numbers(int axis_c, int axis_r)
{
    char text[16];
    double step, v;
    int c, r, w, last_end = -100;
    int r_text = axis_r + 2, c_text = axis_c + 2;
    if (r_text < 0)
        r_text = 0;
    if (r_text > GRAPH_H - GFX_CHAR_HEIGHT)
        r_text = axis_r - GFX_CHAR_HEIGHT < 0 ? GRAPH_H - GFX_CHAR_HEIGHT : axis_r - GFX_CHAR_HEIGHT;
    step = grid_step(x1 - x0);
    for (v = ceil(x0 / step) * step; v <= x1; v += step) {
        if (fabs(v) < step / 2)
            continue;
        sprintf(text, "%g", v);
        w = strlen(text) * GFX_CHAR_WIDTH;
        c = to_column(v) - w / 2;
        if (c < 0 || c + w > GFX_WIDTH || c < last_end + 2)
            continue;
        gfx_text(c, r_text, text, AXES, GFX_NONE);
        last_end = c + w;
    }
    step = grid_step(y1 - y0);
    last_end = -100;
    for (v = floor(y1 / step) * step; v >= y0; v -= step) {
        if (fabs(v) < step / 2)
            continue;
        sprintf(text, "%g", v);
        w = strlen(text) * GFX_CHAR_WIDTH;
        c = c_text < 0 ? 0 : c_text + w > GFX_WIDTH ? axis_c - 1 - w : c_text;
        if (c < 0)
            c = GFX_WIDTH - w;
        r = to_row(v) - GFX_CHAR_HEIGHT / 2;
        if (r < 0 || r + GFX_CHAR_HEIGHT > GRAPH_H || r < last_end + 1)
            continue;
        gfx_text(c, r, text, AXES, GFX_NONE);
        last_end = r + GFX_CHAR_HEIGHT;
    }
}

static void draw_grid(void)
{
    double step, v;
    int c, r;
    gfx_fill_rect(0, 0, GFX_WIDTH, GRAPH_H, BACKGROUND);
    step = grid_step(x1 - x0);
    for (v = ceil(x0 / step) * step; v <= x1; v += step)
        gfx_vline(to_column(v), 0, GRAPH_H, GRID);
    step = grid_step(y1 - y0);
    for (v = ceil(y0 / step) * step; v <= y1; v += step)
        gfx_hline(0, to_row(v), GFX_WIDTH, GRID);
    c = to_column(0);
    r = to_row(0);
    if (c >= 0 && c < GFX_WIDTH)
        gfx_vline(c, 0, GRAPH_H, AXES);
    if (r >= 0 && r < GRAPH_H)
        gfx_hline(0, r, GFX_WIDTH, AXES);
    draw_numbers(c, r);
}

/* column c from row a to row b (either order), clipped to the graph, and
   one pixel more right and down: the curves are two pixels thick */
static void span(int c, int a, int b, int color)
{
    int t;
    if (a > b) {
        t = a;
        a = b;
        b = t;
    }
    b++;
    if (a < 0)
        a = 0;
    if (b > GRAPH_H - 1)
        b = GRAPH_H - 1;
    if (a <= b) {
        gfx_vline(c, a, b - a + 1, color);
        if (c + 1 < GFX_WIDTH)
            gfx_vline(c + 1, a, b - a + 1, color);
    }
}

static void draw_func(const struct func *f, int color)
{
    int c, row, prev_row = 0, have_prev = 0;
    double y, prev_y = 0;
    for (c = 0; c < GFX_WIDTH; c++) {
        y = eval(f, column_x(c));
        if (!isfinite(y)) {
            have_prev = 0;
            continue;
        }
        row = to_row(y);
        if (have_prev && abs(row - prev_row) > 1) {
            /* joined only if the value halfway lies between the two */
            double mid = eval(f, column_x(c - 0.5));
            double lo = prev_y < y ? prev_y : y, hi = prev_y < y ? y : prev_y;
            if (isfinite(mid) && mid >= lo && mid <= hi)
                span(c, prev_row + (row > prev_row ? 1 : -1), row, color);
            else
                span(c, row, row, color);
        } else
            span(c, row, row, color);
        prev_row = row;
        prev_y = y;
        have_prev = 1;
    }
}

static void status(const char *text, int color)
{
    gfx_fill_rect(0, STATUS_Y, GFX_WIDTH, 8, BAR);
    gfx_text(1, STATUS_Y, text, color, GFX_NONE);
}

static void redraw(void)
{
    int i;
    draw_grid();
    for (i = 0; i < nfuncs; i++)
        draw_func(&funcs[i], colors[i]);
}

static void show_view(void)
{
    char text[40];
    printf("view x %g..%g, y %g..%g\n", x0, x1, y0, y1);
    sprintf(text, "x %g..%g", x0, x1);
    status(text, BAR_TEXT);
}

static void set_view(double a, double b, double c, double d)
{
    x0 = a;
    x1 = b;
    y0 = c;
    y1 = d;
    redraw();
    show_view();
}

/* ---- the input line --------------------------------------------------- */

static char line[MAX_LINE + 1];
static int line_len;

#define INPUT_CHARS 20                  /* after the "> " */

static void draw_input(void)
{
    int start = line_len > INPUT_CHARS - 1 ? line_len - (INPUT_CHARS - 1) : 0;
    int x;
    gfx_fill_rect(0, INPUT_Y, GFX_WIDTH, 8, BAR);
    x = gfx_text(1, INPUT_Y, ">", colors[nfuncs < MAX_FUNCS ? nfuncs : 0], GFX_NONE);
    x = gfx_text(x, INPUT_Y, line + start, BAR_TEXT, GFX_NONE);
    gfx_fill_rect(x, INPUT_Y + 7, 5, 1, BAR_TEXT);      /* the cursor */
}

/* the words of a command: name and up to four numbers; their count, or -1 */
static int split(const char *text, char *name, double *args)
{
    int n = 0, i = 0;
    char *end;
    while (*text == ' ')
        text++;
    while (*text >= 'a' && *text <= 'z' && i < 15)
        name[i++] = *text++;
    name[i] = 0;
    for (;;) {
        while (*text == ' ')
            text++;
        if (*text == 0)
            return n;
        if (n == 4)
            return -1;
        args[n] = strtod(text, &end);
        if (end == text)
            return -1;
        text = end;
        n++;
    }
}

/* what can be typed: on the screen until the first command, and on the
   text display at the start */
static const char *const help[] = {
    "Type f(x), Enter",
    "",
    "+ - * / ^  ( )  |x|",
    "2x  3sin(x)  pi  e",
    "sin cos tan sqrt",
    "asin acos atan exp",
    "sinh cosh tanh abs",
    "ln log floor ceil",
    "round sign",
    "",
    "clear reset in out",
    "zoom f  move dx dy",
    "view x0 x1 y0 y1",
    "demo help",
};
#define HELP_LINES ((int)(sizeof(help) / sizeof(help[0])))

static int help_shown;

static void show_help(void)
{
    int i;
    gfx_fill_rect(0, 0, GFX_WIDTH, GRAPH_H, BACKGROUND);
    for (i = 0; i < HELP_LINES; i++)
        gfx_text(3, i * GFX_CHAR_HEIGHT, help[i],
                 i == 0 ? colors[0] : i >= 10 ? colors[1] : GFX_BLACK, GFX_NONE);
    help_shown = 1;
}

static void print_help(void)
{
    printf("  numbers     2, 0.5, 1e3        x, pi, e\n"
           "  operators   + - * / ^ ( ), unary -, |x| for abs,\n"
           "              implied products: 2x, 3sin(x), x(x+1)\n"
           "  functions   sin cos tan asin acos atan sinh cosh tanh\n"
           "              sqrt abs exp ln log floor ceil round sign\n"
           "  commands    clear, reset, zoom f, in, out, move dx dy,\n"
           "              view x0 x1 y0 y1, demo, help\n");
}

static void add_func(const char *text)
{
    struct func *f = &funcs[nfuncs < MAX_FUNCS ? nfuncs : MAX_FUNCS - 1];
    char message[40];
    clock_t start;
    if (nfuncs == MAX_FUNCS) {
        /* full: the oldest goes */
        memmove(&funcs[0], &funcs[1], (MAX_FUNCS - 1) * sizeof(struct func));
        nfuncs--;
        redraw();
    }
    if (compile(text, f)) {
        printf("error: %s\n  %s\n  %*s^\n", error, text, error_pos, "");
        sprintf(message, "%d: %s", error_pos + 1, error);
        status(message, ERROR);
        return;
    }
    strcpy(f->text, text);
    start = clock();
    draw_func(f, colors[nfuncs]);
    nfuncs++;
    printf("y%d = %s  (%d ms)\n", nfuncs, text, (int)(clock() - start));
    sprintf(message, "y%d=%s", nfuncs, text);
    status(message, colors[nfuncs - 1]);
}

static void command(const char *text)
{
    char name[16];
    double args[4], cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    int n = split(text, name, args);
    if (n == 0 && strcmp(name, "help") == 0) {
        show_help();
        print_help();
        return;
    }
    if (help_shown) {
        help_shown = 0;
        redraw();
    }
    if (n == 0 && strcmp(name, "clear") == 0) {
        nfuncs = 0;
        redraw();
        printf("cleared\n");
        status("cleared", BAR_TEXT);
    } else if (n == 0 && strcmp(name, "reset") == 0)
        set_view(-8, 8, -7, 7);
    else if ((n == 1 && strcmp(name, "zoom") == 0 && args[0] > 0)
             || (n == 0 && (strcmp(name, "in") == 0 || strcmp(name, "out") == 0))) {
        double k = n == 1 ? 1 / args[0] : name[0] == 'i' ? 0.5 : 2;
        set_view(cx - (cx - x0) * k, cx + (x1 - cx) * k,
                 cy - (cy - y0) * k, cy + (y1 - cy) * k);
    } else if (n == 2 && strcmp(name, "move") == 0)
        set_view(x0 + args[0], x1 + args[0], y0 + args[1], y1 + args[1]);
    else if (n == 4 && strcmp(name, "view") == 0 && args[0] < args[1] && args[2] < args[3])
        set_view(args[0], args[1], args[2], args[3]);
    else if (n == 0 && strcmp(name, "demo") == 0) {
        add_func("sin(x)");
        add_func("x^2/4-3");
        add_func("2cos(x/2)+|x|/2");
        add_func("tan(x)");
    } else
        add_func(text);
}

int main(void)
{
    int key;
    printf("Grapher: type a function of x, then Enter\n");
    print_help();
    x0 = -8;
    x1 = 8;
    y0 = -7;
    y1 = 7;
    show_help();
    status("type help to see this", BAR_TEXT);
    draw_input();
    for (;;) {
        key = wait_key();
        if (key == '\n') {
            if (line_len > 0) {
                command(line);
                line_len = 0;
                line[0] = 0;
            }
        } else if (key == 8) {
            if (line_len > 0)
                line[--line_len] = 0;
        } else if (key == 4)            /* Ctrl-D: the end of --keys input */
            break;
        else if (key >= 'A' && key <= 'Z' && line_len < MAX_LINE) {
            line[line_len++] = key - 'A' + 'a';
            line[line_len] = 0;
        } else if (key >= 32 && key < 127 && line_len < MAX_LINE) {
            line[line_len++] = key;
            line[line_len] = 0;
        }
        draw_input();
    }
    return 0;
}
