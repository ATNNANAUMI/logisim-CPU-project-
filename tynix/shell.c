/* shell.c - Tynix's shell: /bin/sh, the first program the kernel starts
 * (tynix/kernel.c; simulator only)
 *
 *   python tynix/make_disk.py             (tynix/disk.img: this shell built --exe
 *                                          as /bin/sh, the examples in /bin)
 *   python compiler/src/cc build tynix/kernel.c
 *   python cpu_sim/src/main.py compiler/ROM/kernel.rom --disk tynix/disk.img
 *   (or: python compiler/src/cc run tynix/kernel.c --disk tynix/disk.img
 *    --keys $'ls /bin\nprimes\nhalt\n')
 *
 * A prompt with the current directory. The built-in commands (help lists
 * them) work on the files: ls cd pwd cat echo rm mv cp mkdir rmdir df clear
 * halt, and on the programs that run: jobs fg kill wait. Any other name is a
 * program: /bin/NAME, or a path when the name has a '/' (./prog,
 * /games/snake), which the kernel loads next to the others and runs in the
 * current directory; the shell waits for it, or with `&` at the end of the
 * line, doesn't (it runs in the background: it can print, but it waits for
 * the keyboard and the screen until `fg` brings it forward). A program that
 * can't be loaded gives a message and the shell goes on.
 *
 * Words are split at spaces; "..." or '...' keep spaces inside one word, and
 * \ keeps the next char as it is. # starts a comment (at the start of a
 * word). Output can go to a file: `echo hi > a.txt`, `ls >> list.txt`, and a
 * program's too: `primes > p.txt` (what it prints with printf, putchar and
 * puts; its input is the keyboard unless `<` gives a file, below, and its own errors the display). `cat` with no
 * file copies the keyboard up to Ctrl-D, so `cat > notes.txt` writes a
 * file. Ctrl-D at the prompt, or `halt`, stops the CPU.
 *
 * Input can come from a file: `ed notes.txt < edits.txt` gives the program
 * that file as its stdin (getchar, fgets and scanf read it, EOF at its end;
 * key_pressed() and wait_key() still read the keyboard); `cat < f` is
 * `cat f`, `read` reads it too, and other built-ins refuse `<`.
 *
 * The NMI (Esc) belongs to the kernel: on the program in front it asks
 * kill / continue / background / tasks; "background" gives the keyboard
 * back to this shell, which prints the job's number.
 *
 * At the prompt, Up and Down bring back the last 32 lines and Tab completes
 * the word being typed (a command from the built-ins, aliases, functions
 * and $PATH, else a path; several names are listed). The cursor stays at
 * the end of the line. A line that leaves something open (a quote, an if
 * without its fi, a | or && at the end) asks for more with "> ".
 *
 * Variables: `NAME=value` or `set NAME=value` (the shell's own), `export
 * NAME=value` (the environment, which every program started afterwards
 * gets: getenv), `unset`, `env`. $NAME, ${NAME} and $? (the last command's
 * status) expand in words and "...", not in '...'; so do ${#NAME} (its
 * length), ${NAME#pat} ${NAME##pat} ${NAME%pat} ${NAME%%pat} (NAME without
 * its shortest, or doubled longest, prefix or suffix that matches the
 * pattern: with the pattern "star, slash" the ## form gives the file name
 * of a path and the % form of "slash, star" its folder),
 * ${NAME:-word} (word when NAME is empty), ${NAME:=word} (and set
 * it), ${NAME:+word}, $$ (this shell's pid) and $! (the last program put in
 * the background). A plain command name is looked for in the folders of
 * $PATH (default /bin) in order. At start the shell sets PATH, HOME and PWD
 * if they are missing, and an interactive one runs /etc/profile, then
 * $HOME/.profile, when the disk has them.
 *
 * The language (a small POSIX sh; tynix/README.md has examples):
 *   a ; b      one after the other      a && b    b if a worked (status 0)
 *   a | b      a's output is b's input  a || b    b if a failed
 *   ! a        the opposite status      a &       in the background
 *   if LIST; then LIST; [elif LIST; then LIST;] [else LIST;] fi
 *   while LIST; do LIST; done     until LIST; do LIST; done
 *   for NAME in WORDS; do LIST; done   (no `in WORDS`: the arguments)
 *   case WORD in PATTERN|PATTERN) LIST ;; ... esac
 *   { LIST; }  a group      ( LIST )  in a new shell (its variables stay there)
 *   NAME() { LIST; }        a function: $1 $2 ... $# $@ are its arguments,
 *                           `local NAME=value` a variable of its own, `return N`
 *   break [N]  continue [N]  exit [N]  shift [N]
 *   $(LIST) or `LIST`       the output of LIST, its last newlines taken off
 *   $((1 + 2 * $n))         integer arithmetic (+ - * / % << >> & | ^ ! ~
 *                           comparisons, && ||, parentheses; names are variables)
 *   * ? [a-z] [!x]          file names that match, sorted (none: the word stays)
 *   ~                       $HOME at the start of a word
 *   test EXPR, [ EXPR ]     -e -f -d -s -z -n FILE/TEXT, = != < >, -eq -ne -lt
 *                           -le -gt -ge, ! -a -o ( ); true, false, :
 *   read [-r] NAME...       a line of stdin into variables (the last gets the rest)
 *   alias NAME='text'       NAME as a command becomes text (unalias, alias lists)
 *   eval WORDS, type NAME, echo -n
 * Redirections (< > >>) go after any command, also after `done`, `fi`, `}`.
 *
 * A pipe joins two programs that run at the same time: the kernel holds 256
 * words between them (pipe(), sys/tynix.h). A built-in, an alias, a
 * function or a compound command in a pipeline, or after `&`, runs in a new
 * shell (/bin/sh -S STATE -c TEXT) that gets the variables, the functions,
 * the aliases and the arguments of this one through a file in /tmp, so
 * `ls /bin | while read f; do echo "[$f]"; done` works, but what it sets
 * stays in that shell. $( ) runs in this shell, with its output going to a
 * file in /tmp that is then read back.
 *
 * Scripts: `sh FILE [ARG...]` runs a text file in a new shell, with $0 the
 * file and $1 ... the arguments, and ends with its status; so does a text
 * file named as a command (./backup.sh, or in a folder of $PATH) when its
 * first line is `#!/bin/sh` (#!PROGRAM [ARG]: that program, given the file).
 * `run FILE [ARG...]`, `source FILE` or `. FILE` runs it in this shell
 * instead (so its variables, functions and aliases stay: /etc/profile is run
 * so). A whole text is checked before any of it runs: a syntax error stops it
 * with "NAME: line N: ...". `sh -c TEXT [NAME ARG...]` runs that text, `sh <
 * FILE` the text of its stdin (stdin not the keyboard), without the banner
 * or a prompt. An endless loop typed at the prompt can't be stopped (Esc
 * goes to programs, and the shell is not one); in a script run with `sh
 * FILE` or `./FILE`, Esc kills that shell.
 *
 * Limits, each with a message: 256 chars a typed line, 64 words and 4
 * redirections a simple command (before * expands), 256 words after, 8
 * commands a pipeline, 64 K chars a script, 128 variables, 32 functions,
 * 32 aliases, 24 levels of functions, run, eval, aliases and $( ) inside each
 * other.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/statvfs.h>
#include <sys/stat.h>
#include <gfx.h>
#include <cpu.h>

#define LINE_MAX 256
#define MAX_ARGS 256            /* the words of a command, after * */
#define MAX_WORDS 64            /* the words of a simple command, as typed */
#define MAX_REDIRS 4
#define MAX_STAGES 8            /* the commands of a pipeline */
#define MAX_NEST 24             /* functions, run, eval, aliases, $( ) inside each other */
#define SCRIPT_MAX 65536        /* chars of a script */
#define WIDTH 64                /* the text display's columns (the circuit's TTY) */
#define MAX_JOBS 16
#define MAX_VARS 128
#define MAX_FUNCS 32
#define MAX_ALIASES 32
#define MAX_LOCALS 64

static char line[LINE_MAX];
static char path[2 * LINE_MAX];
static char cwd[512];
static FILE *out;               /* where a built-in writes: base_out, or its own > file */
static FILE *base_out;          /* where commands write now: stdout, or a > of a compound
                                   command, a function, run, $( ) */
static FILE *base_in;           /* where they read: 0 (the shell's stdin), or a < file */
static int last_status;         /* $?: the status of the last command */
static int last_bg;             /* $!: the last program started with & */
static char *var_entry(const char *name, int len, int *at);
static int good_name(const char *s, int len);
static char *vars[MAX_VARS];    /* the shell's own variables, "NAME=value" (set);
                                   exported ones are in environ instead (export) */
static struct job {             /* the programs this shell left running */
    int pid;
    char name[32];
} jobs[MAX_JOBS];

static struct func {            /* NAME() { ... }: the text of its body */
    char *name, *body;
    int busy;                   /* running: a new definition keeps the old body */
} funcs[MAX_FUNCS];

static struct alias {           /* alias NAME='text' */
    char *name, *value;
    int busy;                   /* being expanded: not again inside itself */
} aliases[MAX_ALIASES];

static char *arg0 = "sh";       /* $0 */
static char **pos;              /* $1 ... (malloc'd copies), pos_n of them: $# */
static int pos_n;

/* the state of the language (section "the language" below) */
enum { F_NONE, F_BREAK, F_CONTINUE, F_RETURN, F_EXIT };
static int flow, flow_n;        /* a break, continue, return or exit on its way out */
static int loops;               /* loops around the command running (of this function) */
static int funcs_depth;         /* functions running */
static int sourcing;            /* run/source files running (return ends them) */
static int nest;                /* functions, run, eval, aliases and $( ) inside each other */
static int interactive;         /* the shell reads the keyboard at a prompt */
static int typed;               /* the text running is the line typed (messages without line numbers) */
static int temp_n;              /* files made in /tmp */
static int no_fg;               /* sh -B: a shell in the background, whose programs are too */
#define FG (no_fg ? 0 : SPAWN_FG)
static int run_text(const char *text, const char *name);
static int run_file(const char *file, int argc, char **argv);
/* "cmd: what: No such file or directory"; returns the command's status, 1 */
static int fail(const char *cmd, const char *what)
{
    printf("%s: %s: %s\n", cmd, what, strerror(errno));
    return 1;
}

static int col;                 /* where a list of names has got to on its line */

/* one name of a list (and tail, "/" for a directory), two spaces apart,
   a new line (after indent spaces) when it would pass WIDTH */
static void item(const char *name, const char *tail, int indent)
{
    int n = strlen(name) + strlen(tail);
    if (col > indent && col + 2 + n > WIDTH) {
        fputc('\n', out);
        col = 0;
    }
    if (col == 0)
        col = fprintf(out, "%*s", indent, "");
    else
        col += fprintf(out, "  ");
    col += fprintf(out, "%s%s", name, tail);
}

static int is_dir(const char *p)
{
    DIR *d = opendir(p);
    if (d)
        closedir(d);
    return d != 0;
}

/* ---------------------------------------------------------------- built-ins
   Each gets argc/argv like main and returns its status; -1 means wrong
   arguments (the shell prints the usage). */

static int cmd_help(int argc, char **argv);
static int cmd_run(int argc, char **argv);

static int list(const char *dir, int sizes)
{
    DIR *d = opendir(dir);
    struct dirent *e;
    if (d == 0) {
        if (errno != ENOTDIR)
            return fail("ls", dir);
        fprintf(out, "%s\n", dir);      /* a file: just its name */
        return 0;
    }
    col = 0;
    while ((e = readdir(d))) {
        if (!sizes && (out != stdout || !isatty(1)))
            fprintf(out, "%s\n", e->d_name);   /* to a file or a pipe: a name a line */
        else if (!sizes)
            item(e->d_name, e->d_type == DT_DIR ? "/" : "", 0);
        else if (e->d_type == DT_DIR)
            fprintf(out, "   <dir>  %s/\n", e->d_name);
        else
            fprintf(out, "%8u  %s\n", e->d_size, e->d_name);
    }
    if (col > 0)
        fputc('\n', out);
    closedir(d);
    return 0;
}

static int cmd_ls(int argc, char **argv)
{
    int i = 1, sizes = 0, status = 0;
    if (argc > 1 && strcmp(argv[1], "-l") == 0) {
        sizes = 1;
        i++;
    }
    if (i == argc)
        return list(".", sizes);
    for (; i < argc; i++) {
        if (argc - (sizes + 1) > 1 && is_dir(argv[i]))
            fprintf(out, "%s:\n", argv[i]);
        status |= list(argv[i], sizes);
    }
    return status;
}

static int cmd_cd(int argc, char **argv)
{
    const char *to = argc > 1 ? argv[1] : "/";
    if (argc > 2)
        return -1;
    if (chdir(to))
        return fail("cd", to);
    setenv("PWD", getcwd(cwd, sizeof cwd), 1);
    return 0;
}


/* ------------------------------------------------------------- variables */

/* NAME=value: the length of NAME, or -1 (with a message) */
static int assignment(const char *cmd, const char *a)
{
    const char *eq = strchr(a, '=');
    int len = eq ? eq - a : (int)strlen(a);
    if (!good_name(a, len)) {
        printf("%s: %.*s: not a name (letters, digits, _)\n", cmd, len, a);
        return -1;
    }
    return len;
}

static void forget_var(const char *name, int len)
{
    int i;
    if (var_entry(name, len, &i)) {
        free(vars[i]);
        vars[i] = 0;
    }
}

/* NAME (len chars) = value: a shell variable, or the environment's when
   NAME is exported; 0, or 1 after a message */
static int assign(const char *name, int len, const char *value)
{
    char n[64], *e;
    int at;
    if (len >= (int)sizeof n) {
        printf("sh: %.*s: name too long\n", len, name);
        return 1;
    }
    strncpy(n, name, len);
    n[len] = 0;
    if (getenv(n)) {                    /* exported: stays in the environment */
        if (setenv(n, value, 1) == 0)
            return 0;
    } else if ((e = malloc(len + strlen(value) + 2)) != 0) {
        sprintf(e, "%s=%s", n, value);
        forget_var(name, len);
        for (at = 0; at < MAX_VARS && vars[at]; at++)
            ;
        if (at < MAX_VARS) {
            vars[at] = e;
            return 0;
        }
        free(e);
    }
    printf("sh: no room for %s\n", n);
    return 1;
}

/* $1 ...: copies of v[0..n) */
static void set_args(int n, char **v)
{
    int i;
    pos = n ? malloc(n * sizeof *pos) : 0;
    pos_n = pos || n == 0 ? n : 0;
    for (i = 0; i < pos_n; i++)
        pos[i] = strdup(v[i]);
}

static void free_args(void)
{
    int i;
    for (i = 0; i < pos_n; i++)
        free(pos[i]);
    free(pos);
    pos = 0;
    pos_n = 0;
}

/* set: the shell's own variables; set NAME=value...: set them (a name that
   is exported changes in the environment instead); set -- ARG...: $1 ... */
static int cmd_set(int argc, char **argv)
{
    int i, len, status = 0;
    if (argc == 1) {
        for (i = 0; i < MAX_VARS; i++)
            if (vars[i])
                fprintf(out, "%s\n", vars[i]);
        return 0;
    }
    if (strcmp(argv[1], "--") == 0) {
        free_args();
        set_args(argc - 2, argv + 2);
        return 0;
    }
    for (i = 1; i < argc; i++) {
        char *eq = strchr(argv[i], '=');
        if ((len = assignment("set", argv[i])) < 0 || !eq) {
            if (len >= 0)
                printf("set: %s: give it as NAME=value\n", argv[i]);
            status = 1;
            continue;
        }
        status |= assign(argv[i], len, eq + 1);
    }
    return status;
}

/* export: the environment; export NAME[=value]...: into it, so programs
   started from here on get them */
static int cmd_export(int argc, char **argv)
{
    int i, len, status = 0;
    char name[64], *v;
    if (argc == 1) {
        for (i = 0; environ[i]; i++)
            fprintf(out, "%s\n", environ[i]);
        return 0;
    }
    for (i = 1; i < argc; i++) {
        char *eq = strchr(argv[i], '=');
        if ((len = assignment("export", argv[i])) < 0 || len >= (int)sizeof name) {
            status = 1;
            continue;
        }
        strncpy(name, argv[i], len);
        name[len] = 0;
        if (eq)
            v = eq + 1;
        else if ((v = var_entry(name, len, 0)) != 0)
            v += len + 1;               /* a set variable moves to the environment */
        else
            continue;                   /* nothing by that name: nothing to export */
        if (setenv(name, v, 1)) {
            printf("export: no room for %s\n", name);
            status = 1;
        }
        forget_var(name, len);
    }
    return status;
}

static int cmd_env(int argc, char **argv)
{
    return argc == 1 ? cmd_export(argc, argv) : -1;
}

static int cmd_unset(int argc, char **argv)
{
    int i, len, status = 0;
    char name[64];
    if (argc == 1)
        return -1;
    for (i = 1; i < argc; i++) {
        if ((len = assignment("unset", argv[i])) < 0 || len >= (int)sizeof name || argv[i][len]) {
            status = 1;
            continue;
        }
        strcpy(name, argv[i]);
        forget_var(name, len);
        unsetenv(name);
    }
    return status;
}

/* local NAME[=value]...: until the function ends (its old value comes back) */
static struct {
    char *name, *old;           /* old: 0 when it was not set */
    int depth;
} locals[MAX_LOCALS];
static int n_locals;
static const char *lookup(const char *name, int len);

static int cmd_local(int argc, char **argv)
{
    int i, len, status = 0;
    const char *old;
    if (funcs_depth == 0) {
        printf("local: only in a function\n");
        return 1;
    }
    for (i = 1; i < argc; i++) {
        char *eq = strchr(argv[i], '=');
        if ((len = assignment("local", argv[i])) < 0) {
            status = 1;
            continue;
        }
        if (n_locals == MAX_LOCALS) {
            printf("local: more than %d\n", MAX_LOCALS);
            return 1;
        }
        old = lookup(argv[i], len);
        locals[n_locals].name = malloc(len + 1);
        strncpy(locals[n_locals].name, argv[i], len);
        locals[n_locals].name[len] = 0;
        locals[n_locals].old = old ? strdup(old) : 0;
        locals[n_locals++].depth = funcs_depth;
        status |= assign(argv[i], len, eq ? eq + 1 : "");
    }
    return status;
}

/* the function that ends gives its locals back */
static void drop_locals(void)
{
    while (n_locals > 0 && locals[n_locals - 1].depth == funcs_depth) {
        n_locals--;
        if (locals[n_locals].old) {
            assign(locals[n_locals].name, strlen(locals[n_locals].name), locals[n_locals].old);
            free(locals[n_locals].old);
        } else {
            forget_var(locals[n_locals].name, strlen(locals[n_locals].name));
            unsetenv(locals[n_locals].name);
        }
        free(locals[n_locals].name);
    }
}
static int cmd_pwd(int argc, char **argv)
{
    fprintf(out, "%s\n", getcwd(cwd, sizeof cwd));
    return 0;
}

static int cat(const char *name)
{
    FILE *f = fopen(name, "r");
    int c, last = '\n';
    if (f == 0)
        return fail("cat", name);
    while ((c = fgetc(f)) != EOF || !feof(f)) {
        if (c < 0 || c > 255) {         /* a word of a binary file, not a char */
            if (last != '\n')
                fputc('\n', out);
            printf("cat: %s: a binary file (a program?)\n", name);
            fclose(f);
            return 1;
        }
        fputc(c, out);
        last = c;
    }
    fclose(f);
    return 0;
}

static int cmd_cat(int argc, char **argv)
{
    int i, c, status = 0;
    if (argc == 1 && base_in) {         /* cat < file, or a < of a compound command */
        while ((c = fgetc(base_in)) != EOF)
            fputc(c, out);
        return 0;
    }
    if (argc == 1) {                    /* the keyboard (or a pipe), up to Ctrl-D */
        while ((c = getchar()) != EOF)
            fputc(c, out);
        clearerr(stdin);                /* the prompt reads the keyboard again */
        return 0;
    }
    for (i = 1; i < argc; i++)
        status |= cat(argv[i]);
    return status;
}

static int cmd_echo(int argc, char **argv)
{
    int i = 1, first = 1;
    if (argc > 1 && strcmp(argv[1], "-n") == 0)
        i++;                            /* -n: no newline at the end */
    for (; i < argc; i++, first = 0)
        fprintf(out, first ? "%s" : " %s", argv[i]);
    if (!(argc > 1 && strcmp(argv[1], "-n") == 0))
        fputc('\n', out);
    return 0;
}

static int cmd_rm(int argc, char **argv)
{
    int i, status = 0;
    if (argc < 2)
        return -1;
    for (i = 1; i < argc; i++)
        if (remove(argv[i]))
            status = fail("rm", argv[i]);
    return status;
}

static int cmd_mv(int argc, char **argv)
{
    const char *base;
    if (argc != 3)
        return -1;
    if (is_dir(argv[2])) {              /* into the directory, same name */
        base = strrchr(argv[1], '/');
        sprintf(path, "%s/%s", argv[2], base ? base + 1 : argv[1]);
    } else
        strcpy(path, argv[2]);
    return rename(argv[1], path) ? fail("mv", argv[1]) : 0;
}

/* a copy of a file, text or binary like the original (stat tells which) */
static int cmd_cp(int argc, char **argv)
{
    struct stat st, dst;
    FILE *from, *to;
    const char *base;
    int c, text;
    if (argc != 3)
        return -1;
    if (stat(argv[1], &st))
        return fail("cp", argv[1]);
    if (S_ISDIR(st.st_mode)) {
        printf("cp: %s: is a directory\n", argv[1]);
        return 1;
    }
    if (is_dir(argv[2])) {              /* into the directory, same name */
        base = strrchr(argv[1], '/');
        sprintf(path, "%s/%s", argv[2], base ? base + 1 : argv[1]);
    } else
        strcpy(path, argv[2]);
    if (st.st_ino && stat(path, &dst) == 0 && dst.st_ino == st.st_ino) {
        printf("cp: %s and %s are the same file\n", argv[1], path);
        return 1;                       /* "w" would free the blocks it is reading */
    }
    text = S_ISTEXT(st.st_mode);
    if ((from = fopen(argv[1], text ? "r" : "rb")) == 0)
        return fail("cp", argv[1]);
    if ((to = fopen(path, text ? "w" : "wb")) == 0) {
        fclose(from);
        return fail("cp", path);
    }
    while ((c = fgetc(from)) != EOF || !feof(from))
        fputc(c, to);                   /* a binary word of -1 reads as EOF: ferror tells */
    c = ferror(from) || ferror(to);
    fclose(from);
    fclose(to);
    if (c) {
        printf("cp: %s: write error\n", path);
        return 1;
    }
    return 0;
}

static int cmd_mkdir(int argc, char **argv)
{
    int i, status = 0;
    if (argc < 2)
        return -1;
    for (i = 1; i < argc; i++)
        if (mkdir(argv[i]))
            status = fail("mkdir", argv[i]);
    return status;
}

static int cmd_rmdir(int argc, char **argv)
{
    int i, status = 0;
    if (argc < 2)
        return -1;
    for (i = 1; i < argc; i++)
        if (rmdir(argv[i]))
            status = fail("rmdir", argv[i]);
    return status;
}

static int cmd_df(int argc, char **argv)
{
    struct statvfs s;
    unsigned used;
    if (statvfs("/", &s))
        return fail("df", "/");
    used = s.f_blocks - s.f_bfree;
    fprintf(out, "%u blocks of 1 KB (256 words): %u used, %u free (%u%% used)\n",
            s.f_blocks, used, s.f_bfree, (used * 100 + s.f_blocks - 1) / s.f_blocks);
    return 0;
}

static int cmd_clear(int argc, char **argv)
{
    putchar('\f');                      /* the text display */
    gfx_clear();                        /* and the RGB screen */
    return 0;
}

static int cmd_halt(int argc, char **argv)
{
    printf("CPU halted\n");
    halt_os();                          /* the kernel closes every file */
    return 0;
}

/* ---------------------------------------------------------------- jobs */

static struct job *job_of(int pid)
{
    int i;
    for (i = 0; i < MAX_JOBS; i++)
        if (jobs[i].pid == pid)
            return &jobs[i];
    return 0;
}

static void add_job(int pid, const char *name)
{
    struct job *j = job_of(0);
    if (j) {
        j->pid = pid;
        strncpy(j->name, name, sizeof j->name - 1);
        j->name[sizeof j->name - 1] = 0;
    }
    printf("[%d] %s &\n", pid, name);
}

/* how a program ended, when it is worth saying (130: killed, 139: past its
   stack, which the kernel has already said): kept until the end of the
   && || list, and said only if nothing tested it (if, while, &&, ||, !) */
static char report_name[32];
static int report_status, testing;

static void report(const char *name, int status)
{
    report_status = status;
    if (status) {
        strncpy(report_name, name, sizeof report_name - 1);
        report_name[sizeof report_name - 1] = 0;
    }
}

static void report_now(void)
{
    if (report_status && !testing)
        printf("[%s: exit status %d]\n", report_name, report_status);
    report_status = 0;
}

/* the background jobs that ended since the last prompt */
static void reap(void)
{
    int pid, status;
    struct job *j;
    while ((pid = waitpid(-1, &status, WAIT_NOHANG)) > 0)
        if ((j = job_of(pid))) {
            printf("[%d] done: %s, exit status %d\n", pid, j->name, status);
            j->pid = 0;
        }
}

/* wait for a program in front; one the NMI menu sends back becomes a job */
static int wait_for(int pid, const char *name)
{
    int status;
    struct job *j;
    if (waitpid(pid, &status, 0) < 0)
        return 1;
    if (status == SPAWN_BACKGROUND) {
        if (!job_of(pid))
            add_job(pid, name);
        else
            printf("[%d] %s &\n", pid, name);
        return 0;
    }
    if ((j = job_of(pid)))
        j->pid = 0;
    report(name, status);               /* said at the end of the && || list, unless tested */
    return status;
}

static int number(const char *s, int *n)
{
    char *end;
    *n = strtol(s, &end, 10);
    return *s && !*end;
}

static int cmd_jobs(int argc, char **argv)
{
    static const char *const states[] = {"", "running", "waiting", "ended"};
    struct task_info t[16];
    int n = tasks(t, 16), i;
    if (argc > 1)
        return -1;
    fprintf(out, "  pid  name          state    RAM\n");
    for (i = 0; i < n; i++)
        fprintf(out, "  %3d  %-12s  %-7s  %dK at 0x%x%s\n", t[i].pid, t[i].name,
                states[t[i].state], t[i].words / 1024, t[i].base, t[i].fg ? "  (front)" : "");
    return 0;
}

static int cmd_fg(int argc, char **argv)
{
    int pid;
    struct job *j;
    if (argc != 2 || !number(argv[1], &pid))
        return -1;
    if (set_foreground(pid))
        return fail(argv[0], argv[1]);
    j = job_of(pid);
    return wait_for(pid, j ? j->name : argv[1]);
}

static int cmd_kill(int argc, char **argv)
{
    int pid, i, status = 0;
    if (argc < 2)
        return -1;
    for (i = 1; i < argc; i++)
        if (!number(argv[i], &pid) || kill(pid, 0))
            status = fail(argv[0], argv[i]);
    return status;
}

static int cmd_wait(int argc, char **argv)
{
    int pid, status;
    struct job *j;
    if (argc > 2 || (argc == 2 && !number(argv[1], &pid)))
        return -1;
    if (argc == 1) {                    /* every job */
        while ((pid = waitpid(-1, &status, 0)) > 0)
            if ((j = job_of(pid))) {
                printf("[%d] done: %s, exit status %d\n", pid, j->name, status);
                j->pid = 0;
            }
        return 0;
    }
    if (waitpid(pid, &status, 0) < 0)
        return fail(argv[0], argv[1]);
    if ((j = job_of(pid)))
        j->pid = 0;
    return status;
}


/* ---------------------------------------------------------- script built-ins */

static int cmd_true(int argc, char **argv)
{
    return 0;
}

static int cmd_false(int argc, char **argv)
{
    return 1;
}

/* test EXPR: 0 true, 1 false, 2 a bad expression. A recursive parser over
   the words: or := and (-o and)*, and := not (-a not)*, not := ! not |
   ( or ) | -X word | word OP word | word */
static char **targ;
static int tn, ti, terr;

static int integer(const char *s, int *n)
{
    char *end;
    *n = strtol(s, &end, 0);
    if (*s && !*end)
        return 1;
    printf("test: %s: not a number\n", s);
    terr = 2;                           /* said */
    return 0;
}

static int binary_op(const char *op)
{
    static const char *const ops[] = {"=", "==", "!=", "<", ">", "-eq", "-ne", "-lt",
                                      "-le", "-gt", "-ge", 0};
    int i;
    for (i = 0; ops[i]; i++)
        if (strcmp(op, ops[i]) == 0)
            return 1;
    return 0;
}

static int t_or(void);

static int t_primary(void)
{
    const char *a, *op, *b;
    struct stat st;
    int x, y, r;
    if (ti >= tn) {
        terr = 1;
        return 0;
    }
    a = targ[ti];
    if (ti + 2 < tn && binary_op(targ[ti + 1])) {
        op = targ[ti + 1];
        b = targ[ti + 2];
        ti += 3;
        if (op[0] != '-') {
            r = strcmp(a, b);
            return op[0] == '=' ? r == 0 : op[0] == '!' ? r != 0 : op[0] == '<' ? r < 0 : r > 0;
        }
        if (!integer(a, &x) || !integer(b, &y))
            return 0;
        if (strcmp(op, "-eq") == 0)
            return x == y;
        if (strcmp(op, "-ne") == 0)
            return x != y;
        if (strcmp(op, "-lt") == 0)
            return x < y;
        if (strcmp(op, "-le") == 0)
            return x <= y;
        if (strcmp(op, "-gt") == 0)
            return x > y;
        return x >= y;
    }
    if (strcmp(a, "!") == 0) {
        ti++;
        return !t_primary();
    }
    if (strcmp(a, "(") == 0 && ti + 1 < tn) {
        ti++;
        r = t_or();
        if (ti < tn && strcmp(targ[ti], ")") == 0)
            ti++;
        else
            terr = 1;
        return r;
    }
    if (a[0] == '-' && a[1] && !a[2] && strchr("efdszrwxn", a[1]) && ti + 1 < tn) {
        b = targ[ti + 1];
        ti += 2;
        if (a[1] == 'z')
            return b[0] == 0;
        if (a[1] == 'n')
            return b[0] != 0;
        if (stat(b, &st))
            return 0;
        if (a[1] == 'f')
            return !S_ISDIR(st.st_mode);
        if (a[1] == 'd')
            return S_ISDIR(st.st_mode);
        if (a[1] == 's')
            return st.st_size > 0;
        return 1;                       /* -e -r -w -x: there (no permissions on the disk) */
    }
    ti++;
    return a[0] != 0;                   /* one word: not empty */
}

static int t_and(void)
{
    int r = t_primary();
    while (ti < tn && strcmp(targ[ti], "-a") == 0) {
        ti++;
        r = t_primary() && r;
    }
    return r;
}

static int t_or(void)
{
    int r = t_and();
    while (ti < tn && strcmp(targ[ti], "-o") == 0) {
        ti++;
        r = t_and() || r;
    }
    return r;
}

static int cmd_test(int argc, char **argv)
{
    int r;
    if (strcmp(argv[0], "[") == 0) {
        if (strcmp(argv[argc - 1], "]") != 0) {
            printf("[: no ] at the end\n");
            return 2;
        }
        argc--;
    }
    targ = argv + 1;
    tn = argc - 1;
    ti = terr = 0;
    if (tn == 0)
        return 1;
    r = t_or();
    if (terr || ti != tn) {
        if (terr != 2)
            printf("%s: a bad expression\n", argv[0]);
        return 2;
    }
    return !r;
}

/* read [-r] [NAME...]: a line of stdin (or of a < file) into the variables,
   split at spaces, the last one getting the rest (no NAME: REPLY); 1 at the
   end of the input. \ before a char keeps it, unless -r. */
static int cmd_read(int argc, char **argv)
{
    static char buf[LINE_MAX];
    static char *reply[] = {"REPLY"};
    char **names = argv + 1, *p, *w;
    FILE *f = base_in ? base_in : stdin;
    int n = argc - 1, raw = 0, i, len, got;
    if (n > 0 && strcmp(names[0], "-r") == 0) {
        raw = 1;
        names++;
        n--;
    }
    if (n == 0) {
        names = reply;
        n = 1;
    }
    for (i = 0; i < n; i++)
        if (!good_name(names[i], strlen(names[i]))) {
            printf("read: %s: not a name (letters, digits, _)\n", names[i]);
            return 2;
        }
    fflush(stdout);
    got = fgets(buf, sizeof buf, f) != 0;
    if (!got) {
        clearerr(f);                    /* the keyboard: the prompt reads it again */
        buf[0] = 0;
    }
    len = strlen(buf);
    if (len && buf[len - 1] == '\n')
        buf[--len] = 0;
    if (!raw) {                         /* \x is x */
        for (p = w = buf; *p; p++) {
            if (*p == '\\' && p[1])
                p++;
            *w++ = *p;
        }
        *w = 0;
    }
    p = buf;
    for (i = 0; i < n; i++) {
        while (*p == ' ' || *p == '\t')
            p++;
        w = p;
        if (i < n - 1) {
            while (*p && *p != ' ' && *p != '\t')
                p++;
            if (*p)
                *p++ = 0;
        } else {                        /* the rest, without its last spaces */
            len = strlen(w);
            while (len && (w[len - 1] == ' ' || w[len - 1] == '\t'))
                w[--len] = 0;
        }
        assign(names[i], strlen(names[i]), w);
    }
    return got ? 0 : 1;
}

static int cmd_shift(int argc, char **argv)
{
    int n = argc > 1 ? atoi(argv[1]) : 1, i;
    if (argc > 2 || n < 0)
        return -1;
    if (n > pos_n) {
        printf("shift: only %d arguments\n", pos_n);
        return 1;
    }
    for (i = 0; i < n; i++)
        free(pos[i]);
    memmove(pos, pos + n, (pos_n - n) * sizeof *pos);
    pos_n -= n;
    return 0;
}

/* break, continue, return, exit: what is running stops at its next step
   and the loop, function, file or shell they name takes over */
static int out_of(int kind, int argc, char **argv, int status)
{
    if (argc > 2 || (argc == 2 && argv[1][0] == 0))
        return -1;
    flow = kind;
    flow_n = argc == 2 ? atoi(argv[1]) : kind == F_BREAK || kind == F_CONTINUE ? 1 : status;
    if (flow_n < 1 && (kind == F_BREAK || kind == F_CONTINUE))
        flow_n = 1;
    return kind == F_BREAK || kind == F_CONTINUE ? 0 : flow_n;
}

static int cmd_break(int argc, char **argv)
{
    if (loops == 0) {
        printf("%s: only inside a loop\n", argv[0]);
        return 1;
    }
    return out_of(argv[0][0] == 'b' ? F_BREAK : F_CONTINUE, argc, argv, 0);
}

static int cmd_return(int argc, char **argv)
{
    if (funcs_depth == 0 && sourcing == 0) {
        printf("return: only in a function or a file run by run, source or .\n");
        return 1;
    }
    return out_of(F_RETURN, argc, argv, last_status);
}

static int cmd_exit(int argc, char **argv)
{
    return out_of(F_EXIT, argc, argv, last_status);
}

/* alias [NAME[=text]...]: define, show, or (none) list */
static struct alias *alias_of(const char *name, int len)
{
    int i;
    for (i = 0; i < MAX_ALIASES; i++)
        if (aliases[i].name && strncmp(aliases[i].name, name, len) == 0 && !aliases[i].name[len])
            return &aliases[i];
    return 0;
}

static void put_quoted(FILE *f, const char *s)
{
    fputc('\'', f);
    for (; *s; s++)
        if (*s == '\'')
            fputs("'\\''", f);
        else
            fputc(*s, f);
    fputc('\'', f);
}

static void show_alias(struct alias *a)
{
    fprintf(out, "alias %s=", a->name);
    put_quoted(out, a->value);
    fputc('\n', out);
}

static int cmd_alias(int argc, char **argv)
{
    int i, len, status = 0;
    struct alias *a;
    char *eq;
    if (argc == 1)
        for (i = 0; i < MAX_ALIASES; i++)
            if (aliases[i].name)
                show_alias(&aliases[i]);
    for (i = 1; i < argc; i++) {
        eq = strchr(argv[i], '=');
        len = eq ? eq - argv[i] : (int)strlen(argv[i]);
        if (len == 0 || strcspn(argv[i], " \t'\"\\$`;&|<>()/") < (size_t)len) {
            printf("alias: %.*s: not a name for an alias\n", len, argv[i]);
            status = 1;
        } else if (!eq) {
            if ((a = alias_of(argv[i], len)))
                show_alias(a);
            else {
                printf("alias: %s: not found\n", argv[i]);
                status = 1;
            }
        } else {
            if ((a = alias_of(argv[i], len)) == 0)
                for (a = aliases; a < aliases + MAX_ALIASES && a->name; a++)
                    ;
            if (a == aliases + MAX_ALIASES) {
                printf("alias: more than %d\n", MAX_ALIASES);
                return 1;
            }
            if (a->name == 0) {
                a->name = malloc(len + 1);
                strncpy(a->name, argv[i], len);
                a->name[len] = 0;
            } else if (!a->busy)
                free(a->value);
            a->value = strdup(eq + 1);
        }
    }
    return status;
}

static int cmd_unalias(int argc, char **argv)
{
    int i, status = 0;
    struct alias *a;
    if (argc == 1)
        return -1;
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-a") == 0) {
            for (a = aliases; a < aliases + MAX_ALIASES; a++)
                if (a->name && !a->busy) {
                    free(a->name);
                    free(a->value);
                    a->name = 0;
                }
        } else if ((a = alias_of(argv[i], strlen(argv[i]))) && !a->busy) {
            free(a->name);
            free(a->value);
            a->name = 0;
        } else {
            printf("unalias: %s: not found\n", argv[i]);
            status = 1;
        }
    }
    return status;
}

/* eval WORDS: the words joined with spaces, run as a text */
static int cmd_eval(int argc, char **argv)
{
    int i, len = 1, status;
    char *text;
    for (i = 1; i < argc; i++)
        len += strlen(argv[i]) + 1;
    if ((text = malloc(len)) == 0)
        return 1;
    text[0] = 0;
    for (i = 1; i < argc; i++) {
        strcat(text, argv[i]);
        if (i < argc - 1)
            strcat(text, " ");
    }
    if (nest >= MAX_NEST) {
        printf("eval: %d levels deep\n", MAX_NEST);
        status = 1;
    } else {
        nest++;
        status = run_text(text, "eval");
        nest--;
    }
    free(text);
    return status;
}

/* run FILE [ARG...], source, .: the file's text in this shell */
static int cmd_run(int argc, char **argv)
{
    if (argc < 2)
        return -1;
    return run_file(argv[1], argc - 2, argv + 2);
}

static int cmd_type(int argc, char **argv);

static const struct command {
    const char *name, *usage, *help;
    int (*run)(int argc, char **argv);
} commands[] = {
    {"help", "help", "these commands, the programs in /bin", cmd_help},
    {"ls", "ls [-l] [path...]", "list a directory (-l: sizes)", cmd_ls},
    {"cd", "cd [dir]", "go to a directory (none: /)", cmd_cd},
    {"pwd", "pwd", "show the current directory", cmd_pwd},
    {"cat", "cat [file...]", "show files (none: keys to Ctrl-D)", cmd_cat},
    {"echo", "echo [-n] [word...]", "show the words (-n: no newline)", cmd_echo},
    {"rm", "rm path...", "delete files, empty directories", cmd_rm},
    {"mv", "mv from to", "rename, or move into a directory", cmd_mv},
    {"cp", "cp from to", "copy a file, or into a directory", cmd_cp},
    {"mkdir", "mkdir dir...", "make directories", cmd_mkdir},
    {"rmdir", "rmdir dir...", "delete empty directories", cmd_rmdir},
    {"df", "df", "free space on the disk", cmd_df},
    {"clear", "clear", "clear the screens", cmd_clear},
    {"halt", "halt", "stop the CPU (Ctrl-D too)", cmd_halt},
    {"jobs", "jobs", "the programs running, their RAM", cmd_jobs},
    {"fg", "fg pid", "bring a program to the front, wait", cmd_fg},
    {"kill", "kill pid...", "end programs (status 130)", cmd_kill},
    {"wait", "wait [pid]", "wait for a program (none: all)", cmd_wait},
    {"run", "run file [arg...]", "run a script in this shell", cmd_run},
    {"source", "source file [arg...]", "the same as run", cmd_run},
    {".", ". file [arg...]", "the same as run", cmd_run},
    {"set", "set [NAME=value...]", "shell variables ($NAME), or list", cmd_set},
    {"export", "export [NAME[=v]...]", "into the environment, or list", cmd_export},
    {"env", "env", "list the environment", cmd_env},
    {"unset", "unset NAME...", "forget variables", cmd_unset},
    {"local", "local NAME[=v]...", "a function's own variables", cmd_local},
    {"alias", "alias [NAME[=text]]", "a name for a command line, or list", cmd_alias},
    {"unalias", "unalias NAME... | -a", "forget aliases", cmd_unalias},
    {"type", "type NAME...", "what a command name is", cmd_type},
    {"test", "test EXPR", "compare, check files (status 0/1)", cmd_test},
    {"[", "[ EXPR ]", "the same as test", cmd_test},
    {"true", "true", "status 0", cmd_true},
    {"false", "false", "status 1", cmd_false},
    {":", ":", "status 0", cmd_true},
    {"read", "read [-r] [NAME...]", "a line of input into variables", cmd_read},
    {"shift", "shift [n]", "drop the first arguments ($1 ...)", cmd_shift},
    {"break", "break [n]", "leave a loop (n loops)", cmd_break},
    {"continue", "continue [n]", "the next round of a loop", cmd_break},
    {"return", "return [status]", "leave a function or a run file", cmd_return},
    {"exit", "exit [status]", "end the shell or script", cmd_exit},
    {"eval", "eval word...", "run the words as a command line", cmd_eval},
};

#define N_COMMANDS (int)(sizeof commands / sizeof commands[0])

static int cmd_help(int argc, char **argv)
{
    DIR *d;
    struct dirent *e;
    int i;
    for (i = 0; i < N_COMMANDS; i++)
        fprintf(out, "  %-18s %s\n", commands[i].usage, commands[i].help);
    fprintf(out, "  %-18s %s\n", "command >[>] file", "its output to a file (>> adds)");
    fprintf(out, "  %-18s %s\n", "program < file", "its input from a file (cat < file too)");
    fprintf(out, "  %-18s %s\n", "a | b", "a's output into b (both run)");
    fprintf(out, "  %-18s %s\n", "a;b a&&b a||b", "after, if a worked, if not");
    fprintf(out, "  %-18s %s\n", "if while for case", "f() { }: see tynix/README.md");
    fprintf(out, "  %-18s %s\n", "$(c) $((1+2)) *.c", "output, arithmetic, file names");
    fprintf(out, "  %-18s %s\n", "sh file [arg...]", "a script in a new shell (or #!/bin/sh)");
    if ((d = opendir("/bin")) == 0) {
        fprintf(out, "no /bin: no programs\n");
        return 0;
    }
    fprintf(out, "programs in /bin (type the name):\n");
    col = 0;
    while ((e = readdir(d)))
        item(e->d_name, "", 2);
    if (col > 0)
        fputc('\n', out);
    closedir(d);
    return 0;
}

static int builtin_of(const char *name)
{
    int i;
    for (i = 0; i < N_COMMANDS; i++)
        if (strcmp(name, commands[i].name) == 0)
            return i;
    return -1;
}

static struct func *func_of(const char *name)
{
    int i;
    for (i = 0; i < MAX_FUNCS; i++)
        if (funcs[i].name && strcmp(funcs[i].name, name) == 0)
            return &funcs[i];
    return 0;
}

/* ---------------------------------------------------------------- programs */

/* a plain name: the first DIR/name, for the folders of $PATH in order
   (none set: /bin), that is a file, in path[]; when none is, the first
   folder's (whose load error the shell reports) */
static void find_program(const char *name)
{
    static char first[2 * LINE_MAX];
    const char *p = getenv("PATH"), *end;
    struct stat st;
    first[0] = 0;
    if (p == 0 || *p == 0)
        p = "/bin";
    for (;;) {
        int len;
        end = strchr(p, ':');
        if (end == 0)
            end = p + strlen(p);
        len = end - p;
        if (len > 0 && len + strlen(name) + 2 <= sizeof path) {
            strncpy(path, p, len);
            path[len] = '/';
            strcpy(path + len + 1, name);
            if (first[0] == 0)
                strcpy(first, path);
            if (stat(path, &st) == 0 && !S_ISDIR(st.st_mode))
                return;
        }
        if (*end == 0)
            break;
        p = end + 1;
    }
    if (first[0])
        strcpy(path, first);
    else
        sprintf(path, "/bin/%s", name);
}


/* the file after <, opened as what it is (a text file "r", a binary one
   "rb", as cp does), or 0 after an error message */
static FILE *open_input(const char *cmd, const char *name)
{
    struct stat st;
    int known = stat(name, &st) == 0;
    FILE *f;
    if (known && S_ISDIR(st.st_mode)) {
        printf("%s: %s: Is a directory\n", cmd, name);
        return 0;
    }
    f = fopen(name, known && !S_ISTEXT(st.st_mode) ? "rb" : "r");
    if (f == 0)
        fail(cmd, name);
    return f;
}

/* a text file that starts with #!PROGRAM [ARG]: argv for that program, given
   the file (path[] becomes PROGRAM; #! alone is /bin/sh); else argv */
static char **script_argv(char **argv)
{
    static char first[LINE_MAX], file[2 * LINE_MAX];
    static char *v[MAX_ARGS + 4];
    struct stat st;
    FILE *f;
    char *p, *arg;
    int i, n = 0;
    if (stat(path, &st) || S_ISDIR(st.st_mode) || !S_ISTEXT(st.st_mode) || (f = fopen(path, "r")) == 0)
        return argv;
    p = fgets(first, sizeof first, f);
    fclose(f);
    if (p == 0 || first[0] != '#' || first[1] != '!')
        return argv;                    /* the kernel says: Exec format error */
    p = first + 2;
    while (*p == ' ' || *p == '\t')
        p++;
    p[strcspn(p, "\r\n")] = 0;
    arg = p + strcspn(p, " \t");
    if (*arg) {
        *arg++ = 0;
        while (*arg == ' ' || *arg == '\t')
            arg++;
    }
    if (*p == 0)
        p = "/bin/sh";
    strcpy(file, path);
    v[n++] = p;
    if (*arg)
        v[n++] = arg;
    v[n++] = file;
    for (i = 1; argv[i] && n < MAX_ARGS + 3; i++)
        v[n++] = argv[i];
    v[n] = 0;
    strcpy(path, p);
    return v;
}

/* start argv[0] (a program, or a #! script) with that stdin (0: the shell's)
   and stdout; its pid, or -1 after a message */
static int start_program(char **argv, FILE *in, FILE *to, int flags)
{
    int pid;
    if (strlen(argv[0]) >= sizeof path / 2) {
        printf("%s: name too long\n", argv[0]);
        return -1;
    }
    if (strchr(argv[0], '/'))
        strcpy(path, argv[0]);
    else
        find_program(argv[0]);
    argv = script_argv(argv);
    fflush(stdout);                     /* what the shell wrote goes first: the */
    if (to != stdout)                   /* program writes to the same file itself */
        fflush(to);
    pid = spawn_io(path, argv, in, to != stdout ? to : 0, flags);
    if (pid < 0) {
        if (errno == ENOENT && !strchr(argv[0], '/'))
            printf("%s: no such command (help lists them)\n", argv[0]);
        else
            printf("%s: %s\n", path, strerror(errno));
    }
    return pid;
}

static int run_program(int argc, char **argv)
{
    int pid = start_program(argv, base_in, base_out, FG);
    return pid < 0 ? 127 : wait_for(pid, argv[0]);
}

/* type NAME...: an alias, a function, a built-in, or the program's path */
static int cmd_type(int argc, char **argv)
{
    struct alias *a;
    struct stat st;
    int i, status = 0;
    if (argc < 2)
        return -1;
    for (i = 1; i < argc; i++) {
        if ((a = alias_of(argv[i], strlen(argv[i]))))
            fprintf(out, "%s is an alias for %s\n", argv[i], a->value);
        else if (func_of(argv[i]))
            fprintf(out, "%s is a function\n", argv[i]);
        else if (builtin_of(argv[i]) >= 0)
            fprintf(out, "%s is a shell built-in\n", argv[i]);
        else {
            if (strchr(argv[i], '/'))
                strncpy(path, argv[i], sizeof path - 1);
            else
                find_program(argv[i]);
            if (stat(path, &st) == 0 && !S_ISDIR(st.st_mode))
                fprintf(out, "%s is %s\n", argv[i], path);
            else {
                printf("type: %s: not found\n", argv[i]);
                status = 1;
            }
        }
    }
    return status;
}

/* ------------------------------------------------------------- the language

   The shell runs text as it parses it, as the first shells did: there is
   no tree. P walks the text; every parse function also runs what it parsed,
   unless skip is set (then it only finds where the command ends). A loop
   goes back to the place its condition or body starts. Before a text runs
   at all it is parsed once with skip set, so a syntax error anywhere stops
   it before anything ran. A pipeline or a & is parsed once with skip to
   find its commands, then each is started. */

enum { T_END, T_NL, T_SEMI, T_DSEMI, T_AMP, T_AND, T_OR, T_PIPE, T_LP, T_RP,
       T_LT, T_GT, T_GTGT, T_WORD };

static const char *P;           /* where the parser is */
static const char *tok_end;     /* the end of the token peek() saw */
static const char *text_start;  /* the text running: for line numbers */
static const char *text_name;   /* its name in messages */
static int skip;                /* > 0: parse only */
static int error;               /* a syntax error: the text stops */
static int incomplete;          /* the text ended inside a command */
static int quiet;               /* no messages (checking whether a typed line is complete) */
static int parsed_cmds, parsed_compound;    /* what the last parse with skip saw */

struct stage {                  /* a command that runs on its own: in a pipeline, or & */
    FILE *in, *out;             /* its stdin (0: the shell's) and stdout */
    int flags;                  /* SPAWN_FG, or 0 */
    const char *start, *end;    /* its text, for a new shell */
    int pid, status;            /* what started (0: nothing, it ran here: status; -1: failed) */
    int helper;                 /* a new shell runs it: its status is not reported */
    char name[32];
};
static struct stage *stage;     /* the next command parsed runs so (then it is 0 again) */

static int active(void)
{
    return skip == 0 && flow == F_NONE && !error;
}

static char *copy(const char *s, const char *e)
{
    char *r = malloc(e - s + 1);
    if (r) {
        strncpy(r, s, e - s);
        r[e - s] = 0;
    }
    return r;
}

static int line_of(const char *at)
{
    const char *p;
    int n = 1;
    for (p = text_start; p < at && *p; p++)
        if (*p == '\n')
            n++;
    return n;
}

/* a syntax error at P (len chars of it shown) */
static void syntax(const char *what, int len)
{
    if (!error && !quiet) {
        if (!typed)
            printf("%s: line %d: ", text_name, line_of(P));
        if (len)
            printf("%s '%.*s'\n", what, len, P);
        else
            printf("%s\n", what);
    }
    error = 1;
}

/* the lexer: words are found by their ends; what they mean is worked out
   only when they run (expand) */

static int meta(int c)
{
    return c == 0 || c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == ';' || c == '&'
           || c == '|' || c == '(' || c == ')' || c == '<' || c == '>';
}

static const char *scan_dollar(const char *p);

/* after the quote that closes the one at p, or 0 (the text ended) */
static const char *scan_quote(const char *p)
{
    char q = *p++;
    while (*p && *p != q) {
        if (q != '\'' && *p == '\\' && p[1])
            p += 2;
        else if (q == '"' && *p == '$') {
            if ((p = scan_dollar(p)) == 0)
                return 0;
        } else
            p++;
    }
    if (*p == 0) {
        incomplete = 1;
        return 0;
    }
    return p + 1;
}

/* after the ) that matches the ( at p, or 0 */
static const char *scan_parens(const char *p)
{
    int depth = 0;
    for (;;) {
        if (*p == 0) {
            incomplete = 1;
            return 0;
        }
        if (*p == '\'' || *p == '"' || *p == '`') {
            if ((p = scan_quote(p)) == 0)
                return 0;
            continue;
        }
        if (*p == '\\' && p[1])
            p++;
        else if (*p == '(')
            depth++;
        else if (*p == ')' && --depth == 0)
            return p + 1;
        p++;
    }
}

/* after $(...), $((...)), ${...} at p; just after the $ otherwise (also
   for a ${ with no } on its line: a plain $) */
static const char *scan_dollar(const char *p)
{
    const char *dollar = p;
    if (p[1] == '(')
        return scan_parens(p + 1);
    if (p[1] != '{')
        return p + 1;
    for (p += 2; *p && *p != '}' && *p != '\n'; ) {
        if (*p == '\'' || *p == '"' || *p == '`')
            p = scan_quote(p);
        else if (*p == '$')
            p = scan_dollar(p);
        else
            p += *p == '\\' && p[1] ? 2 : 1;
        if (p == 0)
            return 0;
    }
    return *p == '}' ? p + 1 : dollar + 1;
}

static const char *scan_word(const char *p)
{
    while (!meta(*p)) {
        if (*p == '\\') {
            if (p[1] == 0) {
                incomplete = 1;
                return 0;
            }
            p += 2;
        } else if (*p == '\'' || *p == '"' || *p == '`') {
            if ((p = scan_quote(p)) == 0)
                return 0;
        } else if (*p == '$') {
            if ((p = scan_dollar(p)) == 0)
                return 0;
        } else
            p++;
    }
    return p;
}

/* spaces, \ newline and # comments */
static void blanks(void)
{
    for (;;) {
        if (*P == ' ' || *P == '\t' || *P == '\r')
            P++;
        else if (*P == '\\' && P[1] == '\n')
            P += 2;
        else if (*P == '#')
            while (*P && *P != '\n')
                P++;
        else
            return;
    }
}

/* the token at P (P moved past the blanks before it); tok_end its end */
static int peek(void)
{
    const char *p;
    blanks();
    p = P;
    tok_end = p + 1;
    switch (*p) {
    case 0: tok_end = p; return T_END;
    case '\n': return T_NL;
    case ';':
        if (p[1] != ';')
            return T_SEMI;
        tok_end = p + 2;
        return T_DSEMI;
    case '&':
        if (p[1] != '&')
            return T_AMP;
        tok_end = p + 2;
        return T_AND;
    case '|':
        if (p[1] != '|')
            return T_PIPE;
        tok_end = p + 2;
        return T_OR;
    case '(': return T_LP;
    case ')': return T_RP;
    case '>':
        if (p[1] != '>')
            return T_GT;
        tok_end = p + 2;
        return T_GTGT;
    case '<':
        if (p[1] != '<')
            return T_LT;
        tok_end = p + 2;                /* << is a word (calc 1 << 2) */
        return T_WORD;
    }
    if ((tok_end = scan_word(p)) == 0) {    /* a quote not closed */
        tok_end = p;
        error = 1;
        return T_END;
    }
    return T_WORD;
}

static void next(void)
{
    P = tok_end;
}

static int is_word(const char *w)
{
    int n = strlen(w);
    return peek() == T_WORD && tok_end - P == n && strncmp(P, w, n) == 0;
}

static void newlines(void)
{
    while (peek() == T_NL)
        next();
}

/* a token that is not what the grammar wants; at the end of the text it
   only means the text is not complete (more lines, at the prompt) */
static void unexpected(void)
{
    int t = peek();
    if (error)
        return;
    if (t == T_END) {
        incomplete = 1;
        error = 1;
    } else if (t == T_NL)
        syntax("unexpected newline", 0);
    else
        syntax("unexpected", tok_end - P);
}

static int expect(const char *w)
{
    if (is_word(w)) {
        next();
        return 1;
    }
    unexpected();
    return 0;
}

/* where a list ends: ) ;; the end, or a word that closes something */
static int at_end(void)
{
    static const char *const ends[] = {"then", "elif", "else", "fi", "do", "done", "esac", "}", 0};
    int t = peek(), i;
    if (t == T_END || t == T_RP || t == T_DSEMI)
        return 1;
    for (i = 0; t == T_WORD && ends[i]; i++)
        if (is_word(ends[i]))
            return 1;
    return 0;
}

static int compound_word(void)
{
    return is_word("if") || is_word("while") || is_word("until") || is_word("for")
           || is_word("case") || is_word("{");
}

/* ---------------------------------------------------------- expansion

   A word as typed becomes zero or more words to run: quotes come off,
   $NAME ${...} $( ) ` ` $(( )) and ~ are replaced, the values that were
   not quoted are split at spaces, and a word with an unquoted * ? [ becomes
   the file names it matches. */

#define X_SPLIT 1               /* split and match file names (a command's words) */
#define X_PATTERN 2             /* one string where quoted * ? [ \ keep a \ (case) */

struct fields {                 /* malloc'd words, v[n] = 0 */
    char **v;
    int n, cap;
};

struct exp {                    /* a word being made */
    struct fields *f;
    int mode;
    char *s, *g;                /* its chars; g: 1 where a char was not quoted */
    int len, cap, has;          /* has: there is a word (even "" ) */
};

static int exp_error;           /* a message was given: the command doesn't run */
static int subst_status;        /* the status of the last $( ), -1: none */

static void fields_add(struct fields *f, char *s)
{
    char **v;
    if (s == 0)
        return;
    if (f->n >= MAX_ARGS) {
        if (!exp_error)
            printf("sh: more than %d words\n", MAX_ARGS);
        exp_error = 1;
        free(s);
        return;
    }
    if (f->n + 2 > f->cap) {
        if ((v = realloc(f->v, (f->cap * 2 + 8) * sizeof *v)) == 0) {
            free(s);
            return;
        }
        f->v = v;
        f->cap = f->cap * 2 + 8;
    }
    f->v[f->n++] = s;
    f->v[f->n] = 0;
}

static void free_fields(struct fields *f)
{
    int i;
    for (i = 0; i < f->n; i++)
        free(f->v[i]);
    free(f->v);
    f->v = 0;
    f->n = f->cap = 0;
}

/* $NAME and ${NAME}: a shell variable (set), else one of the environment
   (export), else 0 */
static char *var_entry(const char *name, int len, int *at)
{
    int i;
    for (i = 0; i < MAX_VARS; i++)
        if (vars[i] && strncmp(vars[i], name, len) == 0 && vars[i][len] == '=') {
            if (at)
                *at = i;
            return vars[i];
        }
    return 0;
}

static const char *lookup(const char *name, int len)
{
    char *v = var_entry(name, len, 0), *e;
    int i;
    if (v)
        return v + len + 1;
    for (i = 0; environ && (e = environ[i]); i++)
        if (strncmp(e, name, len) == 0 && e[len] == '=')
            return e + len + 1;
    return 0;
}

static int name_char(int c, int first)
{
    return c == '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
           || (!first && c >= '0' && c <= '9');
}

/* a variable's name: letters, digits, _, not a digit first */
static int good_name(const char *s, int len)
{
    int i;
    if (len <= 0)
        return 0;
    for (i = 0; i < len; i++)
        if (!name_char(s[i], i == 0))
            return 0;
    return 1;
}

/* a parameter's value: $? $# $$ $! $0 $1 ... or a variable; 0 when unset */
static const char *param_value(const char *name, int len)
{
    static char num[16];
    int n = 0, i;
    if (len == 1 && strchr("?#$!", *name)) {
        if (*name == '!' && last_bg == 0)
            return 0;
        sprintf(num, "%d", *name == '?' ? last_status : *name == '#' ? pos_n
                           : *name == '$' ? getpid() : last_bg);
        return num;
    }
    if (*name >= '0' && *name <= '9') {
        for (i = 0; i < len; i++)
            n = n * 10 + name[i] - '0';
        return n == 0 ? arg0 : n <= pos_n ? pos[n - 1] : 0;
    }
    return lookup(name, len);
}

static void put(struct exp *x, int c, int glob)
{
    char *s, *g;
    if (x->len + 2 > x->cap) {
        s = realloc(x->s, x->cap * 2 + 32);
        if (s)
            x->s = s;
        g = realloc(x->g, x->cap * 2 + 32);
        if (g)
            x->g = g;
        if (s == 0 || g == 0) {
            if (!exp_error)
                printf("sh: out of memory\n");
            exp_error = 1;
            return;
        }
        x->cap = x->cap * 2 + 32;
    }
    x->s[x->len] = c;
    x->g[x->len++] = glob;
    x->s[x->len] = 0;
    x->has = 1;
}

static void lit(struct exp *x, int c, int quoted)
{
    if ((x->mode & X_PATTERN) && quoted && strchr("*?[\\", c))
        put(x, '\\', 0);
    put(x, c, !quoted);
}

static void glob_field(struct exp *x);

/* the end of a word (split mode): it goes into the fields, matched
   against the file names if it has an unquoted * ? [ */
static void field_end(struct exp *x)
{
    int i, globby = 0;
    if (!x->has)
        return;
    for (i = 0; i < x->len; i++)
        if (x->g[i] && strchr("*?[", x->s[i]))
            globby = 1;
    if (globby)
        glob_field(x);
    else
        fields_add(x->f, strdup(x->len ? x->s : ""));
    x->len = 0;
    x->has = 0;
}

/* a value into the word: split at spaces unless quoted */
static void value(struct exp *x, const char *v, int quoted)
{
    for (; v && *v; v++)
        if (!quoted && (x->mode & X_SPLIT) && (*v == ' ' || *v == '\t' || *v == '\n'))
            field_end(x);
        else
            lit(x, *v, quoted);
}

static void param(struct exp *x, const char *name, int len, int quoted)
{
    int i;
    if (len == 1 && (*name == '@' || *name == '*')) {
        if (*name == '@' && quoted && (x->mode & X_SPLIT)) {
            for (i = 0; i < pos_n; i++) {      /* "$@": a word for each */
                if (i) {
                    x->has = 1;
                    field_end(x);
                }
                value(x, pos[i], 1);
                x->has = 1;
            }
            return;
        }
        for (i = 0; i < pos_n; i++) {
            if (i)
                value(x, " ", quoted);
            value(x, pos[i], quoted);
        }
        return;
    }
    value(x, param_value(name, len), quoted);
}

static void expand(const char *s, const char *e, struct fields *f, int mode);

static char *expand_mode(const char *s, const char *e, int mode)
{
    struct fields f;
    char *r;
    memset(&f, 0, sizeof f);
    expand(s, e, &f, mode);
    r = f.n ? f.v[0] : 0;
    if (f.n)
        f.v[0] = 0;
    free_fields(&f);
    if (exp_error) {
        free(r);
        return 0;
    }
    return r;
}

/* one word, no splitting, no file names (NAME=value, > file, case WORD) */
static char *expand_one(const char *s, const char *e)
{
    return expand_mode(s, e, 0);
}

static void bad_subst(const char *s, const char *e)
{
    printf("sh: ${%.*s}: bad substitution\n", (int)(e - s), s);
    exp_error = 1;
}

static int gmatch(const char *p, const char *s);

/* ${NAME#pat} ${NAME##pat} ${NAME%pat} ${NAME%%pat}: v without its shortest
   (or, doubled, longest) prefix (#) or suffix (%) that matches the pattern */
static void trimmed(struct exp *x, const char *v, const char *pat, char op, int longest, int quoted)
{
    int len = strlen(v), i, cut = -1;
    if (op == '#') {
        char *t = strdup(v);
        for (i = longest ? len : 0; i >= 0 && i <= len && cut < 0; i += longest ? -1 : 1) {
            char c = t[i];
            t[i] = 0;
            if (gmatch(pat, t))
                cut = i;
            t[i] = c;
        }
        free(t);
        value(x, v + (cut > 0 ? cut : 0), quoted);
    } else {
        char *t;
        for (i = longest ? 0 : len; i >= 0 && i <= len && cut < 0; i += longest ? 1 : -1)
            if (gmatch(pat, v + i))
                cut = i;
        t = strdup(v);
        if (cut >= 0)
            t[cut] = 0;
        value(x, t, quoted);
        free(t);
    }
}

/* ${...} between s and e */
static void braced(struct exp *x, const char *s, const char *e, int quoted)
{
    const char *n = s, *v;
    char num[16], *word = 0;
    int colon = 0, len, empty;
    if (*s == '#' && e - s > 1) {       /* ${#NAME}: its length */
        v = param_value(s + 1, e - s - 1);
        sprintf(num, "%d", v ? (int)strlen(v) : 0);
        value(x, num, quoted);
        return;
    }
    if (n < e && strchr("?#@*$!", *n))
        n++;
    else if (n < e && *n >= '0' && *n <= '9')
        while (n < e && *n >= '0' && *n <= '9')
            n++;
    else
        while (n < e && name_char(*n, n == s))
            n++;
    len = n - s;
    if (len == 0) {
        bad_subst(s, e);
        return;
    }
    if (n == e) {
        param(x, s, len, quoted);
        return;
    }
    if (*n == '#' || *n == '%') {       /* ${NAME#pat} and the others: trim a prefix or a suffix */
        char op = *n++, *pat;
        int longest = n < e && *n == op;
        if (longest)
            n++;
        if ((pat = expand_one(n, e)) == 0)
            return;
        v = *s == '@' || *s == '*' ? 0 : param_value(s, len);
        trimmed(x, v ? v : "", pat, op, longest, quoted);
        free(pat);
        return;
    }
    if (*n == ':') {
        colon = 1;
        n++;
    }
    if (n == e || !strchr("-=+?", *n)) {
        bad_subst(s, e);
        return;
    }
    v = *s == '@' || *s == '*' ? (pos_n ? "1" : 0) : param_value(s, len);
    empty = v == 0 || (colon && *v == 0);
    if (*n == '+' ? !empty : empty) {
        if ((word = expand_one(n + 1, e)) == 0)
            return;
    }
    switch (*n) {
    case '-':                           /* the word if it is empty */
    case '+':                           /* the word if it is not */
        if (word)
            value(x, word, quoted);
        else if (*n == '-')
            param(x, s, len, quoted);
        break;
    case '=':                           /* the word, kept in it */
        if (word && !good_name(s, len))
            bad_subst(s, e);
        else if (word) {
            assign(s, len, word);
            value(x, word, quoted);
        } else
            param(x, s, len, quoted);
        break;
    case '?':                           /* a message and no command */
        if (word) {
            printf("sh: %.*s: %s\n", len, s, *word ? word : "not set");
            exp_error = 1;
        } else
            param(x, s, len, quoted);
        break;
    }
    free(word);
}

/* $( ): run text with its output to a file in /tmp, read it back; the
   last newlines taken off */
static char *temp_name(char *buf)
{
    mkdir("/tmp");
    sprintf(buf, "/tmp/.sh%d-%d", getpid(), ++temp_n);
    return buf;
}

static char *subst(const char *s, const char *e, int backquoted)
{
    char name[48], *text = copy(s, e), *res = 0, *r, *p, *w;
    FILE *f, *saved = base_out;
    int len = 0, cap = 0, c, status;
    if (text == 0)
        return strdup("");
    if (backquoted)                     /* `...`: \` \\ \$ are the char */
        for (p = w = text; (*w = *p); p++, w++)
            if (*p == '\\' && (p[1] == '`' || p[1] == '\\' || p[1] == '$'))
                *w = *++p;
    if (nest >= MAX_NEST || (f = fopen(temp_name(name), "w")) == 0) {
        if (nest >= MAX_NEST)
            printf("sh: $( ) %d levels deep\n", MAX_NEST);
        else
            fail("sh", name);
        exp_error = 1;
        free(text);
        return strdup("");
    }
    base_out = f;
    nest++;
    status = run_text(text, "$( )");
    nest--;
    base_out = saved;
    flow = F_NONE;                      /* exit, return, break end only the $( ) */
    fclose(f);
    free(text);
    subst_status = last_status = status;
    if ((f = fopen(name, "r")) != 0) {
        while ((c = fgetc(f)) != EOF) {
            if (len + 2 > cap) {
                if ((r = realloc(res, cap * 2 + 64)) == 0)
                    break;
                res = r;
                cap = cap * 2 + 64;
            }
            res[len++] = c;
        }
        fclose(f);
    }
    remove(name);
    while (len > 0 && res[len - 1] == '\n')
        len--;
    if (res == 0)
        return strdup("");
    res[len] = 0;
    return res;
}

/* $(( )): integers, C's operators and precedence (no assignments) */
static const char *ap;
static int aerr;

static void a_space(void)
{
    while (*ap == ' ' || *ap == '\t' || *ap == '\n')
        ap++;
}

static int a_binary(int min);

static int a_unary(void)
{
    const char *n, *v;
    char *end;
    int x;
    a_space();
    switch (*ap) {
    case '(':
        ap++;
        x = a_binary(1);
        a_space();
        if (*ap == ')')
            ap++;
        else
            aerr = 1;
        return x;
    case '-': ap++; return -a_unary();
    case '+': ap++; return a_unary();
    case '!': ap++; return !a_unary();
    case '~': ap++; return ~a_unary();
    }
    if (*ap >= '0' && *ap <= '9') {
        x = strtol(ap, &end, 0);
        ap = end;
        return x;
    }
    if (name_char(*ap, 1)) {            /* a variable: its number (none: 0) */
        for (n = ap; name_char(*ap, 0); ap++)
            ;
        v = lookup(n, ap - n);
        return v ? strtol(v, &end, 0) : 0;
    }
    aerr = 1;
    return 0;
}

static const char *const a_ops[] = {"||", "&&", "==", "!=", "<=", ">=", "<<", ">>",
                                    "|", "^", "&", "<", ">", "+", "-", "*", "/", "%", 0};
static const int a_prec[] = {1, 2, 6, 6, 7, 7, 8, 8, 3, 4, 5, 7, 7, 9, 9, 10, 10, 10};

static int a_binary(int min)
{
    int l = a_unary(), r, i;
    for (;;) {
        a_space();
        for (i = 0; a_ops[i]; i++)
            if (strncmp(ap, a_ops[i], strlen(a_ops[i])) == 0)
                break;
        if (a_ops[i] == 0 || a_prec[i] < min || aerr)
            return l;
        ap += strlen(a_ops[i]);
        r = a_binary(a_prec[i] + 1);
        switch (i) {
        case 0: l = l || r; break;
        case 1: l = l && r; break;
        case 2: l = l == r; break;
        case 3: l = l != r; break;
        case 4: l = l <= r; break;
        case 5: l = l >= r; break;
        case 6: l = l << r; break;
        case 7: l = l >> r; break;
        case 8: l = l | r; break;
        case 9: l = l ^ r; break;
        case 10: l = l & r; break;
        case 11: l = l < r; break;
        case 12: l = l > r; break;
        case 13: l = l + r; break;
        case 14: l = l - r; break;
        case 15: l = l * r; break;
        default:
            if (r == 0) {
                aerr = 2;
                return 0;
            }
            l = i == 16 ? l / r : l % r;
        }
    }
}

static int arith(const char *s, const char *e)
{
    char *text = expand_one(s, e);
    int x;
    if (text == 0)
        return 0;
    ap = text;
    aerr = 0;
    x = a_binary(1);
    a_space();
    if (*ap || aerr) {
        printf("sh: $((%s)): %s\n", text, aerr == 2 ? "division by zero" : "not an arithmetic expression");
        exp_error = 1;
        x = 0;
    }
    free(text);
    return x;
}

static const char *expand_dollar(struct exp *x, const char *s, const char *e, int quoted)
{
    const char *p = s + 1, *q;
    char *v, num[16];
    if (*s == '`') {
        for (q = p; q < e && *q != '`'; q++)
            if (*q == '\\' && q + 1 < e)
                q++;
        v = subst(p, q, 1);
        value(x, v, quoted);
        free(v);
        return q + 1;
    }
    if (p >= e) {
        lit(x, '$', quoted);
        return p;
    }
    if (*p == '(') {
        if ((q = scan_parens(p)) == 0 || q > e) {
            lit(x, '$', quoted);
            return p;
        }
        if (p[1] == '(' && q[-2] == ')') {     /* $(( )) */
            sprintf(num, "%d", arith(p + 2, q - 2));
            value(x, num, quoted);
        } else {
            v = subst(p + 1, q - 1, 0);
            value(x, v, quoted);
            free(v);
        }
        return q;
    }
    if (*p == '{') {
        if ((q = scan_dollar(s)) == 0 || q > e || q[-1] != '}') {
            lit(x, '$', quoted);
            return p;
        }
        braced(x, p + 1, q - 1, quoted);
        return q;
    }
    if (strchr("?#@*$!", *p) || (*p >= '0' && *p <= '9')) {
        param(x, p, 1, quoted);
        return p + 1;
    }
    if (name_char(*p, 1)) {
        for (q = p; q < e && name_char(*q, 0); q++)
            ;
        param(x, p, q - p, quoted);
        return q;
    }
    lit(x, '$', quoted);                /* a $ that names nothing stays a $ */
    return p;
}

static const char *expand_dquote(struct exp *x, const char *s, const char *e)
{
    if (!(strncmp(s, "$@\"", 3) == 0 && pos_n == 0))
        x->has = 1;                     /* "" is a word; "$@" with no arguments is none */
    while (s < e && *s != '"') {
        if (*s == '\\' && s + 1 < e && strchr("$`\"\\\n", s[1])) {
            if (s[1] != '\n')
                lit(x, s[1], 1);
            s += 2;
        } else if (*s == '$' || *s == '`')
            s = expand_dollar(x, s, e, 1);
        else
            lit(x, *s++, 1);
    }
    return s + 1;
}

/* the word s..e into f: X_SPLIT, X_PATTERN, or 0 (exactly one string) */
static void expand(const char *s, const char *e, struct fields *f, int mode)
{
    struct exp x;
    memset(&x, 0, sizeof x);
    x.f = f;
    x.mode = mode;
    if (s < e && *s == '~' && (s + 1 == e || s[1] == '/')) {
        value(&x, param_value("HOME", 4), 1);
        x.has = 1;
        s++;
    }
    while (s < e && !exp_error) {
        if (*s == '\\') {
            if (s + 1 < e && s[1] != '\n')
                lit(&x, s[1], 1);
            s += 2;
        } else if (*s == '\'') {
            x.has = 1;
            for (s++; s < e && *s != '\''; s++)
                lit(&x, *s, 1);
            s++;
        } else if (*s == '"')
            s = expand_dquote(&x, s + 1, e);
        else if (*s == '$' || *s == '`')
            s = expand_dollar(&x, s, e, 0);
        else
            lit(&x, *s++, 0);
    }
    if (mode & X_SPLIT)
        field_end(&x);
    else
        fields_add(f, strdup(x.len ? x.s : ""));
    free(x.s);
    free(x.g);
}

/* file names: * any chars, ? one, [abc] [a-z] [!x] one of (or not), \x x */
static int gmatch(const char *p, const char *s)
{
    while (*p) {
        if (*p == '*') {
            while (*p == '*')
                p++;
            if (*p == 0)
                return 1;
            for (; *s; s++)
                if (gmatch(p, s))
                    return 1;
            return 0;
        }
        if (*s == 0)
            return 0;
        if (*p == '[') {
            const char *q = p + 1;
            int neg = 0, ok = 0;
            char lo, hi;
            if (*q == '!' || *q == '^') {
                neg = 1;
                q++;
            }
            if (*q == ']') {            /* [] ...]: a ] first is a ] */
                ok = *s == ']';
                q++;
            }
            while (*q && *q != ']') {
                if (*q == '\\' && q[1])
                    q++;
                lo = hi = *q++;
                if (*q == '-' && q[1] && q[1] != ']') {
                    hi = q[1];
                    q += 2;
                }
                if (*s >= lo && *s <= hi)
                    ok = 1;
            }
            if (*q == 0) {              /* no ]: a plain [ */
                if (*s != '[')
                    return 0;
                p++;
                s++;
                continue;
            }
            if (ok == neg)
                return 0;
            p = q + 1;
            s++;
            continue;
        }
        if (*p == '\\' && p[1]) {
            if (*++p != *s)
                return 0;
        } else if (*p != '?' && *p != *s)
            return 0;
        p++;
        s++;
    }
    return *s == 0;
}

static int has_meta(const char *p, const char *e)
{
    for (; p < e; p++)
        if (*p == '\\' && p + 1 < e)
            p++;
        else if (*p == '*' || *p == '?' || *p == '[')
            return 1;
    return 0;
}

static char *join(const char *dir, const char *name)
{
    int d = strlen(dir);
    char *r = malloc(d + strlen(name) + 2);
    if (r) {
        strcpy(r, dir);
        if (d && dir[d - 1] != '/')
            r[d++] = '/';
        strcpy(r + d, name);
    }
    return r;
}

static int by_name(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

/* the paths dir/... that match pat, one / part at a time */
static void glob_walk(struct fields *out, const char *dir, const char *pat)
{
    const char *end = pat + strcspn(pat, "/"), *rest = *end ? end + 1 : 0, *p;
    struct fields names;
    struct dirent *ent;
    struct stat st;
    DIR *d;
    char *part, *w, *path_;
    int i;
    while (rest && *rest == '/')
        rest++;
    if ((part = malloc(end - pat + 1)) == 0)
        return;
    if (!has_meta(pat, end)) {          /* a plain part: it is there or not */
        for (p = pat, w = part; p < end; p++) {
            if (*p == '\\' && p + 1 < end)
                p++;
            *w++ = *p;
        }
        *w = 0;
        path_ = join(dir, part);
        free(part);
        if (path_ && stat(path_, &st) == 0 && (!rest || S_ISDIR(st.st_mode))) {
            if (rest && *rest) {
                glob_walk(out, path_, rest);
                free(path_);
            } else
                fields_add(out, path_);
        } else
            free(path_);
        return;
    }
    strncpy(part, pat, end - pat);
    part[end - pat] = 0;
    memset(&names, 0, sizeof names);
    if ((d = opendir(*dir ? dir : ".")) != 0) {
        while ((ent = readdir(d)) != 0)
            if (strcmp(ent->d_name, ".") && strcmp(ent->d_name, "..")
                    && (ent->d_name[0] != '.' || part[0] == '.')     /* .name only for .* */
                    && (!rest || ent->d_type == DT_DIR) && gmatch(part, ent->d_name))
                fields_add(&names, strdup(ent->d_name));
        closedir(d);
    }
    for (i = 0; i < names.n; i++) {
        path_ = join(dir, names.v[i]);
        if (path_ && rest && *rest) {
            glob_walk(out, path_, rest);
            free(path_);
        } else if (path_ && rest) {     /* pat ended with /: the folders, with it */
            fields_add(out, join(path_, ""));
            free(path_);
        } else
            fields_add(out, path_);
    }
    free_fields(&names);
    free(part);
}

static void glob_field(struct exp *x)
{
    char *pat = malloc(2 * x->len + 1), *w = pat;
    int i, n0 = x->f->n;
    if (pat == 0)
        return;
    for (i = 0; i < x->len; i++) {      /* quoted pattern chars get a \ */
        if (!x->g[i] && strchr("*?[\\", x->s[i]))
            *w++ = '\\';
        *w++ = x->s[i];
    }
    *w = 0;
    if (pat[0] == '/')
        glob_walk(x->f, "/", pat + 1);
    else
        glob_walk(x->f, "", pat);
    if (x->f->n == n0)
        fields_add(x->f, strdup(x->s)); /* no name matches: the word as it is */
    else
        qsort(x->f->v + n0, x->f->n - n0, sizeof(char *), by_name);
    free(pat);
}

/* ----------------------------------------------------------- running */

struct span {
    const char *s, *e;
};

struct redir {
    int type;                   /* T_LT, T_GT, T_GTGT */
    struct span w;
};

#define MAX_ASSIGNS 8

struct simple {                 /* a simple command as typed */
    int nw, na, nr;
    struct span w[MAX_WORDS], a[MAX_ASSIGNS];
    struct redir r[MAX_REDIRS];
};

struct saved_io {
    FILE *in, *out;
    FILE *opened[MAX_REDIRS];
    int n;
};

static void undo_redirs(struct saved_io *sv)
{
    base_in = sv->in;
    base_out = sv->out;
    while (sv->n > 0)
        fclose(sv->opened[--sv->n]);
}

/* < > >>: base_in and base_out are their files until undo_redirs; 0, or
   1 after a message */
static int do_redirs(struct redir *r, int nr, struct saved_io *sv, const char *cmd)
{
    char *name;
    FILE *f;
    int i;
    sv->in = base_in;
    sv->out = base_out;
    sv->n = 0;
    for (i = 0; i < nr; i++) {
        exp_error = 0;
        if ((name = expand_one(r[i].w.s, r[i].w.e)) == 0) {
            undo_redirs(sv);
            return 1;
        }
        if (r[i].type == T_LT)
            f = open_input(cmd, name);
        else if ((f = fopen(name, r[i].type == T_GTGT ? "a" : "w")) == 0)
            fail(cmd, name);
        free(name);
        if (f == 0) {
            undo_redirs(sv);
            return 1;
        }
        sv->opened[sv->n++] = f;
        if (r[i].type == T_LT)
            base_in = f;
        else
            base_out = f;
    }
    return 0;
}

/* what a new shell needs to be this one: the arguments, the variables, the
   aliases and the functions, as a script in /tmp (it deletes the file) */
static int write_state(char *name)
{
    FILE *f;
    char *eq;
    int i, bad;
    if ((f = fopen(temp_name(name), "w")) == 0) {
        fail("sh", name);
        return 0;
    }
    if (pos_n) {
        fputs("set --", f);
        for (i = 0; i < pos_n; i++) {
            fputc(' ', f);
            put_quoted(f, pos[i]);
        }
        fputc('\n', f);
    }
    for (i = 0; i < MAX_VARS; i++)
        if (vars[i]) {
            eq = strchr(vars[i], '=');
            fprintf(f, "%.*s=", (int)(eq - vars[i]), vars[i]);
            put_quoted(f, eq + 1);
            fputc('\n', f);
        }
    for (i = 0; i < MAX_ALIASES; i++)
        if (aliases[i].name) {
            fprintf(f, "alias %s=", aliases[i].name);
            put_quoted(f, aliases[i].value);
            fputc('\n', f);
        }
    for (i = 0; i < MAX_FUNCS; i++)
        if (funcs[i].name)
            fprintf(f, "%s() %s\n", funcs[i].name, funcs[i].body);
    bad = ferror(f);
    fclose(f);
    if (bad) {
        printf("sh: %s: write error\n", name);
        remove(name);
        return 0;
    }
    return 1;
}

/* /bin/sh [-B] -S STATE -c TEXT: the text start..end in a new shell; its pid,
   or -1 after a message */
static int spawn_sh(const char *start, const char *end, FILE *in, FILE *to, int flags)
{
    char state[48], *text = copy(start, end), *argv[7];
    int pid = -1, n = 0;
    if (text && write_state(state)) {
        argv[n++] = "sh";
        if (!(flags & SPAWN_FG))
            argv[n++] = "-B";           /* in the background: its programs too */
        argv[n++] = "-S";
        argv[n++] = state;
        argv[n++] = "-c";
        argv[n++] = text;
        argv[n] = 0;
        fflush(stdout);
        if (to != stdout)
            fflush(to);
        pid = spawn_io("/bin/sh", argv, in, to != stdout ? to : 0, flags);
        if (pid < 0) {
            printf("sh: /bin/sh: %s\n", strerror(errno));
            remove(state);
        }
    }
    free(text);
    return pid;
}

static int started(struct stage *s, int pid, const char *name)
{
    s->pid = pid;
    s->status = pid < 0 ? 127 : 0;
    strncpy(s->name, name, sizeof s->name - 1);
    s->name[sizeof s->name - 1] = 0;
    return s->status;
}

/* the stage's text in a new shell */
static int stage_sh(struct stage *s)
{
    s->helper = 1;
    return started(s, spawn_sh(s->start, s->end, s->in, s->out, s->flags), "sh");
}

static int run_builtin(int i, int argc, char **argv, int has_input)
{
    FILE *saved = out;
    int status;
    if (has_input && !(commands[i].run == cmd_cat && argc == 1) && commands[i].run != cmd_read) {
        printf("%s: < works for programs, a bare cat and read only\n", argv[0]);
        return 2;
    }
    out = base_out;
    status = commands[i].run(argc, argv);
    out = saved;
    if (status == -1) {
        printf("usage: %s\n", commands[i].usage);
        status = 2;
    }
    return status;
}

static int call_function(struct func *f, int argc, char **argv)
{
    char **saved_pos = pos;
    int saved_n = pos_n, saved_loops = loops, status;
    if (nest >= MAX_NEST) {
        printf("%s: functions %d levels deep\n", argv[0], MAX_NEST);
        return 1;
    }
    set_args(argc - 1, argv + 1);
    nest++;
    funcs_depth++;
    f->busy++;
    loops = 0;
    status = run_text(f->body, f->name);
    if (flow == F_RETURN) {
        flow = F_NONE;
        status = flow_n;
    }
    drop_locals();
    f->busy--;
    funcs_depth--;
    nest--;
    loops = saved_loops;
    free_args();
    pos = saved_pos;
    pos_n = saved_n;
    return status;
}

/* an alias: its text and the rest of the command (rest..end, as typed) */
static int run_alias(struct alias *a, const char *rest, const char *end)
{
    int n = strlen(a->value), status;
    char *text = malloc(n + (end - rest) + 2);
    if (text == 0)
        return 1;
    if (nest >= MAX_NEST) {
        printf("%s: aliases %d levels deep\n", a->name, MAX_NEST);
        free(text);
        return 1;
    }
    strcpy(text, a->value);
    text[n] = ' ';
    strncpy(text + n + 1, rest, end - rest);
    text[n + 1 + (end - rest)] = 0;
    a->busy++;
    nest++;
    status = run_text(text, a->name);
    nest--;
    a->busy--;
    free(text);
    return status;
}

static int plain(struct span w)
{
    const char *p;
    for (p = w.s; p < w.e; p++)
        if (strchr("'\"\\$`", *p))
            return 0;
    return 1;
}

/* NAME=value words: the temporary environment of a command (old: the
   values to put back, 0 for none), or the shell's variables (old == 0) */
static int assign_words(struct simple *c, char **old)
{
    const char *eq;
    char *v, name[64];
    int i, len, status = 0;
    for (i = 0; i < c->na; i++) {
        eq = strchr(c->a[i].s, '=');
        len = eq - c->a[i].s;
        if ((v = expand_one(eq + 1, c->a[i].e)) == 0)
            return 1;
        if (old == 0)
            status |= assign(c->a[i].s, len, v);
        else if (len < (int)sizeof name) {
            strncpy(name, c->a[i].s, len);
            name[len] = 0;
            old[i] = getenv(name) ? strdup(getenv(name)) : 0;
            setenv(name, v, 1);
        }
        free(v);
    }
    return status;
}

static void unassign_words(struct simple *c, char **old)
{
    char name[64];
    int i, len;
    for (i = 0; i < c->na; i++) {
        len = strchr(c->a[i].s, '=') - c->a[i].s;
        if (len >= (int)sizeof name)
            continue;
        strncpy(name, c->a[i].s, len);
        name[len] = 0;
        if (old[i])
            setenv(name, old[i], 1);
        else
            unsetenv(name);
        free(old[i]);
    }
}

static int exec_simple(struct simple *c, const char *end)
{
    struct stage *s = stage;
    struct fields f;
    struct saved_io sv;
    struct alias *a;
    struct func *fn = 0;
    char *old[MAX_ASSIGNS];
    FILE *si, *so;
    int i, b = -1, has_input = 0, status = 0;
    stage = 0;
    if (c->nw && plain(c->w[0]) && (a = alias_of(c->w[0].s, c->w[0].e - c->w[0].s)) && !a->busy)
        return s ? stage_sh(s) : run_alias(a, c->w[0].e, end);
    memset(&f, 0, sizeof f);
    exp_error = 0;
    subst_status = -1;
    for (i = 0; i < c->nw && !exp_error; i++)
        expand(c->w[i].s, c->w[i].e, &f, X_SPLIT);
    if (exp_error) {
        free_fields(&f);
        if (s) {
            started(s, 0, "sh");
            s->status = 1;
        }
        return 1;
    }
    if (f.n == 0) {                     /* NAME=value only (or nothing left) */
        status = assign_words(c, 0);
        if (!status && subst_status >= 0)
            status = subst_status;
        if (c->nr && do_redirs(c->r, c->nr, &sv, "sh") == 0)
            undo_redirs(&sv);           /* > file alone makes it empty */
        free_fields(&f);
        if (s) {
            started(s, 0, "sh");
            s->status = status;
        }
        return status;
    }
    if (!strchr(f.v[0], '/') && (fn = func_of(f.v[0])) == 0)
        b = builtin_of(f.v[0]);
    if (c->na && assign_words(c, old)) {
        free_fields(&f);
        return 1;
    }
    if (s && (fn || b >= 0))
        status = stage_sh(s);           /* a built-in or a function on its own: a new shell */
    else if (s) {
        si = base_in;
        so = base_out;
        base_in = s->in;
        base_out = s->out;
        if (c->nr && do_redirs(c->r, c->nr, &sv, f.v[0])) {
            started(s, -1, f.v[0]);
            status = s->status = 1;
        } else {
            status = started(s, start_program(f.v, base_in, base_out, s->flags), f.v[0]);
            if (c->nr)
                undo_redirs(&sv);
        }
        base_in = si;
        base_out = so;
    } else if (c->nr && do_redirs(c->r, c->nr, &sv, f.v[0]))
        status = 1;
    else {
        for (i = 0; i < c->nr; i++)
            if (c->r[i].type == T_LT)
                has_input = 1;
        if (fn)
            status = call_function(fn, f.n, f.v);
        else if (b >= 0)
            status = run_builtin(b, f.n, f.v, has_input);
        else
            status = run_program(f.n, f.v);
        if (c->nr)
            undo_redirs(&sv);
    }
    if (c->na)
        unassign_words(c, old);
    free_fields(&f);
    return status;
}

static int assignment_word(const char *s, const char *e)
{
    const char *p = s;
    while (p < e && name_char(*p, p == s))
        p++;
    return p > s && p < e && *p == '=';
}

/* words and redirections up to an operator */
static int run_simple(void)
{
    struct simple *c = malloc(sizeof *c);
    int t, status = 0;
    if (c == 0) {
        printf("sh: out of memory\n");
        error = 1;
        return 2;
    }
    c->nw = c->na = c->nr = 0;
    for (;;) {
        t = peek();
        if (t == T_WORD) {
            if (c->nw == 0 && c->na < MAX_ASSIGNS && assignment_word(P, tok_end)) {
                c->a[c->na].s = P;
                c->a[c->na++].e = tok_end;
            } else if (c->nw == MAX_WORDS) {
                syntax("more than 64 words in a command", 0);
                break;
            } else {
                c->w[c->nw].s = P;
                c->w[c->nw++].e = tok_end;
            }
            next();
        } else if (t == T_LT || t == T_GT || t == T_GTGT) {
            next();
            if (peek() != T_WORD) {
                syntax(t == T_LT ? "< needs a file name" : "> needs a file name", 0);
                break;
            }
            if (c->nr == MAX_REDIRS) {
                syntax("more than 4 redirections in a command", 0);
                break;
            }
            c->r[c->nr].type = t;
            c->r[c->nr].w.s = P;
            c->r[c->nr++].w.e = tok_end;
            next();
        } else
            break;
    }
    if (active())
        status = exec_simple(c, P);
    free(c);
    return status;
}

static int run_list(int top);
static int run_command(void);
static int run_pipeline(void);
static int run_compound_redir(void);

/* break and continue, at the end of a loop's round: 1 to leave the loop */
static int loop_flow(void)
{
    if (flow == F_BREAK) {
        if (--flow_n == 0)
            flow = F_NONE;
        return 1;
    }
    if (flow == F_CONTINUE) {
        if (--flow_n == 0)
            flow = F_NONE;
        else
            return 1;                   /* continue 2: the loop around this one */
    }
    return flow != F_NONE;
}

static int run_if(void)
{
    int done = 0, status = 0, c;
    next();
    for (;;) {
        if (active() && !done) {
            testing++;
            c = run_list(0);
            testing--;
        } else {
            skip++;
            run_list(0);
            skip--;
            c = 1;
        }
        if (!expect("then"))
            return 2;
        if (active() && !done && c == 0) {
            status = run_list(0);
            done = 1;
        } else {
            skip++;
            run_list(0);
            skip--;
        }
        if (!is_word("elif"))
            break;
        next();
    }
    if (is_word("else")) {
        next();
        if (active() && !done)
            status = run_list(0);
        else {
            skip++;
            run_list(0);
            skip--;
        }
    }
    expect("fi");
    return status;
}

static int run_while(int until)
{
    const char *cond;
    int status = 0, s = 0, c, go;
    next();
    cond = P;
    if (!active()) {
        run_list(0);
        if (expect("do")) {
            run_list(0);
            expect("done");
        }
        return 0;
    }
    loops++;
    for (;;) {
        P = cond;
        testing++;
        c = run_list(0);
        testing--;
        if (!expect("do"))
            break;
        go = active() && (c == 0) != until;
        if (go)
            s = run_list(0);
        else {
            skip++;
            run_list(0);
            skip--;
        }
        if (!expect("done"))
            break;
        if (go)
            status = s;
        if (loop_flow() || !go)
            break;
    }
    loops--;
    return status;
}

static int run_for(void)
{
    const char *name, *body;
    struct span *w = malloc(MAX_WORDS * sizeof *w);
    struct fields f;
    int nw = 0, i, status = 0, has_in = 0, t, len;
    next();
    if (w == 0)
        return 2;
    if (peek() != T_WORD || !good_name(P, tok_end - P)) {
        if (peek() == T_WORD)
            syntax("for needs a variable name, not", tok_end - P);
        else
            unexpected();
        free(w);
        return 2;
    }
    name = P;
    len = tok_end - P;
    next();
    newlines();
    if (is_word("in")) {
        has_in = 1;
        next();
        while (peek() == T_WORD) {
            if (nw == MAX_WORDS) {
                syntax("more than 64 words after in", 0);
                free(w);
                return 2;
            }
            w[nw].s = P;
            w[nw++].e = tok_end;
            next();
        }
        t = peek();
        if (t != T_SEMI && t != T_NL) {
            unexpected();
            free(w);
            return 2;
        }
        next();
    } else if (peek() == T_SEMI)
        next();
    newlines();
    if (!expect("do")) {
        free(w);
        return 2;
    }
    body = P;
    if (!active()) {
        run_list(0);
        expect("done");
        free(w);
        return 0;
    }
    memset(&f, 0, sizeof f);
    exp_error = 0;
    if (has_in)
        for (i = 0; i < nw && !exp_error; i++)
            expand(w[i].s, w[i].e, &f, X_SPLIT);
    else
        for (i = 0; i < pos_n; i++)     /* for NAME: the arguments, "$@" */
            fields_add(&f, strdup(pos[i]));
    free(w);
    if (exp_error) {
        free_fields(&f);
        status = 1;
    }
    loops++;
    if (f.n == 0) {
        skip++;
        run_list(0);
        skip--;
        expect("done");
    }
    for (i = 0; i < f.n; i++) {
        assign(name, len, f.v[i]);
        P = body;
        status = run_list(0);
        if (!expect("done") || loop_flow())
            break;
    }
    loops--;
    free_fields(&f);
    return status;
}

static int run_case(void)
{
    const char *ws, *we;
    char *word = 0, *pat;
    int status = 0, done = 0, hit;
    next();
    if (peek() != T_WORD) {
        unexpected();
        return 2;
    }
    ws = P;
    we = tok_end;
    next();
    newlines();
    if (!expect("in"))
        return 2;
    if (active()) {
        exp_error = 0;
        if ((word = expand_one(ws, we)) == 0)
            done = 1, status = 1;
    }
    for (;;) {
        newlines();
        if (is_word("esac"))
            break;
        if (peek() == T_LP)
            next();
        hit = 0;
        for (;;) {
            if (peek() != T_WORD) {
                unexpected();
                free(word);
                return 2;
            }
            if (word && !done && !hit && active()) {
                exp_error = 0;
                pat = expand_mode(P, tok_end, X_PATTERN);
                hit = pat && gmatch(pat, word);
                free(pat);
            }
            next();
            if (peek() != T_PIPE)
                break;
            next();
        }
        if (peek() != T_RP) {
            unexpected();
            free(word);
            return 2;
        }
        next();
        if (hit) {
            status = run_list(0);
            done = 1;
        } else {
            skip++;
            run_list(0);
            skip--;
        }
        if (peek() == T_DSEMI) {
            next();
            continue;
        }
        newlines();
        if (!is_word("esac")) {
            unexpected();
            free(word);
            return 2;
        }
    }
    next();
    free(word);
    return status;
}

/* ( LIST ): in a new shell */
static int run_subshell(void)
{
    const char *start;
    int pid;
    next();
    start = P;
    skip++;
    run_list(0);
    skip--;
    if (peek() != T_RP) {
        unexpected();
        return 2;
    }
    if (!active()) {
        next();
        return 0;
    }
    pid = spawn_sh(start, P, base_in, base_out, FG);
    next();
    if (pid < 0)
        return 127;
    pid = wait_for(pid, "sh");
    report_status = 0;                  /* ( ): as if it ran here */
    return pid;
}

static int run_compound(void)
{
    int status;
    if (peek() == T_LP)
        return run_subshell();
    if (is_word("if"))
        return run_if();
    if (is_word("while"))
        return run_while(0);
    if (is_word("until"))
        return run_while(1);
    if (is_word("for"))
        return run_for();
    if (is_word("case"))
        return run_case();
    next();                             /* { */
    status = run_list(0);
    expect("}");
    return status;
}

static int parse_redirs(struct redir *r)
{
    int n = 0, t;
    for (;;) {
        t = peek();
        if (t != T_LT && t != T_GT && t != T_GTGT)
            return n;
        next();
        if (peek() != T_WORD) {
            syntax(t == T_LT ? "< needs a file name" : "> needs a file name", 0);
            return n;
        }
        if (n == MAX_REDIRS) {
            syntax("more than 4 redirections", 0);
            return n;
        }
        r[n].type = t;
        r[n].w.s = P;
        r[n++].w.e = tok_end;
        next();
    }
}

/* a compound command and the redirections after it (found first, by a
   parse with skip, then the command runs with them) */
static int run_compound_redir(void)
{
    struct redir r[MAX_REDIRS];
    struct saved_io sv;
    struct stage *s = active() ? stage : 0;
    const char *start = P, *end;
    int n, status;
    if (s)
        stage = 0;
    parsed_compound++;
    skip++;
    run_compound();
    n = parse_redirs(r);
    skip--;
    if (!active())
        return 0;
    if (s)
        return stage_sh(s);
    end = P;
    if (n && do_redirs(r, n, &sv, "sh"))
        return 1;
    P = start;
    status = run_compound();
    P = end;
    if (n)
        undo_redirs(&sv);
    return status;
}

static int func_def(void)
{
    const char *p = tok_end;
    if (!good_name(P, tok_end - P))
        return 0;
    while (*p == ' ' || *p == '\t')
        p++;
    if (*p++ != '(')
        return 0;
    while (*p == ' ' || *p == '\t')
        p++;
    return *p == ')';
}

/* NAME() BODY: its text kept */
static int define_function(void)
{
    const char *name = P, *body;
    struct func *f;
    int len = tok_end - P, i;
    char *text;
    P = strchr(tok_end, ')') + 1;
    newlines();
    body = P;
    if (!(peek() == T_LP || (peek() == T_WORD && compound_word()))) {
        if (!error)
            syntax("a function's body is { ... }, not", peek() == T_WORD ? tok_end - P : 0);
        return 2;
    }
    skip++;
    run_compound_redir();
    skip--;
    if (!active())
        return 0;
    for (i = 0, f = 0; i < MAX_FUNCS && !f; i++)
        if (funcs[i].name && strncmp(funcs[i].name, name, len) == 0 && !funcs[i].name[len])
            f = &funcs[i];
    for (i = 0; i < MAX_FUNCS && !f; i++)
        if (funcs[i].name == 0)
            f = &funcs[i];
    if (f == 0 || (text = copy(body, P)) == 0) {
        printf("sh: more than %d functions\n", MAX_FUNCS);
        return 1;
    }
    if (f->name == 0) {
        f->name = copy(name, name + len);
        f->busy = 0;
    } else if (!f->busy)
        free(f->body);                  /* (running: the old text stays, unfreed) */
    f->body = text;
    return 0;
}

static int run_command(void)
{
    int t = peek();
    parsed_cmds++;
    if (t == T_LP || (t == T_WORD && compound_word()))
        return run_compound_redir();
    if (t == T_WORD && func_def()) {
        parsed_compound++;
        if (stage && active()) {        /* f() { } | x: defined here, nothing runs */
            started(stage, 0, "sh");
            stage = 0;
        }
        return define_function();
    }
    if (t == T_WORD || t == T_LT || t == T_GT || t == T_GTGT)
        return run_simple();
    unexpected();
    return 2;
}

/* a | b | c: every command started at once, joined by kernel pipes; the
   status is the last one's */
static int run_stages(const char **spans, int n)
{
    struct stage st[MAX_STAGES];
    FILE *in = base_in, *next_in, *w;
    int fds[2], i, status = 0;
    for (i = 0; i < n; i++) {
        w = next_in = 0;
        if (i < n - 1) {
            if (pipe(fds)) {
                fail("sh", "pipe");
                break;
            }
            next_in = fdopen(fds[0], "r");
            w = fdopen(fds[1], "w");
        }
        memset(&st[i], 0, sizeof st[i]);
        st[i].in = in;
        st[i].out = w ? w : base_out;
        st[i].flags = i == n - 1 ? FG : 0;
        st[i].start = spans[2 * i];
        st[i].end = spans[2 * i + 1];
        stage = &st[i];
        P = st[i].start;
        run_command();
        stage = 0;
        if (in != base_in)
            fclose(in);                 /* the programs hold their own ends */
        if (w)
            fclose(w);
        in = next_in;
    }
    if (in && in != base_in)
        fclose(in);
    if (i < n)                          /* no pipe: the ones started end alone */
        n = i;
    if (n == 0)
        return 1;
    status = st[n - 1].pid > 0 ? wait_for(st[n - 1].pid, st[n - 1].name) : st[n - 1].status;
    if (st[n - 1].helper)
        report_status = 0;              /* a built-in's or a loop's status: not a program's */
    for (i = 0; i < n - 1; i++)
        if (st[i].pid > 0) {
            if (st[n - 1].pid > 0 && job_of(st[n - 1].pid))
                add_job(st[i].pid, st[i].name);     /* the last one went to the background */
            else
                waitpid(st[i].pid, 0, 0);
        }
    return status;
}

static int run_pipeline(void)
{
    const char *spans[2 * MAX_STAGES], *start, *end;
    int bang = 0, n = 1, status;
    if (is_word("!")) {
        next();
        bang = 1;
    }
    start = P;
    if (!active()) {
        run_command();
        while (!error && peek() == T_PIPE) {
            next();
            newlines();
            run_command();
        }
        return 0;
    }
    skip++;
    run_command();
    skip--;
    if (error)
        return 2;
    if (peek() != T_PIPE) {
        P = start;
        status = run_command();
    } else {
        spans[0] = start;
        spans[1] = P;
        while (!error && peek() == T_PIPE) {
            next();
            newlines();
            if (n == MAX_STAGES) {
                syntax("more than 8 commands in a pipeline", 0);
                return 2;
            }
            spans[2 * n] = P;
            skip++;
            run_command();
            skip--;
            spans[2 * n++ + 1] = P;
        }
        if (error)
            return 2;
        end = P;
        status = run_stages(spans, n);
        P = end;
    }
    if (bang) {
        report_status = 0;
        status = !status;
    }
    return status;
}

/* a && b || c */
static int run_and_or(void)
{
    int status = run_pipeline(), t;
    for (;;) {
        t = peek();
        if (t != T_AND && t != T_OR)
            break;
        next();
        newlines();
        report_status = 0;              /* the left side was tested */
        if (active() && (t == T_AND) != (status == 0)) {
            skip++;
            run_pipeline();
            skip--;
        } else
            status = run_pipeline();
    }
    if (active())
        report_now();
    return status;
}

/* an && || list, in the background when & follows it: a program alone
   is started; anything else runs in a new shell */
static int run_bg_and_or(void)
{
    const char *start = P, *end;
    struct stage st;
    int status;
    if (!active()) {
        run_and_or();
        return 0;
    }
    parsed_cmds = parsed_compound = 0;
    skip++;
    run_and_or();
    skip--;
    if (error)
        return 2;
    if (peek() != T_AMP) {
        P = start;
        return last_status = run_and_or();
    }
    end = P;
    memset(&st, 0, sizeof st);
    st.in = base_in;
    st.out = base_out;
    st.start = start;
    st.end = end;
    if (parsed_cmds == 1 && parsed_compound == 0) {
        P = start;                      /* one simple command */
        stage = &st;
        run_and_or();
        stage = 0;
    } else
        stage_sh(&st);                  /* a | b &, a && b &, loops: one new shell for it all */
    P = end;
    if (st.pid > 0) {
        add_job(st.pid, st.name);
        last_bg = st.pid;
    }
    status = st.pid < 0 ? 127 : st.pid == 0 ? st.status : 0;
    return last_status = status;
}

static int run_list(int top)
{
    int status = 0, t;
    for (;;) {
        newlines();
        if (error || at_end())
            break;
        status = run_bg_and_or();
        if (error)
            break;
        t = peek();
        if (t == T_SEMI || t == T_NL || t == T_AMP)
            next();
        else if (!at_end()) {
            unexpected();
            break;
        }
    }
    if (top && !error && peek() != T_END)
        unexpected();
    return status;
}

/* ---------------------------------------------------------- texts */

/* a whole text: parsed once to find syntax errors, then run */
static int run_text(const char *text, const char *name)
{
    const char *saved_p = P, *saved_start = text_start, *saved_name = text_name;
    int saved_error = error, saved_incomplete = incomplete, saved_typed = typed, status;
    P = text_start = text;
    text_name = name;
    error = incomplete = 0;
    typed = typed && nest == 0;
    skip++;
    run_list(1);
    skip--;
    if (error) {
        if (incomplete && !quiet) {
            if (!typed)
                printf("%s: line %d: ", text_name, line_of(P));
            printf("the text ends inside a quote, ( ), { }, if, while, until, for or case\n");
        }
        status = 2;
    } else {
        P = text;
        status = run_list(1);
    }
    P = saved_p;
    text_start = saved_start;
    text_name = saved_name;
    error = saved_error;
    incomplete = saved_incomplete;
    typed = saved_typed;
    return status;
}

/* 0 when the text ends inside something (a typed line wants more lines) */
static int complete_text(const char *text)
{
    const char *saved_p = P, *saved_start = text_start;
    int saved_error = error, saved_incomplete = incomplete, more;
    P = text_start = text;
    error = incomplete = 0;
    quiet++;
    skip++;
    run_list(1);
    skip--;
    quiet--;
    more = incomplete;
    P = saved_p;
    text_start = saved_start;
    error = saved_error;
    incomplete = saved_incomplete;
    return !more;
}

/* a text file's chars (malloc'd), or 0 after a message */
static char *read_text(const char *file, const char *cmd)
{
    struct stat st;
    FILE *f;
    char *t, *bigger;
    int len = 0, cap = 1024, c;
    if (stat(file, &st) == 0 && S_ISDIR(st.st_mode)) {
        printf("%s: %s: Is a directory\n", cmd, file);
        return 0;
    }
    if ((f = fopen(file, "r")) == 0) {
        fail(cmd, file);
        return 0;
    }
    t = malloc(cap);
    while (t && (c = fgetc(f)) != EOF) {
        if (c < 0 || c > 255) {
            printf("%s: %s: a binary file (a program?)\n", cmd, file);
            free(t);
            t = 0;
        } else if (len + 2 > cap) {
            bigger = cap < SCRIPT_MAX ? realloc(t, cap * 2) : 0;
            if (bigger == 0)
                printf("%s: %s: longer than %d chars\n", cmd, file, SCRIPT_MAX);
            else
                cap *= 2;
            if (bigger == 0)
                free(t);
            t = bigger;
        }
        if (t)
            t[len++] = c;
    }
    fclose(f);
    if (t)
        t[len] = 0;
    return t;
}

/* run FILE [ARG...]: a script in this shell */
static int run_file(const char *file, int argc, char **argv)
{
    char **saved_pos = pos, *text, *name;
    int saved_n = pos_n, status;
    if (nest >= MAX_NEST) {
        printf("run: %s: %d levels deep\n", file, MAX_NEST);
        return 1;
    }
    if ((text = read_text(file, "run")) == 0)
        return 1;
    name = strdup(file);
    if (argc)
        set_args(argc, argv);
    nest++;
    sourcing++;
    status = run_text(text, name);
    if (flow == F_RETURN) {
        flow = F_NONE;
        status = flow_n;
    }
    sourcing--;
    nest--;
    if (argc) {
        free_args();
        pos = saved_pos;
        pos_n = saved_n;
    }
    free(text);
    free(name);
    return status;
}

/* stdin to its end (sh < FILE, or a pipe) */
static char *read_stdin(void)
{
    char *t = malloc(1024), *bigger;
    int len = 0, cap = 1024, c;
    while (t && (c = getchar()) != EOF) {
        if (len + 2 > cap) {
            bigger = cap < SCRIPT_MAX ? realloc(t, cap * 2) : 0;
            if (bigger == 0) {
                printf("sh: the input is longer than %d chars\n", SCRIPT_MAX);
                free(t);
                return 0;
            }
            t = bigger;
            cap *= 2;
        }
        t[len++] = c;
    }
    if (t)
        t[len] = 0;
    return t;
}

/* the status a shell ends with (exit N gives N) */
static int end_status(int status)
{
    reap();
    return flow == F_EXIT ? flow_n : status;
}
/* ------------------------------------------------------- typing a line */

/* At the prompt the shell reads the keys itself (wait_key, no echo) and
   shows them, so it can offer the last lines (Up, Down) and complete names
   (Tab). The text display has no cursor addressing, only backspace: the
   cursor stays at the end of the line, and showing another line means a
   backspace for each char shown, then the new text. Measured in the
   simulator's display (devices.py, 2026-11-03): a backspace at column 0
   does nothing (it never goes back to the line above), and a line never
   wraps, however long, so the backspaces always reach the prompt. The
   circuit's TTY wraps at 64 columns, and what its backspace does at the
   start of a wrapped row is not measured; Tynix runs only in the simulator.
   Left and Right are ignored: there is no moving inside the line. */

#define HISTORY 32
static char history[HISTORY][LINE_MAX];
static int history_n;           /* lines kept (at most HISTORY), the newest last */

static void remember(const char *s)
{
    int len = strlen(s);
    if (len && s[len - 1] == '\n')
        len--;
    if (len == 0 || (history_n && strncmp(history[history_n - 1], s, len) == 0
                     && history[history_n - 1][len] == 0))
        return;                         /* blank, or the same as the last one */
    if (history_n == HISTORY) {
        memmove(history[0], history[1], (HISTORY - 1) * LINE_MAX);
        history_n--;
    }
    strncpy(history[history_n], s, len);
    history[history_n++][len] = 0;
}

static void erase(int n)
{
    while (n-- > 0)
        putchar('\b');
}

/* show s in place of the n chars shown; its length */
static int replace(char *buf, int n, const char *s)
{
    erase(n);
    strcpy(buf, s);
    fputs(buf, stdout);
    return strlen(buf);
}

/* the names a word could become: matches[] (NUL-separated in names[]) */
#define MAX_MATCHES 64
static char names[4096];
static char *matches[MAX_MATCHES];
static int n_matches, names_len, match_dir[MAX_MATCHES];

static void add_match(const char *name, int is_dir)
{
    int i, len = strlen(name) + 1;
    for (i = 0; i < n_matches; i++)
        if (strcmp(matches[i], name) == 0)
            return;                     /* a built-in also in /bin */
    if (n_matches == MAX_MATCHES || names_len + len > (int)sizeof names)
        return;
    matches[n_matches] = names + names_len;
    match_dir[n_matches++] = is_dir;
    strcpy(names + names_len, name);
    names_len += len;
}

/* the entries of dir starting with prefix (only programs: not folders) */
static void match_dir_entries(const char *dir, const char *prefix, int programs)
{
    DIR *d = opendir(*dir ? dir : ".");
    struct dirent *e;
    int len = strlen(prefix);
    if (d == 0)
        return;
    while ((e = readdir(d)))
        if (strncmp(e->d_name, prefix, len) == 0 && !(programs && e->d_type == DT_DIR)
                && strcmp(e->d_name, ".") && strcmp(e->d_name, ".."))
            add_match(e->d_name, e->d_type == DT_DIR);
    closedir(d);
}

/* Tab: the last word of buf[0..n) completed as far as it is sure; when it
   can't add anything and there are several names, they are listed and the
   prompt and line shown again. The new length. */
static int complete(char *buf, int n, const char *prompt)
{
    static char dir[LINE_MAX];
    char *word = buf + n, *slash;
    const char *prefix, *p, *end;
    int first, i, common, len;
    while (word > buf && word[-1] != ' ')
        word--;
    first = word == buf || strspn(buf, " ") == (unsigned)(word - buf);
    n_matches = names_len = 0;
    slash = memchr(word, '/', buf + n - word) ? strrchr(word, '/') : 0;
    if (first && slash == 0) {          /* a command: built-ins, aliases, functions, $PATH's programs */
        buf[n] = 0;
        for (i = 0; i < N_COMMANDS; i++)
            if (strncmp(commands[i].name, word, strlen(word)) == 0)
                add_match(commands[i].name, 0);
        for (i = 0; i < MAX_ALIASES; i++)
            if (aliases[i].name && strncmp(aliases[i].name, word, strlen(word)) == 0)
                add_match(aliases[i].name, 0);
        for (i = 0; i < MAX_FUNCS; i++)
            if (funcs[i].name && strncmp(funcs[i].name, word, strlen(word)) == 0)
                add_match(funcs[i].name, 0);
        p = getenv("PATH");
        for (p = p && *p ? p : "/bin"; ; p = end + 1) {
            end = strchr(p, ':');
            if (end == 0)
                end = p + strlen(p);
            if (end > p && end - p < (int)sizeof dir) {
                strncpy(dir, p, end - p);
                dir[end - p] = 0;
                match_dir_entries(dir, word, 1);
            }
            if (*end == 0)
                break;
        }
        prefix = word;
    } else {                            /* a path: the entries of its folder */
        buf[n] = 0;
        if (slash) {
            len = slash - word;
            strncpy(dir, word, len);
            dir[len] = 0;
            if (len == 0)
                strcpy(dir, "/");
            prefix = slash + 1;
        } else {
            dir[0] = 0;
            prefix = word;
        }
        match_dir_entries(dir, prefix, 0);
    }
    if (n_matches == 0)
        return n;
    len = strlen(prefix);
    common = strlen(matches[0]);
    for (i = 1; i < n_matches; i++) {
        int k = 0;
        while (k < common && matches[i][k] == matches[0][k])
            k++;
        common = k;
    }
    if (common > len || n_matches == 1) {
        int add = common - len;
        if (n + add + 1 >= LINE_MAX - 1)
            return n;
        memcpy(buf + n, matches[0] + len, add);
        n += add;
        if (n_matches == 1)
            buf[n++] = match_dir[0] ? '/' : ' ';
        buf[n] = 0;
        fputs(buf + n - add - (n_matches == 1), stdout);
        return n;
    }
    putchar('\n');                      /* several, and nothing to add: list them */
    out = stdout;
    col = 0;
    for (i = 0; i < n_matches; i++)
        item(matches[i], match_dir[i] ? "/" : "", 0);
    if (col > 0)
        putchar('\n');
    printf("%s%s", prompt, buf);
    return n;
}

/* a line typed at the prompt, in line[] with its '\n'; 0 at Ctrl-D on an
   empty line */
static int type_line(const char *prompt)
{
    static char typed[LINE_MAX];    /* what was being typed before Up */
    int n = 0, at = history_n, c;
    line[0] = 0;
    for (;;) {
        c = wait_key();
        if (c == KEY_CTRL('d') && n == 0)
            return 0;
        if (c == '\n' || c == '\r') {
            putchar('\n');
            line[n++] = '\n';
            line[n] = 0;
            remember(line);
            return 1;
        }
        if (c == '\b' || c == 127) {
            if (n > 0) {
                line[--n] = 0;
                erase(1);
            }
        } else if (c == KEY_UP) {
            if (at > 0) {
                if (at == history_n)
                    strcpy(typed, line);
                n = replace(line, n, history[--at]);
            }
        } else if (c == KEY_DOWN) {
            if (at < history_n)
                n = replace(line, n, ++at == history_n ? typed : history[at]);
        } else if (c == '\t') {
            n = complete(line, n, prompt);
        } else if (c >= ' ' && c < 127 && n < LINE_MAX - 2) {
            line[n++] = c;
            line[n] = 0;
            putchar(c);
        }
    }
}


int main(int argc, char **argv)
{
    struct stat st;
    char *text;
    int i = 1, status = 0;
    base_out = stdout;
    /* the environment this shell and its programs start with, unless the
       parent's already says (sh -c from claude, sh from sh) */
    setenv("PATH", "/bin", 0);
    setenv("HOME", is_dir("/home/user") ? "/home/user" : "/", 0);
    setenv("PWD", getcwd(cwd, sizeof cwd), 1);
    if (argc > i && strcmp(argv[i], "-B") == 0) {
        no_fg = 1;                      /* started in the background */
        i++;
    }
    if (argc > i + 1 && strcmp(argv[i], "-S") == 0) {  /* the state of the shell that started this one */
        if ((text = read_text(argv[i + 1], "sh")) != 0) {
            nest++;
            run_text(text, "sh -S");
            nest--;
            free(text);
        }
        remove(argv[i + 1]);
        i += 2;
    }
    if (argc > i && strcmp(argv[i], "-c") == 0) {     /* sh -c TEXT [NAME ARG...] */
        if (argc == i + 1) {
            printf("usage: sh -c 'command line' [name arg...]\n");
            return 2;
        }
        if (argc > i + 2) {
            arg0 = argv[i + 2];
            free_args();
            set_args(argc - i - 3, argv + i + 3);
        }
        return end_status(run_text(argv[i + 1], arg0));
    }
    if (argc > i) {                     /* sh FILE [ARG...]: a script */
        if ((text = read_text(argv[i], "sh")) == 0)
            return 127;
        arg0 = argv[i];
        free_args();
        set_args(argc - i - 1, argv + i + 1);
        return end_status(run_text(text, arg0));
    }
    if (!isatty(0)) {                   /* sh < FILE: its text, then the end */
        if ((text = read_stdin()) == 0)
            return 2;
        return end_status(run_text(text, "sh"));
    }
    interactive = 1;
    printf("Tynix shell: help lists the commands\n");
    out = stdout;
    if (stat("/etc/profile", &st) == 0 && !S_ISDIR(st.st_mode))
        last_status = run_file("/etc/profile", 0, 0);   /* the settings kept on the disk */
    if (strlen(getenv("HOME")) + 10 < sizeof path) {
        sprintf(path, "%s/.profile", getenv("HOME"));
        if (stat(path, &st) == 0 && !S_ISDIR(st.st_mode)) {
            text = strdup(path);
            last_status = run_file(text, 0, 0);
            free(text);
        }
    }
    flow = F_NONE;
    for (;;) {
        static char prompt[sizeof cwd + 2];
        char *more;
        reap();
        sprintf(prompt, "%s> ", getcwd(cwd, sizeof cwd));
        fputs(prompt, stdout);
        if (!type_line(prompt))
            break;                      /* Ctrl-D */
        text = strdup(line);
        while (text && !complete_text(text)) {   /* an open quote, if, |: more lines */
            fputs("> ", stdout);
            if (!type_line("> ")) {
                free(text);
                text = 0;
                putchar('\n');
            } else if ((more = realloc(text, strlen(text) + strlen(line) + 1)) != 0) {
                text = more;
                strcat(text, line);
            }
        }
        if (text == 0)
            continue;
        typed = 1;
        status = run_text(text, "sh");
        typed = 0;
        free(text);
        if (flow == F_EXIT) {
            status = flow_n;
            break;
        }
        flow = F_NONE;
    }
    if (getpid() != 1)                  /* sh typed at a prompt: back to that shell */
        return status;
    printf("\nCPU halted\n");
    halt_os();
    return 0;
}
