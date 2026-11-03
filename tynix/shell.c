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
 * Words are split at spaces; "..." or '...' keep spaces inside one word.
 * Output can go to a file: `echo hi > a.txt`, `ls >> list.txt`, and a
 * program's too: `primes > p.txt` (what it prints with printf, putchar and
 * puts; its input is the keyboard unless `<` gives a file, below, and its own errors the display). `cat` with no
 * file copies the keyboard up to Ctrl-D, so `cat > notes.txt` writes a
 * file. Ctrl-D at the prompt, or `halt`, stops the CPU.
 *
 * Input can come from a file: `ed notes.txt < edits.txt` gives the program
 * that file as its stdin (getchar, fgets and scanf read it, EOF at its end;
 * key_pressed() and wait_key() still read the keyboard); `cat < f` is
 * `cat f`, and other built-ins refuse `<`. `sh < script.txt` (stdin not the
 * keyboard) runs the file's lines with no banner or prompt and ends at its
 * end instead of halting.
 *
 * The NMI (Esc) belongs to the kernel: on the program in front it asks
 * kill / continue / background / tasks; "background" gives the keyboard
 * back to this shell, which prints the job's number.
 *
 * Variables: `set NAME=value` (the shell's own), `export NAME=value`
 * (the environment, which every program started afterwards gets: getenv),
 * `unset`, `env`. $NAME, ${NAME} and $? (the last line's status) expand in
 * words and "...", not in '...'. A plain command name is looked for in the
 * folders of $PATH (default /bin) in order. At start the shell sets PATH,
 * HOME and PWD if they are missing, and an interactive one runs
 * /etc/profile when the disk has one.
 *
 * `sh -c LINE` runs that one line and ends with its status, without the
 * banner or a prompt (Claude's `claude` program runs its commands so, with
 * stdin and stdout files). `run FILE` runs the lines of a text file as if
 * typed (a batch file; lines starting with # are left out), and ends with
 * the last one's status.
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
#define MAX_ARGS 32
#define WIDTH 64                /* the text display's columns (the circuit's TTY) */
#define MAX_JOBS 16

static char line[LINE_MAX];
static char *args[MAX_ARGS + 1];
static char path[2 * LINE_MAX];
static char cwd[512];
static FILE *out;               /* where a built-in writes: stdout, or a file after > */
static char *redirect;          /* the file after > or >>, or 0 */
static char *input;             /* the file after <, or 0 */
static int append;              /* >> */
static int background;          /* the line ended with & */
static FILE *base_out;          /* where a line writes without >: stdout, or run's file */
static int depth;               /* run inside run */
static int last_status;         /* $?: the status of the last line */
static char *var_entry(const char *name, int len, int *at);
static int good_name(const char *s, int len);
static char words[2 * LINE_MAX];    /* the line's words, after quotes and $NAME */
static int words_len;
#define MAX_VARS 32
static char *vars[MAX_VARS];    /* the shell's own variables, "NAME=value" (set);
                                   exported ones are in environ instead (export) */
static struct job {             /* the programs this shell left running */
    int pid;
    char name[32];
} jobs[MAX_JOBS];

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
        if (!sizes)
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

/* set: the shell's own variables; set NAME=value...: set them (a name that
   is exported changes in the environment instead) */
static int cmd_set(int argc, char **argv)
{
    int i, len, status = 0, at;
    char name[64];
    if (argc == 1) {
        for (i = 0; i < MAX_VARS; i++)
            if (vars[i])
                fprintf(out, "%s\n", vars[i]);
        return 0;
    }
    for (i = 1; i < argc; i++) {
        char *eq = strchr(argv[i], '=');
        if ((len = assignment("set", argv[i])) < 0 || len >= (int)sizeof name || !eq) {
            if (len >= 0)
                printf("set: %s: give it as NAME=value\n", argv[i]);
            status = 1;
            continue;
        }
        strncpy(name, argv[i], len);
        name[len] = 0;
        if (getenv(name)) {             /* exported: stays in the environment */
            setenv(name, eq + 1, 1);
            continue;
        }
        forget_var(name, len);
        for (at = 0; at < MAX_VARS && vars[at]; at++)
            ;
        if (at == MAX_VARS || (vars[at] = strdup(argv[i])) == 0) {
            printf("set: no room for %s\n", name);
            status = 1;
        }
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
    if (argc == 1) {                    /* the keyboard, up to Ctrl-D */
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
    int i;
    for (i = 1; i < argc; i++)
        fprintf(out, i > 1 ? " %s" : "%s", argv[i]);
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
   stack, which the kernel has already said) */
static void report(const char *name, int status)
{
    if (status)
        printf("[%s: exit status %d]\n", name, status);
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
    report(name, status);
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

static const struct command {
    const char *name, *usage, *help;
    int (*run)(int argc, char **argv);
} commands[] = {
    {"help", "help", "these commands, the programs in /bin", cmd_help},
    {"ls", "ls [-l] [path...]", "list a directory (-l: sizes)", cmd_ls},
    {"cd", "cd [dir]", "go to a directory (none: /)", cmd_cd},
    {"pwd", "pwd", "show the current directory", cmd_pwd},
    {"cat", "cat [file...]", "show files (none: keys to Ctrl-D)", cmd_cat},
    {"echo", "echo [word...]", "show the words", cmd_echo},
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
    {"run", "run file", "run the lines of a file as commands", cmd_run},
    {"set", "set [NAME=value...]", "shell variables ($NAME), or list", cmd_set},
    {"export", "export [NAME[=v]...]", "into the environment, or list", cmd_export},
    {"env", "env", "list the environment", cmd_env},
    {"unset", "unset NAME...", "forget variables", cmd_unset},
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

/* ---------------------------------------------------------------- programs */

/* the file after <, opened as what it is (a text file "r", a binary one
   "rb", as cp does), or 0 after an error message */
static FILE *open_input(const char *cmd)
{
    struct stat st;
    int known = stat(input, &st) == 0;
    FILE *f;
    if (known && S_ISDIR(st.st_mode)) {
        printf("%s: %s: Is a directory\n", cmd, input);
        return 0;
    }
    f = fopen(input, known && !S_ISTEXT(st.st_mode) ? "rb" : "r");
    if (f == 0)
        fail(cmd, input);
    return f;
}

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

static int run_program(int argc, char **argv)
{
    int pid;
    FILE *to = 0, *in = 0;
    if (strchr(argv[0], '/'))
        strcpy(path, argv[0]);
    else
        find_program(argv[0]);
    if (input && (in = open_input(argv[0])) == 0)
        return 1;
    fflush(stdout);                     /* what the shell wrote goes first: the */
    if (base_out != stdout)             /* program writes to the same file itself */
        fflush(base_out);
    if (redirect && (to = fopen(redirect, append ? "a" : "w")) == 0) {
        if (in)
            fclose(in);
        return fail(argv[0], redirect);
    }
    pid = spawn_io(path, argv, in, to ? to : base_out != stdout ? base_out : 0,
                   background ? 0 : SPAWN_FG);
    if (to)
        fclose(to);                     /* the program has its own hold on the file */
    if (in)
        fclose(in);                     /* and on its stdin */
    if (pid < 0) {
        if (errno == ENOENT && !strchr(argv[0], '/'))
            printf("%s: no such command (help lists them)\n", argv[0]);
        else
            printf("%s: %s\n", path, strerror(errno));
        return 127;
    }
    if (background) {
        add_job(pid, argv[0]);
        return 0;
    }
    return wait_for(pid, argv[0]);
}

/* ---------------------------------------------------------------- one line */

/* $NAME and ${NAME}: a shell variable (set), else one of the environment
   (export), else nothing */
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

static const char *value_of(const char *name, int len)
{
    char *v = var_entry(name, len, 0), *e;
    int i;
    if (v)
        return v + len + 1;
    for (i = 0; environ && (e = environ[i]); i++)
        if (strncmp(e, name, len) == 0 && e[len] == '=')
            return e + len + 1;
    return "";
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

/* put c in the word being made; 0 when the words are full */
static int put_char(int c)
{
    if (words_len == sizeof words - 1)
        return 0;
    words[words_len++] = c;
    return 1;
}

/* $ at *p (a variable, ${...}, $?): its value into the word; p moved past
   it. A $ that names nothing stays a $. 0 when the words are full */
static int expand(char **pp)
{
    char *p = *pp + 1, *name = p, num[12];
    const char *v;
    int len;
    if (*p == '?') {
        sprintf(num, "%d", last_status);
        v = num;
        p++;
    } else if (*p == '{') {
        name = ++p;
        while (*p && *p != '}')
            p++;
        len = p - name;
        if (*p != '}' || !good_name(name, len)) {
            *pp += 1;
            return put_char('$');       /* not a ${NAME}: as typed */
        }
        v = value_of(name, len);
        p++;
    } else if (name_char(*p, 1)) {
        while (name_char(*p, 0))
            p++;
        v = value_of(name, p - name);
    } else {
        *pp += 1;
        return put_char('$');
    }
    *pp = p;
    while (*v)
        if (!put_char(*v++))
            return 0;
    return 1;
}

/* the next word at *s, its quotes taken out and $NAME replaced by its value
   (not inside '...'), copied into words[]; 0 when the line has no more, -1
   (as a pointer) for a missing quote or a line too long with its values */
static char *word(char **s)
{
    char *p = *s, *start;
    while (*p == ' ' || *p == '\t' || *p == '\n')
        p++;
    if (!*p)
        return 0;
    start = words + words_len;
    while (*p && *p != ' ' && *p != '\t' && *p != '\n') {
        int ok = 1;
        if (*p == '"' || *p == '\'') {
            char q = *p++;
            while (*p && *p != q && ok)
                ok = q == '"' && *p == '$' ? expand(&p) : put_char(*p++);
            if (ok && !*p) {
                printf("missing %c\n", q);
                return (char *)-1;
            }
            p++;
        } else
            ok = *p == '$' ? expand(&p) : put_char(*p++);
        if (!ok) {
            printf("the line is too long with its $ values\n");
            return (char *)-1;
        }
    }
    words[words_len++] = 0;             /* put_char kept room for it */
    *s = *p ? p + 1 : p;
    return start;
}

/* the words of the line (into words[], $NAME replaced) into args[], > and
   >> into redirect, < into input; argc, or -1 */
static int split(char *s)
{
    int n = 0;
    char *w;
    redirect = 0;
    input = 0;
    background = 0;
    words_len = 0;
    for (;;) {
        while (*s == ' ' || *s == '\t')
            s++;
        if (*s == '>') {                /* > file, >> file, >file */
            append = s[1] == '>';
            s += 1 + append;
            redirect = word(&s);
            if (redirect == 0 || redirect == (char *)-1) {
                if (redirect == 0)
                    printf("> needs a file name\n");
                return -1;
            }
            continue;
        }
        if (*s == '<' && s[1] != '<') { /* < file, <file; << stays a word (calc 1 << 2) */
            s++;
            input = word(&s);
            if (input == 0 || input == (char *)-1) {
                if (input == 0)
                    printf("< needs a file name\n");
                return -1;
            }
            continue;
        }
        if (*s == '&' && (s[1] == 0 || s[1] == '\n' || s[1] == ' ')) {
            background = 1;             /* the last word: run it in the background */
            s++;
            continue;
        }
        w = word(&s);
        if (w == 0)
            break;
        if (w == (char *)-1)
            return -1;
        if (n == MAX_ARGS) {
            printf("more than %d words\n", MAX_ARGS);
            return -1;
        }
        args[n++] = w;
    }
    args[n] = 0;
    return n;
}

/* one command line; its status */
static int run_words(char *s)
{
    int argc = split(s), i, status;
    FILE *to;
    if (argc <= 0)
        return argc < 0;
    for (i = 0; i < N_COMMANDS; i++)
        if (strcmp(args[0], commands[i].name) == 0)
            break;
    if (i == N_COMMANDS)
        return run_program(argc, args);
    if (background)
        printf("%s: a built-in command can't run in the background\n", args[0]);
    if (input) {
        if (strcmp(args[0], "cat") != 0 || argc != 1) {
            printf("%s: < works for programs and a bare cat only\n", args[0]);
            return 2;
        }
        args[1] = input;                /* cat < f: as cat f */
        args[argc = 2] = 0;
    }
    to = base_out;
    if (redirect && (to = fopen(redirect, append ? "a" : "w")) == 0)
        return fail(args[0], redirect);
    out = to;
    status = commands[i].run(argc, args);
    if (to != base_out)
        fclose(to);
    if (status == -1) {
        printf("usage: %s\n", commands[i].usage);
        status = 2;
    }
    return status;
}

/* one command line; its status, which is $? from then on (a blank line
   leaves $? as it was) */
static int run_line(char *s)
{
    char *p = s;
    while (*p == ' ' || *p == '\t' || *p == '\n')
        p++;
    if (!*p)
        return 0;
    return last_status = run_words(s);
}

/* run FILE: its lines, as if typed; the output of each goes where run's goes */
static int cmd_run(int argc, char **argv)
{
    static char text[LINE_MAX];
    FILE *f, *saved = base_out;
    int status = 0, n = 0;
    if (argc != 2)
        return -1;
    if (depth == 8) {
        printf("run: %s: runs inside runs, 8 deep\n", argv[1]);
        return 1;
    }
    if ((f = fopen(argv[1], "r")) == 0)
        return fail(argv[0], argv[1]);
    base_out = out;
    depth++;
    while (fgets(text, sizeof text, f)) {
        char *p = text;
        int len = strlen(text), c;
        n++;
        if (len == sizeof text - 1 && text[len - 1] != '\n') {     /* a cut line would run as two commands */
            while ((c = fgetc(f)) != EOF && c != '\n')
                ;
            printf("run: %s: line %d is longer than %d chars, stopped\n", argv[1], n, LINE_MAX - 1);
            status = 1;
            break;
        }
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p == '#' || *p == '\n' || !*p)
            continue;
        strcpy(line, p);                /* run_line writes into its words */
        status = run_line(line);
    }
    depth--;
    base_out = saved;
    fclose(f);
    return status;
}

int main(int argc, char **argv)
{
    struct stat st;
    base_out = stdout;
    /* the environment this shell and its programs start with, unless the
       parent's already says (sh -c from claude, sh from sh) */
    setenv("PATH", "/bin", 0);
    setenv("HOME", is_dir("/home/user") ? "/home/user" : "/", 0);
    setenv("PWD", getcwd(cwd, sizeof cwd), 1);
    if (argc >= 2 && strcmp(argv[1], "-c") == 0) {     /* sh -c LINE: that line, then the end */
        if (argc != 3) {
            printf("usage: sh -c 'command line'\n");
            return 2;
        }
        if (strlen(argv[2]) >= LINE_MAX) {
            printf("sh: the line is longer than %d chars\n", LINE_MAX - 1);
            return 2;
        }
        strcpy(line, argv[2]);
        return run_line(line);
    }
    if (!isatty(0)) {                   /* sh < FILE: its lines, then the end */
        int status = 0;
        while (fgets(line, sizeof line, stdin))
            status = run_line(line);
        reap();
        return status;
    }
    printf("Tynix shell: help lists the commands\n");
    if (stat("/etc/profile", &st) == 0 && !S_ISDIR(st.st_mode)) {
        char *profile[] = {"run", "/etc/profile", 0};
        out = stdout;
        last_status = cmd_run(2, profile);  /* the settings kept on the disk */
    }
    for (;;) {
        reap();
        printf("%s> ", getcwd(cwd, sizeof cwd));
        if (fgets(line, sizeof line, stdin) == 0)
            break;                      /* Ctrl-D */
        run_line(line);
    }
    printf("\nCPU halted\n");
    halt_os();
    return 0;
}
