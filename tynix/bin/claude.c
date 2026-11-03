/* claude.c - talk to Claude from Tynix: a program for /bin (simulator only)
 *
 *   python tynix/make_disk.py             (puts it in /bin with the others)
 *   then, in the shell:  claude                    a conversation
 *                        claude what is a FAT?     one question, one answer
 *                        claude /model sonnet      a command for the device
 *
 * Claude does not run on this CPU: the CPU is its terminal. What is typed
 * goes, a char at a time, to the Claude device (0x9C, cpu_sim/src/claude.py),
 * which calls the Claude API on the PC and sends the reply back a char at a
 * time; this program prints it as it comes. The conversation is kept on the
 * PC, so it goes on the next time `claude` runs, until /new (or /clear) or
 * the simulator closes. Lines starting with / are commands for the device
 * (/help lists them); /quit or Ctrl-D ends this program, /new starts a new
 * conversation, Ctrl-X stops a reply. `claude QUESTION` leaves the keyboard
 * alone (what is typed meanwhile is the shell's): Esc's menu stops it.
 *
 * Claude can use the CPU: the device sends a tool between STX and ETX, and
 * this program runs it and sends back what happened.
 *   run_command  `sh -c LINE` (a fresh shell, in this program's directory)
 *                with stdin from /tmp/.claude_in (the input Claude gave,
 *                then EOF) and stdout to /tmp/.claude_out; it waits for it
 *                at most the timeout (/timeout, 30 s), then kills it and
 *                every program it started (status 130). The answer is
 *                `exit status N` and at most 8000 chars of output; the first
 *                lines are shown here too. `cd DIR` changes this program's
 *                directory, so the next commands run there.
 *   write_file   a text file on the disk.
 * With /approve on, each asks y/n first. The tools on the PC (reading the
 * permitted files, the screenshot) run in the simulator: only a line says so.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <cpu.h>

#define LINE_MAX 256
#define OUT_CAP 8000            /* chars of a command's output sent to Claude */
#define SHOW_LINES 12           /* lines of it shown on the display */
#define IN_FILE "/tmp/.claude_in"
#define OUT_FILE "/tmp/.claude_out"
#define CTRL_X 24
#define WIDTH 64                /* the text display's columns: replies are wrapped there */

static char line[LINE_MAX + 1];
static char command[LINE_MAX + 1];
static char field[LINE_MAX + 1];
static char output[OUT_CAP + 1];
static int col;                 /* the display's column: 0 at the start of a line */
static char ahead[LINE_MAX];    /* keys typed while a reply came: the next line's start */
static int n_ahead;
static int keys = 1;            /* look at the keyboard during a reply (not for `claude QUESTION`) */

static void show(int c)
{
    putchar(c);
    col = c == '\n' ? 0 : col + 1;
}

/* a char of the reply: words that would pass WIDTH go to the next line; the
   spaces before a word wait for it, so no line ends with them */
static char word[WIDTH];
static int word_len, spaces;

static void flush_word(void)
{
    int i;
    if (word_len == 0)
        return;
    if (col && col + spaces + word_len > WIDTH) {
        show('\n');
        spaces = 0;
    }
    for (; spaces > 0; spaces--)
        show(' ');
    for (i = 0; i < word_len; i++)
        show(word[i]);
    word_len = 0;
}

static void say(int c)
{
    if (c == ' ') {
        flush_word();
        spaces++;
    } else if (c == '\n') {
        flush_word();
        spaces = 0;
        show(c);
    } else {
        if (word_len == WIDTH)
            flush_word();
        word[word_len++] = c;
    }
}

static void show_text(const char *s)
{
    while (*s)
        show(*s++);
}

static void new_line(void)
{
    flush_word();
    spaces = 0;
    if (col)
        show('\n');
}

static void send(const char *s)
{
    while (*s)
        device_out(CLAUDE_DEVICE, *s++);
}

/* the next char from the device; it waits (sleeping) for one */
static int next(void)
{
    int c;
    while ((c = device_in(CLAUDE_DEVICE)) == 0)
        wait_ms(5);
    return c;
}

/* a field of a tool into buf (cut at size - 1); the char that ended it */
static int read_field(char *buf, int size)
{
    int c, n = 0;
    while ((c = next()) != CLAUDE_FIELD && c != CLAUDE_STOP)
        if (n < size - 1)
            buf[n++] = c;
    buf[n] = 0;
    return c;
}

/* the rest of a field into the open file f (or nowhere); its length */
static int copy_field(FILE *f, int *end)
{
    int c, n = 0;
    while ((c = next()) != CLAUDE_FIELD && c != CLAUDE_STOP) {
        if (f)
            fputc(c, f);
        n++;
    }
    *end = c;
    return n;
}

/* skip what is left of a tool frame */
static void drain(int end)
{
    while (end != CLAUDE_STOP)
        end = next();
}

/* /approve on: y or n from the keyboard */
static int ask(const char *what, const char *arg)
{
    int k;
    new_line();
    fprintf(stderr, "[claude wants to %s: %s] allow? (y/n) ", what, arg);
    if (n_ahead && (ahead[0] | 0x20) == 'y' || n_ahead && (ahead[0] | 0x20) == 'n') {
        k = ahead[0];                           /* typed ahead: it answers */
        memmove(ahead, ahead + 1, --n_ahead);
    } else do
        k = wait_key();
    while (k != 'y' && k != 'Y' && k != 'n' && k != 'N' && k != 4);
    fprintf(stderr, "%c\n", k == 4 ? 'n' : k);
    return k == 'y' || k == 'Y';
}

/* pid and every program it started, the youngest first */
static void kill_tree(int pid)
{
    struct task_info t[16];
    int tree[16], k = 1, n = tasks(t, 16), i, j, grown = 1;
    tree[0] = pid;
    while (grown) {
        grown = 0;
        for (i = 0; i < n; i++) {
            int in = 0, under = 0;
            for (j = 0; j < k; j++) {
                in |= t[i].pid == tree[j];
                under |= t[i].parent == tree[j];
            }
            if (under && !in && k < 16) {
                tree[k++] = t[i].pid;
                grown = 1;
            }
        }
    }
    for (i = k - 1; i >= 0; i--)
        kill(tree[i], 0);
}

/* sh -c command, stdin from IN_FILE; its status (-1: it could not start),
   *late = 1 if the timeout killed it */
static int run(const char *cmd, int timeout, int *late)
{
    char *argv[4];
    FILE *in = fopen(IN_FILE, "r"), *out = fopen(OUT_FILE, "w");
    int pid, status = -1;
    clock_t start = clock();
    *late = 0;
    if (in == 0 || out == 0) {
        if (in)
            fclose(in);
        if (out)
            fclose(out);
        return -1;
    }
    argv[0] = "sh";
    argv[1] = "-c";
    argv[2] = (char *)cmd;
    argv[3] = 0;
    pid = spawn_io("/bin/sh", argv, in, out, SPAWN_FG);
    fclose(in);                         /* the program has its own hold on them */
    fclose(out);
    if (pid < 0)
        return -1;
    for (;;) {
        int r = waitpid(pid, &status, WAIT_NOHANG);
        if (r == pid)
            break;
        if (r < 0)
            return -1;
        if ((clock() - start) / (CLOCKS_PER_SEC / 1000) > (clock_t)timeout * 1000) {
            kill_tree(pid);
            *late = 1;
            waitpid(pid, &status, 0);
            break;
        }
        wait_ms(20);
    }
    if (status == SPAWN_BACKGROUND)     /* the NMI menu sent it away: it goes on */
        status = 0;
    return status;
}

/* the run_command tool: r (or R: ask first), then timeout, command, input */
static void run_tool(int ask_first)
{
    int end, timeout, late = 0, status, n = 0, total = 0, lines = 0, c;
    FILE *f;
    char head[80];
    read_field(field, sizeof field);
    timeout = atoi(field);
    end = read_field(command, sizeof command);
    f = fopen(IN_FILE, "w");
    if (end == CLAUDE_FIELD)
        copy_field(f, &end);
    if (f)
        fclose(f);
    drain(end);
    if (ask_first && !ask("run", command)) {
        send("the user said no: the command was not run");
        device_out(CLAUDE_DEVICE, CLAUDE_SEND);
        return;
    }
    new_line();
    printf("[claude runs: %s]\n", command);
    if (strncmp(command, "cd", 2) == 0 && (command[2] == 0 || command[2] == ' ')) {
        char *dir = command + 2;
        while (*dir == ' ')
            dir++;
        if (chdir(*dir ? dir : "/")) {
            sprintf(output, "cd: %s: %s\nexit status 1", dir, strerror(errno));
            printf("%s\n", output);
        } else
            sprintf(output, "exit status 0 (the directory is now %s)", getcwd(field, sizeof field));
        send(output);
        device_out(CLAUDE_DEVICE, CLAUDE_SEND);
        return;
    }
    status = run(command, timeout > 0 ? timeout : 30, &late);
    if (status == -1) {
        sprintf(output, "could not start /bin/sh: %s", strerror(errno));
        printf("%s\n", output);
        send(output);
        device_out(CLAUDE_DEVICE, CLAUDE_SEND);
        return;
    }
    if ((f = fopen(OUT_FILE, "r"))) {
        while ((c = fgetc(f)) != EOF) {
            if (n < OUT_CAP)
                output[n++] = c;
            total++;
        }
        fclose(f);
    }
    output[n] = 0;
    for (c = 0; c < n && lines < SHOW_LINES; c++) {     /* the first lines, here too */
        show(output[c]);
        if (output[c] == '\n')
            lines++;
    }
    new_line();
    if (c < n)
        printf("[... %d more chars of output]\n", total - c);
    if (late)
        printf("[killed: it ran past %d s]\n", timeout);
    else if (status)
        printf("[exit status %d]\n", status);
    if (late)
        sprintf(head, "exit status %d (killed: it ran past the %d s timeout)\n", status, timeout);
    else
        sprintf(head, "exit status %d\n", status);
    send(head);
    send(output);
    if (total > n) {
        sprintf(head, "\n[... output cut: %d chars, the first %d sent]", total, n);
        send(head);
    }
    device_out(CLAUDE_DEVICE, CLAUDE_SEND);
}

/* the write_file tool: w (or W: ask first), then path, content */
static void write_tool(int ask_first)
{
    int end = read_field(field, sizeof field), n;
    FILE *f = 0;
    char result[LINE_MAX + 80];
    if (end == CLAUDE_FIELD && (!ask_first || ask("write", field))) {
        new_line();
        printf("[claude writes %s]\n", field);
        if ((f = fopen(field, "w")) == 0)
            sprintf(result, "%s: %s", field, strerror(errno));
    } else
        sprintf(result, "the user said no: %s was not written", field);
    n = end == CLAUDE_FIELD ? copy_field(f, &end) : 0;
    drain(end);
    if (f) {
        if (fclose(f))
            sprintf(result, "%s: %s", field, strerror(errno));
        else
            sprintf(result, "wrote %d chars to %s", n, field);
    }
    send(result);
    device_out(CLAUDE_DEVICE, CLAUDE_SEND);
}

/* the reply, until the end of the turn; Ctrl-X stops it */
static void reply(void)
{
    int c, k, quiet = 0;
    for (;;) {
        c = device_in(CLAUDE_DEVICE);
        if (keys && (c == 0 || ++quiet == 64)) {   /* now and then, and while it waits */
            quiet = 0;
            if ((k = key_pressed()) == CTRL_X)
                device_out(CLAUDE_DEVICE, CLAUDE_STOP);
            else if (k && n_ahead < LINE_MAX)
                ahead[n_ahead++] = k;
        }
        if (c == 0) {
            wait_ms(10);
            continue;
        }
        if (c == CLAUDE_END)
            break;
        if (c == CLAUDE_TOOL) {
            c = next();
            if (c == 'r' || c == 'R')
                run_tool(c == 'R');
            else if (c == 'w' || c == 'W')
                write_tool(c == 'W');
            else {                              /* a tool this program does not know */
                drain(c);
                send("this CPU program does not know that tool");
                device_out(CLAUDE_DEVICE, CLAUDE_SEND);
            }
            continue;
        }
        say(c);
    }
    new_line();
}

/* a line from the keyboard into line, starting with the keys typed ahead,
   echoed, Backspace works; 0 at Ctrl-D on an empty line. With stdin a file
   (isatty(0) is 0), fgets. */
static int read_line(void)
{
    int n = 0, i, k;
    char *p;
    if (!isatty(0)) {
        if (fgets(line, sizeof line, stdin) == 0)
            return 0;
        if ((p = strchr(line, '\n')))
            *p = 0;
        return 1;
    }
    for (i = 0;; ) {
        k = i < n_ahead ? ahead[i++] : wait_key();
        if (i == n_ahead)
            n_ahead = i = 0;
        if (k == 4 && n == 0)
            return 0;
        if (k == '\n' || k == '\r') {
            show('\n');
            break;
        }
        if (k == '\b' || k == 127) {
            if (n > 0) {
                n--;
                putchar('\b');
                col--;
            }
        } else if (k >= ' ' && k < 127 && n < LINE_MAX - 1) {
            line[n++] = k;
            show(k);
        }
    }
    line[n] = 0;
    return 1;
}

static void ask_claude(const char *text)
{
    send(text);
    device_out(CLAUDE_DEVICE, CLAUDE_SEND);
    reply();
}

int main(int argc, char **argv)
{
    int i;
    device_out(CLAUDE_DEVICE, CLAUDE_HELLO);
    mkdir("/tmp");
    if (argc > 1) {                             /* claude words...: one question */
        keys = 0;                               /* keys typed ahead are the shell's (Esc stops it) */
        for (i = 1; i < argc; i++) {
            if (i > 1)
                device_out(CLAUDE_DEVICE, ' ');
            send(argv[i]);
        }
        device_out(CLAUDE_DEVICE, CLAUDE_SEND);
        reply();
        return 0;
    }
    printf("Claude (on the PC, through device 0x9C): /help lists commands.\n"
           "/new starts over, Ctrl-X stops a reply, /quit or Ctrl-D ends.\n");
    for (;;) {
        show_text("you> ");
        if (!read_line())
            break;
        col = 0;
        if (line[0] == 0)
            continue;
        if (strcmp(line, "/quit") == 0)
            break;
        if (strcmp(line, "/new") == 0) {
            device_out(CLAUDE_DEVICE, CLAUDE_NEW);
            printf("(a new conversation)\n");
            continue;
        }
        ask_claude(line);
    }
    new_line();
    return 0;
}
