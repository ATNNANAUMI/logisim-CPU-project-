/* shell.c - the OS (Tynix): a command shell in ROM for the files and programs on
 * the disk (simulator only)
 *
 *   python os/make_disk.py                (once: os/disk.img, the examples in /bin)
 *   python compiler/src/cc build os/shell.c
 *   python cpu_sim/src/main.py compiler/ROM/shell.rom --disk os/disk.img
 *   (or: python compiler/src/cc run os/shell.c --disk os/disk.img
 *    --keys $'ls /bin\nprimes\nhalt\n')
 *
 * It checks the disk, then shows a prompt with the current directory. The
 * built-in commands (help lists them) work on the files: ls cd pwd cat echo
 * rm mv cp mkdir rmdir df clear halt. Any other name is a program: /bin/NAME,
 * or a path when the name has a '/' (./prog, /games/snake); spawnv() loads
 * it, runs it in the current directory and comes back here when it ends.
 * A program that can't be loaded gives a message and the shell goes on.
 *
 * Words are split at spaces; "..." or '...' keep spaces inside one word.
 * Output can go to a file: `echo hi > a.txt`, `ls >> list.txt`, and a
 * program's too: `primes > p.txt` (what it prints with printf, putchar and
 * puts; its input is still the keyboard, and its own errors the display). `cat` with no
 * file copies the keyboard up to Ctrl-D, so `cat > notes.txt` writes a
 * file. Ctrl-D at the prompt, or `halt`, stops the CPU.
 *
 * A program can't start another (spawnv() would load the child over it). One
 * that wants to leave and come back, like visual_file_manager, writes command
 * lines into /.next and ends with exit status 254 (EXIT_NEXT): the shell reads
 * and deletes the file and runs each line as if typed, once it is back at its
 * prompt loop (a loop, not a nested call, so the stack does not grow).
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

#define LINE_MAX 256
#define MAX_ARGS 32
#define WIDTH 64                /* the text display's columns (the circuit's TTY) */
#define EXIT_NEXT 254           /* a program that ends with this status asks the shell to run */
#define NEXT_FILE "/.next"      /* the command lines in this file (visual_file_manager does) */
#define NEXT_MAX 1024

static char line[LINE_MAX];
static char *args[MAX_ARGS + 1];
static char path[2 * LINE_MAX];
static char cwd[512];
static FILE *out;               /* where a built-in writes: stdout, or a file after > */
static char *redirect;          /* the file after > or >>, or 0 */
static int append;              /* >> */
static char *next_text;         /* the lines a program left in NEXT_FILE, to run when it is back */

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
    return chdir(to) ? fail("cd", to) : 0;
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
    exit(0);
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

/* a program cannot start another (spawnv() would load it over itself), so
   one that wants to leave and come back writes command lines into NEXT_FILE
   and ends with EXIT_NEXT: the shell runs the lines, the last one usually
   starting the program again. Returns the file's text (deleted from the
   disk, malloc'd), or 0 if there is none. */
static char *take_next(void)
{
    FILE *f = fopen(NEXT_FILE, "r");
    char *text;
    int c, n = 0;
    if (f == 0)
        return 0;
    if ((text = malloc(NEXT_MAX + 1)) == 0) {
        fclose(f);
        return 0;
    }
    while (n < NEXT_MAX && (c = fgetc(f)) != EOF)
        text[n++] = c;
    text[n] = 0;
    fclose(f);
    remove(NEXT_FILE);
    return text;
}

static int run_program(int argc, char **argv)
{
    int status;
    FILE *to = 0;
    if (strchr(argv[0], '/'))
        strcpy(path, argv[0]);
    else
        sprintf(path, "/bin/%s", argv[0]);
    if (redirect && (to = fopen(redirect, append ? "a" : "w")) == 0)
        return fail(argv[0], redirect);
    errno = 0;                          /* the program's own errno is another variable */
    status = spawnv_to(path, argv, to);
    if (to)
        fclose(to);                     /* after the program: spawnv forgot what the disk held */
    if (status == -1 && errno) {
        if (errno == ENOENT && !strchr(argv[0], '/'))
            printf("%s: no such command (help lists them)\n", argv[0]);
        else
            printf("%s: %s\n", path, strerror(errno));
        return 127;
    }
    if (status == EXIT_NEXT && (next_text = take_next()))
        return 0;                       /* the lines run when this one is done: no loop in the stack */
    if (status)
        printf("[%s: exit status %d]\n", argv[0], status);
    return status;
}

/* ---------------------------------------------------------------- one line */

/* the next word at *s, its quotes taken out, ended by a 0 written in the
   line; 0 when the line has no more, -1 (as a pointer) for a missing quote */
static char *word(char **s)
{
    char *p = *s, *start, *w, end;
    while (*p == ' ' || *p == '\t' || *p == '\n')
        p++;
    if (!*p)
        return 0;
    start = w = p;
    while (*p && *p != ' ' && *p != '\t' && *p != '\n') {
        if (*p == '"' || *p == '\'') {
            char q = *p++;
            while (*p && *p != q)
                *w++ = *p++;
            if (!*p) {
                printf("missing %c\n", q);
                return (char *)-1;
            }
            p++;
        } else
            *w++ = *p++;
    }
    end = *p;
    *w = 0;                             /* may be where end was */
    *s = end ? p + 1 : p;
    return start;
}

/* the words of the line into args[], > and >> into redirect; argc, or -1 */
static int split(char *s)
{
    int n = 0;
    char *w;
    redirect = 0;
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

static void run_line(char *s)
{
    int argc = split(s), i, status;
    if (argc <= 0)
        return;
    for (i = 0; i < N_COMMANDS; i++)
        if (strcmp(args[0], commands[i].name) == 0)
            break;
    if (i == N_COMMANDS) {
        run_program(argc, args);
        return;
    }
    out = stdout;
    if (redirect && (out = fopen(redirect, append ? "a" : "w")) == 0) {
        fail(args[0], redirect);
        return;
    }
    status = commands[i].run(argc, args);
    if (out != stdout)
        fclose(out);
    if (status == -1)
        printf("usage: %s\n", commands[i].usage);
}

int main(void)
{
    printf("Tynix shell: help lists the commands\n");
    if (!is_dir("/")) {
        if (errno == ENODEV)
            printf("no disk, or not formatted: start the simulator with --disk FILE\n"
                   "(python os/make_disk.py makes one)\n");
        else
            printf("disk: %s\n", strerror(errno));
    }
    for (;;) {
        printf("%s> ", getcwd(cwd, sizeof cwd));
        if (fgets(line, sizeof line, stdin) == 0)
            break;                      /* Ctrl-D */
        run_line(line);
        while (next_text) {
            char *text = next_text, *nl;
            next_text = 0;
            for (nl = text; *nl; ) {
                char *start = nl;
                while (*nl && *nl != '\n')
                    nl++;
                if (*nl)
                    *nl++ = 0;
                if (strlen(start) < LINE_MAX)
                    run_line(start);
            }
            free(text);
        }
    }
    printf("\nCPU halted\n");
    return 0;
}
