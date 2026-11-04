/* kernel.c - Tynix's kernel: the OS in ROM (simulator only)
 *
 *   python tynix/make_disk.py                (once: tynix/disk.img with /bin/sh and the programs)
 *   python compiler/src/cc build tynix/kernel.c
 *   python cpu_sim/src/main.py compiler/ROM/kernel.rom --disk tynix/disk.img
 *
 * It owns the machine and runs programs from the disk side by side, as
 * AmigaOS did: preemptive, no memory protection. At boot it checks the disk,
 * frees the blocks nothing points to (fs_reclaim), and starts /bin/sh (the
 * shell, tynix/shell.c, an ordinary program). Everything else is reached by
 * the programs through TRAP: the system calls of sys/tynix.h.
 *
 *   programs   TEX2 files (cc build --exe) are loaded anywhere: a region of
 *              RAM above 0x1200000 (first fit, 1M words unless the file asks
 *              for more), [code + data][stack][heap ... environment, argv],
 *              relocated; the environment is a copy of the parent's.
 *              TEX1 files (the old fixed-address format) go to 0x1100000,
 *              the megaword kept for them, and run alone: the others wait
 *              until it ends (it uses the disk with its own fs.c).
 *   switching  every interrupt saves the program's registers on its own stack
 *              (interrupt.asm); the kernel's C code runs on the kernel's
 *              stack, with interrupts off, and picks which program the RTI
 *              goes back to. Round robin, 10 ms slices; the timer is on only
 *              when two programs want the CPU or one sleeps (tickless), so a
 *              program alone runs at full speed. Nothing ready: the idle task
 *              WAITs.
 *   waiting    getchar, wait_key, wait_ms, wait(): the program sleeps; the
 *              kernel writes the answer into its saved R0 when it comes.
 *   files      the filesystem (fs.c, dir.c) is only here; programs have
 *              numbers for their open files, closed for them when they end.
 *   keys, screen  only the foreground program reads the keyboard and draws on
 *              the RGB screen; the others wait for their turn. Text output
 *              interleaves.
 *   NMI        (Esc) on the foreground program: 1 kill, 2 continue,
 *              3 background (the shell gets the keyboard back), 4 tasks.
 *              A kill that arrives inside a system call waits for its end.
 *   pipes      SYS_PIPE gives two numbers, a read end and a write end of a
 *              256-word ring buffer (the shell's `a | b`). Reading an empty
 *              pipe sleeps until a write, or gives 0 (the end) once no write
 *              end is open; writing to a full one sleeps until a read. A
 *              program that writes to a pipe nobody reads any more ends with
 *              status 141 (Unix's SIGPIPE).
 *   FAULT      a program that runs past its stack ends with status 139.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <dirent.h>
#include <unistd.h>
#include <time.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/tynix.h>
#include <cpu.h>
#include "../compiler/libc/local.h"

int _loads_programs = 1;        /* the C compiler keeps this program's heap below 0x1100000 */

#define RAM_BASE 0x1000000
#define TEX1_BASE 0x1100000     /* the old TEX1 programs' fixed address: kept free for them */
#define LOW 0x1200000           /* TEX2 programs go from here */
#define HIGH 0x2000000          /* to the end of RAM */
#define DEFAULT_REGION 0x100000
#define MIN_HEAP 1024
#define MARGIN 64               /* stack words below the limit: the 18 an interrupt entry pushes */
#define SLICE_MS 10
#define MAX_TASKS 16
#define MAX_FDS 16
#define MAX_OBJS 32
#define KSTACK 8192
#define IDLE_STACK 128
#define SH_PID 1
#define STATUS_KILLED 130
#define STATUS_FAULT 139
#define STATUS_PIPE 141          /* wrote to a pipe with no reader */
#define MAX_PIPES 16
#define PIPE_WORDS 256

#define FREE 0                  /* task states (TASK_READY ... in sys/tynix.h) */
#define W_NONE 0                /* what a blocked task waits for */
#define W_KEY 1
#define W_CHILD 2
#define W_SLEEP 3
#define W_FG 4
#define W_PIPE 5                /* a read of an empty pipe, a write to a full one */

struct ctx { unsigned esp, ebp, limit; };   /* interrupt.asm reads and writes these */

struct task {
    struct ctx ctx;             /* first: _int_cur points here */
    int state, pid, parent;
    int wait, wait_pid;         /* W_..., and the child for W_CHILD (-1: any) */
    int *wait_who;              /* W_CHILD: where its pid goes */
    unsigned wake;              /* W_SLEEP: clock() to wake at */
    int status;                 /* a zombie's exit status */
    unsigned base, words;       /* the region (0: none) */
    int exclusive;              /* a TEX1 program: nobody else runs meanwhile */
    int kill_pending;           /* the status it ends with at the end of the system call, or 0 */
    struct pipe *pipe;          /* W_PIPE: the pipe, */
    int pipe_writes;            /* 1 for a write, 0 for a read, */
    unsigned *pipe_buf;         /* the program's words, */
    int pipe_n, pipe_done;      /* how many, and (a write) how many went in so far */
    int fd[MAX_FDS];            /* object number + 1; fd 1 = 0: the display */
    unsigned block[B_WORDS];
    char name[32];
    char cwd[_FS_PATH];
};

struct obj {                    /* an open file, directory or end of a pipe, shared by fds */
    int refs;
    FILE *file;
    DIR *dir;
    struct pipe *pipe;
    int writer;                 /* a pipe's write end */
};

struct pipe {                   /* SYS_PIPE: words written at one end, read at the other */
    int used, readers, writers; /* writers: the write ends open (0: a read gives the end) */
    int head, count;            /* the oldest word, how many wait */
    unsigned buf[PIPE_WORDS];
};

extern struct ctx *_int_cur, *_int_next;   /* interrupt.asm */
extern unsigned _int_kstack, _int_klimit, _int_depth;

static struct task table[MAX_TASKS];        /* table[0] is the idle task */
static struct obj objs[MAX_OBJS];
static struct pipe pipes[MAX_PIPES];
static struct task *cur;
static struct ctx boot;                     /* where main() ran: left at the first switch */
static int fg_pid;                          /* the program that has the keyboard and screen */
static int next_pid;                        /* the last pid given: the shell gets 1 */
static int booting;
static int changed;                         /* a task changed state: the timer is worked out again */
static int kills;                           /* a kill waits for the end of a system call */
static struct task *ex;                     /* a TEX1 program running alone, or 0 */
static unsigned timer_period, tick_due;
static unsigned kstack[KSTACK];
static unsigned idle_stack[IDLE_STACK];
static unsigned tex1_exit[6];               /* code in RAM: a TEX1 program's _Exit jumps here */

/* ---------------------------------------------------------------- tasks */

/* the saved word of a task that is not running: frame[0]; its devices word
   is frame[-1], R0 ... R15 are frame[1] ... frame[16] */
static unsigned *frame(struct task *t)
{
    return (unsigned *)(RAM_BASE + t->ctx.esp - 17);
}

static struct task *task_of(int pid)
{
    int i;
    for (i = 1; i < MAX_TASKS; i++)
        if (table[i].state != FREE && table[i].pid == pid)
            return &table[i];
    return 0;
}

/* a blocked task gets its answer and runs again */
static void answer(struct task *t, unsigned value)
{
    frame(t)[1] = value;
    t->state = TASK_READY;
    changed = 1;
    t->wait = W_NONE;
}

static void block_on(struct task *t, int what)
{
    t->state = TASK_BLOCKED;
    t->wait = what;
    changed = 1;
}

/* the frame a new task starts from: RTI goes to entry with interrupts on
   and R1 = r1, on a stack at RAM address stack */
static void start_frame(struct task *t, unsigned stack, unsigned words, unsigned entry, unsigned r1)
{
    unsigned *s = (unsigned *)stack;
    int i;
    s[0] = 0;                               /* devices selected: none */
    s[1] = entry | 1u << 27;                /* the saved word: interrupts on, flags 0 */
    for (i = 0; i < 16; i++)
        s[2 + i] = 0;
    s[3] = r1;                              /* R1 */
    t->ctx.esp = stack - RAM_BASE + 18;
    t->ctx.ebp = t->ctx.esp;
    t->ctx.limit = stack - RAM_BASE + words - MARGIN;
}

static void focus(struct task *t);

/* ---------------------------------------------------------------- open files */

static int new_obj(FILE *file, DIR *dir)
{
    int i;
    for (i = 0; i < MAX_OBJS; i++)
        if (objs[i].refs == 0) {
            objs[i].refs = 1;
            objs[i].file = file;
            objs[i].dir = dir;
            objs[i].pipe = 0;
            objs[i].writer = 0;
            return i;
        }
    return -1;
}

static void pipe_kick(struct pipe *p);

static void drop_obj(int i)
{
    struct pipe *p = objs[i].pipe;
    if (--objs[i].refs > 0)
        return;
    if (p) {                            /* an end of a pipe closes */
        objs[i].pipe = 0;
        if (objs[i].writer)
            p->writers--;
        else
            p->readers--;
        if (p->readers + p->writers == 0)
            p->used = 0;
        else
            pipe_kick(p);               /* a reader gets the end, a writer status 141 */
    }
    if (objs[i].file)
        fclose(objs[i].file);
    if (objs[i].dir)
        closedir(objs[i].dir);
    objs[i].file = 0;
    objs[i].dir = 0;
}

static int new_fd(struct task *t, int obj)
{
    int fd;
    for (fd = 3; fd < MAX_FDS; fd++)
        if (t->fd[fd] == 0) {
            t->fd[fd] = obj + 1;
            return fd;
        }
    drop_obj(obj);
    return -EMFILE;
}

/* f was written (or emptied by fopen "w"): its words and its directory entry
   go to the disk, and every other open FILE of the same file takes its first
   block and length, so that two programs appending to one file (a log) both
   land at its end instead of one writing over the other */
static void share(FILE *f)
{
    int i;
    fflush(f);
    for (i = 0; i < MAX_OBJS; i++) {
        FILE *g = objs[i].file;
        if (objs[i].refs && g && g != f && g->dir_first == f->dir_first && g->index == f->index) {
            g->first = f->first;
            g->length = f->length;
            g->word_at = (unsigned)-1;      /* a packed word it held may have changed */
        }
    }
}

static struct obj *obj_of(struct task *t, int fd)
{
    if (fd < 0 || fd >= MAX_FDS || t->fd[fd] == 0)
        return 0;
    return &objs[t->fd[fd] - 1];
}

static void close_all(void)
{
    int i;
    for (i = 0; i < MAX_OBJS; i++)
        if (objs[i].refs) {
            objs[i].refs = 1;
            drop_obj(i);
        }
}

/* ---------------------------------------------------------------- pipes */

/* up to n words out of p into buf; how many */
static int pipe_take(struct pipe *p, unsigned *buf, int n)
{
    int k = 0;
    while (k < n && p->count) {
        buf[k++] = p->buf[p->head];
        p->head = (p->head + 1) % PIPE_WORDS;
        p->count--;
    }
    return k;
}

/* up to n words of buf into p; how many fitted */
static int pipe_put(struct pipe *p, unsigned *buf, int n)
{
    int k = 0;
    while (k < n && p->count < PIPE_WORDS) {
        p->buf[(p->head + p->count) % PIPE_WORDS] = buf[k++];
        p->count++;
    }
    return k;
}

/* the programs asleep on p go on when they can: a reader when words came
   or the last writer closed (0: the end), a writer when there is room, or
   ends with status 141 when the last reader closed. Until nothing moves:
   room a reader made lets a writer in, and its words a reader out. */
static void pipe_kick(struct pipe *p)
{
    int i, moved = 1, k;
    while (moved) {
        moved = 0;
        for (i = 1; i < MAX_TASKS; i++) {
            struct task *t = &table[i];
            if (t->state != TASK_BLOCKED || t->wait != W_PIPE || t->pipe != p || t->kill_pending)
                continue;
            if (!t->pipe_writes) {
                if (p->count) {
                    answer(t, pipe_take(p, t->pipe_buf, t->pipe_n));
                    moved = 1;
                } else if (p->writers == 0)
                    answer(t, 0);
            } else if (p->readers == 0) {
                t->kill_pending = STATUS_PIPE;
                kills = 1;
            } else {
                k = pipe_put(p, t->pipe_buf + t->pipe_done, t->pipe_n - t->pipe_done);
                t->pipe_done += k;
                if (k)
                    moved = 1;
                if (t->pipe_done == t->pipe_n)
                    answer(t, t->pipe_n);
            }
        }
    }
}

static void pipe_sleep(struct task *t, struct obj *o, unsigned *buf, int n, int done)
{
    t->pipe = o->pipe;
    t->pipe_writes = o->writer;
    t->pipe_buf = buf;
    t->pipe_n = n;
    t->pipe_done = done;
    block_on(t, W_PIPE);
}

/* SYS_READ on a pipe: the words there (at most n), or sleep until some come */
static int pipe_read(struct task *t, struct obj *o, unsigned *buf, int n)
{
    struct pipe *p = o->pipe;
    int k;
    if (o->writer)
        return -EBADF;
    if (n <= 0)
        return 0;
    if (p->count) {
        k = pipe_take(p, buf, n);
        pipe_kick(p);                   /* a writer waiting for room */
        return k;
    }
    if (p->writers == 0)
        return 0;                       /* the end */
    pipe_sleep(t, o, buf, n, 0);
    return 0;
}

/* SYS_WRITE on a pipe: all n words, sleeping while it is full */
static int pipe_write(struct task *t, struct obj *o, unsigned *buf, int n)
{
    struct pipe *p = o->pipe;
    int k;
    if (!o->writer)
        return -EBADF;
    if (p->readers == 0) {
        if (t->pid != SH_PID) {         /* SIGPIPE; the shell itself only hears EPIPE */
            t->kill_pending = STATUS_PIPE;
            kills = 1;
        }
        return -EPIPE;
    }
    k = pipe_put(p, buf, n);
    pipe_kick(p);                       /* a reader waiting for words */
    if (k < n)
        pipe_sleep(t, o, buf, n, k);
    return n;
}

/* SYS_PIPE: fds[0] the read end, fds[1] the write end */
static int sys_pipe(struct task *t, int *fds)
{
    int i, r, w, fr, fw;
    struct pipe *p = 0;
    for (i = 0; i < MAX_PIPES; i++)
        if (!pipes[i].used) {
            p = &pipes[i];
            break;
        }
    if (p == 0)
        return -ENFILE;
    if ((r = new_obj(0, 0)) < 0)
        return -ENFILE;
    p->used = 1;
    p->head = p->count = 0;
    p->readers = 1;
    p->writers = 0;
    objs[r].pipe = p;
    if ((fr = new_fd(t, r)) < 0)
        return fr;                      /* new_fd dropped it: the pipe is free again */
    if ((w = new_obj(0, 0)) < 0) {
        drop_obj(t->fd[fr] - 1);
        t->fd[fr] = 0;
        return -ENFILE;
    }
    p->writers = 1;
    objs[w].pipe = p;
    objs[w].writer = 1;
    if ((fw = new_fd(t, w)) < 0) {
        drop_obj(t->fd[fr] - 1);
        t->fd[fr] = 0;
        return fw;
    }
    fds[0] = fr;
    fds[1] = fw;
    return 0;
}

/* ---------------------------------------------------------------- memory */

/* the first gap of `words` words between the regions in use, or 0 */
static unsigned find_region(unsigned words)
{
    unsigned at = LOW;
    int i, moved = 1;
    while (moved) {
        moved = 0;
        for (i = 1; i < MAX_TASKS; i++) {
            struct task *t = &table[i];
            if (t->state != FREE && t->words && at < t->base + t->words && t->base < at + words) {
                at = t->base + t->words;
                moved = 1;
            }
        }
    }
    return words <= HIGH - at ? at : 0;           /* not at + words: a huge request wraps */
}

static int region_free(unsigned base, unsigned words)
{
    int i;
    for (i = 1; i < MAX_TASKS; i++) {
        struct task *t = &table[i];
        if (t->state != FREE && t->words && base < t->base + t->words && t->base < base + words)
            return 0;
    }
    return base >= TEX1_BASE && base <= HIGH && words <= HIGH - base;
}

/* ---------------------------------------------------------------- the end of a task */

static void halt_all(void)
{
    close_all();
    for (;;)
        halt();
}

/* t has ended (exit, kill, fault): its files are closed, its memory is
   free, its parent hears about it */
static void end_task(struct task *t, int status)
{
    struct task *p = task_of(t->parent);
    int i;
    for (i = 0; i < MAX_FDS; i++)
        if (t->fd[i]) {
            drop_obj(t->fd[i] - 1);
            t->fd[i] = 0;
        }
    if (t->exclusive)
        _fs_forget();                   /* it used the disk with its own copy of fs.c */
    if (t == ex)
        ex = 0;
    changed = 1;
    t->words = 0;
    t->kill_pending = 0;
    if (t->pid == SH_PID) {             /* the shell ended: so does the OS */
        printf("[sh: exit status %d: the OS stops]\n", status);
        halt_all();
    }
    for (i = 1; i < MAX_TASKS; i++)     /* its children are the shell's now */
        if (table[i].state != FREE && table[i].parent == t->pid)
            table[i].parent = SH_PID;
    if (fg_pid == t->pid)
        focus(p ? p : task_of(SH_PID));
    if (p && p->state == TASK_BLOCKED && p->wait == W_CHILD
            && (p->wait_pid == t->pid || p->wait_pid == -1)) {
        if (p->wait_who)
            *p->wait_who = t->pid;
        answer(p, status);
        t->state = FREE;
    } else if (p) {
        t->state = TASK_ZOMBIE;
        t->status = status;
    } else
        t->state = FREE;
}

/* ---------------------------------------------------------------- scheduling */

static struct task *exclusive_task(void)
{
    return ex;
}

/* the next task to run after cur (round robin), the idle task if none */
static struct task *pick(void)
{
    int i, start = cur - table;
    struct task *ex = exclusive_task();
    if (ex)
        return ex->state == TASK_READY ? ex : &table[0];
    for (i = 1; i <= MAX_TASKS; i++) {
        struct task *t = &table[(start + i) % MAX_TASKS];
        if (t != &table[0] && t->state == TASK_READY)
            return t;
    }
    return &table[0];
}

static void run(struct task *t)
{
    if (t != cur) {
        _int_next = &t->ctx;
        cur = t;
    }
}

static int ready_count(void)
{
    int i, n = 0;
    for (i = 1; i < MAX_TASKS; i++)
        if (table[i].state == TASK_READY)
            n++;
    return n;
}

/* the timer is on only while something needs it: a time slice (two tasks
   ready) or a sleeper's wake-up */
static void retime(int force)
{
    unsigned now = clock(), need = 0;
    int i;
    if (ready_count() >= 2 && !exclusive_task())
        need = SLICE_MS;
    for (i = 1; i < MAX_TASKS; i++) {
        struct task *t = &table[i];
        if (t->state == TASK_BLOCKED && t->wait == W_SLEEP) {
            unsigned d = (int)(t->wake - now) > 0 ? t->wake - now : 1;
            if (need == 0 || d < need)
                need = d;
        }
    }
    if (need == 0) {
        if (timer_period) {
            timer_interrupt_every(0);
            timer_period = 0;
        }
    } else if (force || timer_period == 0 || (int)(now + need - tick_due) < 0) {
        timer_interrupt_every(need);
        timer_period = need;
        tick_due = now + need;
    }
}

static void wake_sleepers(void)
{
    unsigned now = clock();
    int i;
    for (i = 1; i < MAX_TASKS; i++) {
        struct task *t = &table[i];
        if (t->state == TASK_BLOCKED && t->wait == W_SLEEP && (int)(now - t->wake) >= 0)
            answer(t, 0);
    }
}

static void kill_now(struct task *t, int status)
{
    if (t->state == FREE || t->state == TASK_ZOMBIE)
        return;
    end_task(t, status);
}

/* the end of every entry into the kernel: kills that waited, then who runs,
   then the timer (force: it has just ticked, so its period started again) */
static unsigned finish_timer(int rotate, int force)
{
    int i;
    if (kills) {
        kills = 0;
        for (i = 1; i < MAX_TASKS; i++)
            if (table[i].kill_pending)
                kill_now(&table[i], table[i].kill_pending);
    }
    if (rotate || cur->state != TASK_READY || cur == &table[0] || ex)
        run(pick());
    if (changed || rotate || force) {   /* the usual system call changes nothing: no walk */
        changed = 0;
        retime(force);
    }
    return 0;
}

static unsigned finish(int rotate)
{
    return finish_timer(rotate, 0);
}

/* ---------------------------------------------------------------- the keyboard and the screen */

static void focus(struct task *t)
{
    if (t == 0 || t->pid == fg_pid)
        return;
    fg_pid = t->pid;
    t->block[B_LOST] = 1;               /* what it drew is gone: gfx_lost() says so */
    if (t->state == TASK_BLOCKED && t->wait == W_FG)
        answer(t, 0);
    if (t->state == TASK_BLOCKED && t->wait == W_KEY) {
        int c = key_pressed();
        if (c)
            answer(t, c);
    }
}

/* ---------------------------------------------------------------- loading */

static struct task *free_task(void)
{
    int i;
    for (i = 1; i < MAX_TASKS; i++)
        if (table[i].state == FREE)
            return &table[i];
    return 0;
}

/* SYS_SPAWN: load the program in path; argv is copied into its region */
static int load_program(struct task *parent, const char *path, char **argv, int out_fd, int flags)
{
    _Node node;
    unsigned head[TEX2_HEADER], load, n, entry, zero, stack, want, nrel, words, argc = 0, chars = 0;
    unsigned base, delta, at, i, top, envc = 0, env_chars = 0;
    struct task *t;
    char **args, **env;
    char **penv = parent && !parent->exclusive ? (char **)parent->block[B_ENV] : 0;
    char *p;
    int tex1;
    int in_fd = flags >> 8 & 0xFF;
    /* stdout: the file out_fd, or (1) whatever the caller's stdout is; stdin:
       the file SPAWN_IN gives, or the caller's (a file only when it has one) */
    struct obj *out = parent ? obj_of(parent, out_fd) : 0;
    struct obj *in = parent ? obj_of(parent, in_fd) : 0;
    if (out_fd != 1 && (out == 0 || (out->file == 0 && (out->pipe == 0 || !out->writer))))
        return -EBADF;
    if (in_fd && (in == 0 || (in->file == 0 && (in->pipe == 0 || in->writer))))
        return -EBADF;
    if (_fs_lookup(path, &node))
        return -errno;
    if (node.flags & _FS_DIR)
        return -EISDIR;
    if (node.flags & _FS_PACKED || node.length < 5)
        return -ENOEXEC;
    _fs_read(node.first, 0, head, node.length < TEX2_HEADER ? 5 : TEX2_HEADER);
    tex1 = head[0] == TEX1_MAGIC;
    if (!tex1 && (head[0] != TEX2_MAGIC || node.length < TEX2_HEADER))
        return -ENOEXEC;
    load = head[1];
    n = head[2];
    entry = head[3];
    zero = head[4];
    stack = tex1 ? 0x4000 : head[5];
    want = tex1 ? 0 : head[6];
    nrel = tex1 ? 0 : head[7];
    if (n + (tex1 ? 5 : TEX2_HEADER + nrel) != node.length || entry < load || entry >= load + n
            || n > HIGH - LOW || zero > HIGH - LOW || stack > HIGH - LOW)
        return -ENOEXEC;
    while (argv && argv[argc]) {
        chars += strlen(argv[argc]) + 1;
        argc++;
    }
    while (penv && penv[envc] && envc < ENV_MAX                 /* the parent's environment */
           && env_chars + strlen(penv[envc]) + 1 <= ENV_CHARS) {
        env_chars += strlen(penv[envc]) + 1;
        envc++;
    }
    words = n + zero + stack + MIN_HEAP + argc + 1 + chars + envc + 1 + env_chars;
    if (want > HIGH - LOW)
        return -ENOMEM;
    if (want > words)
        words = want;
    else if (!want && words < DEFAULT_REGION)
        words = DEFAULT_REGION;
    if ((t = free_task()) == 0)
        return -EAGAIN;
    if (tex1) {
        if (exclusive_task() || !region_free(load, words))
            return -ENOMEM;
        base = load;
    } else if ((base = find_region(words)) == 0)
        return -ENOMEM;
    _fs_read(node.first, tex1 ? 5 : TEX2_HEADER, (unsigned *)base, n);
    memset((void *)(base + n), 0, zero);
    delta = base - load;
    for (i = 0; i < nrel; i++) {                /* relocate */
        at = _fs_word(node.first, TEX2_HEADER + n + i);
        if (at < n)
            ((unsigned *)base)[at] += delta;
    }
    memset(t, 0, sizeof *t);
    t->pid = ++next_pid;
    t->parent = parent ? parent->pid : 0;
    t->base = base;
    t->words = words;
    t->exclusive = tex1;
    strcpy(t->cwd, parent ? parent->cwd : "/");
    p = argv && argv[0] ? strrchr(argv[0], '/') : 0;
    strncpy(t->name, p ? p + 1 : argv && argv[0] ? argv[0] : path, sizeof t->name - 1);
    /* argv at the top of the region: the pointers, then the strings; the
       environment below it, the same way */
    top = base + words - (argc + 1 + chars);
    args = (char **)top;
    p = (char *)(top + argc + 1);
    for (i = 0; i < argc; i++) {
        args[i] = p;
        strcpy(p, argv[i]);
        p += strlen(p) + 1;
    }
    args[argc] = 0;
    top -= envc + 1 + env_chars;
    env = (char **)top;
    p = (char *)(top + envc + 1);
    for (i = 0; i < envc; i++) {
        env[i] = p;
        strcpy(p, penv[i]);
        p += strlen(p) + 1;
    }
    env[envc] = 0;
    if (out) {
        out->refs++;
        t->fd[1] = out - objs + 1;
    }
    if (in) {
        in->refs++;
        t->fd[0] = in - objs + 1;
    }
    t->block[B_ARGC] = argc;
    t->block[B_ARGV] = (unsigned)args;
    t->block[B_PID] = t->pid;
    t->block[B_END] = top;
    t->block[B_OUT] = out != 0;
    t->block[B_IN] = in != 0;
    t->block[B_FG] = (unsigned)&fg_pid;
    t->block[B_ENV] = (unsigned)env;
    if (tex1) {                                 /* its old block: argc, argv, way back, cwd, put */
        t->block[2] = (unsigned)tex1_exit;
        t->block[3] = (unsigned)t->cwd;
        t->block[4] = 0;
    }
    start_frame(t, base + n + zero, stack, entry + delta, (unsigned)t->block);
    t->state = TASK_READY;
    changed = 1;
    if (tex1)
        ex = t;
    if (flags & SPAWN_FG)
        focus(t);
    return t->pid;
}

/* ---------------------------------------------------------------- system calls */

static int sys_wait(struct task *t, int pid, int flags, int *who)
{
    int i, any = 0;
    for (i = 1; i < MAX_TASKS; i++) {
        struct task *c = &table[i];
        if (c->state == FREE || c->parent != t->pid || (pid != -1 && c->pid != pid))
            continue;
        any = 1;
        if (c->state == TASK_ZOMBIE) {
            if (who)
                *who = c->pid;
            c->state = FREE;
            return c->status;
        }
    }
    if (!any)
        return -ECHILD;
    if (flags & WAIT_NOHANG)
        return WAIT_RUNNING;
    t->wait_pid = pid;
    t->wait_who = who;
    block_on(t, W_CHILD);
    return 0;
}

static int sys_tasks(struct task_info *buf, int max)
{
    int i, n = 0;
    for (i = 1; i < MAX_TASKS && n < max; i++) {
        struct task *t = &table[i];
        if (t->state == FREE)
            continue;
        buf[n].pid = t->pid;
        buf[n].parent = t->parent;
        buf[n].state = t->state;
        buf[n].fg = t->pid == fg_pid;
        buf[n].base = t->base;
        buf[n].words = t->words;
        strcpy(buf[n].name, t->name);
        n++;
    }
    return n;
}

static int sys_getkey(struct task *t, int wait)
{
    int c;
    if (t->pid == fg_pid) {
        c = key_pressed();
        if (c || !wait)
            return c;
    } else if (!wait)
        return 0;
    block_on(t, W_KEY);
    return 0;
}

static int file_call(struct task *t, unsigned n, unsigned a, unsigned b, unsigned c)
{
    struct obj *o;
    int r, fd;
    FILE *f;
    DIR *d;
    struct dirent *e;
    errno = 0;
    strcpy(_fs_cwd, t->cwd);
    switch (n) {
    case SYS_OPEN:
        if ((f = fopen((char *)a, (char *)b)) == 0)
            return -errno;
        if (((char *)b)[0] == 'w')
            share(f);                           /* it was emptied */
        if ((r = new_obj(f, 0)) < 0) {
            fclose(f);
            return -ENFILE;
        }
        return new_fd(t, r);
    case SYS_OPENDIR:
        if ((d = opendir((char *)a)) == 0)
            return -errno;
        if ((r = new_obj(0, d)) < 0) {
            closedir(d);
            return -ENFILE;
        }
        return new_fd(t, r);
    case SYS_CLOSE:
        if ((fd = a) < 3 || obj_of(t, fd) == 0)
            return -EBADF;
        drop_obj(t->fd[fd] - 1);
        t->fd[fd] = 0;
        return 0;
    case SYS_READ:
        if ((o = obj_of(t, a)) != 0 && o->pipe)
            return pipe_read(t, o, (unsigned *)b, c);
        if (o == 0 || o->file == 0)
            return -EBADF;
        r = fread((void *)b, 1, c, o->file);
        return ferror(o->file) ? -EIO : r;
    case SYS_WRITE:
        if ((o = obj_of(t, a)) == 0) {
            if (a == 1 || a == 2) {             /* the display */
                char *s = (char *)b;
                for (r = 0; r < (int)c; r++)
                    __builtin_out(DISPLAY_DEVICE, s[r]);
                return c;
            }
            return -EBADF;
        }
        if (o->pipe)
            return pipe_write(t, o, (unsigned *)b, c);
        if (o->file == 0)
            return -EBADF;
        {                                       /* not fwrite: it stops at a word of -1 (EOF) */
            unsigned *w = (unsigned *)b;
            for (r = 0; r < (int)c; r++) {
                fputc(w[r], o->file);
                if (ferror(o->file)) {
                    share(o->file);
                    return r ? r : -ENOSPC;
                }
            }
        }
        share(o->file);
        return r;
    case SYS_SEEK:
        if ((o = obj_of(t, a)) == 0 || o->file == 0)
            return -EBADF;
        if (fseek(o->file, b, c))
            return -errno;
        return ftell(o->file);
    case SYS_LENGTH:
        if ((o = obj_of(t, a)) == 0 || o->file == 0)
            return -EBADF;
        return o->file->length;
    case SYS_READDIR:
        if ((o = obj_of(t, a)) == 0 || o->dir == 0)
            return -EBADF;
        if ((e = readdir(o->dir)) == 0)
            return 0;
        memcpy((void *)b, e, sizeof *e);
        return 1;
    case SYS_STAT:
        return stat((char *)a, (struct stat *)b) ? -errno : 0;
    case SYS_STATVFS:
        return statvfs((char *)a, (struct statvfs *)b) ? -errno : 0;
    case SYS_REMOVE:
        return remove((char *)a) ? -errno : 0;
    case SYS_RENAME:
        return rename((char *)a, (char *)b) ? -errno : 0;
    case SYS_MKDIR:
        return mkdir((char *)a) ? -errno : 0;
    case SYS_RMDIR:
        return rmdir((char *)a) ? -errno : 0;
    case SYS_CHDIR:
        if (chdir((char *)a))
            return -errno;
        strcpy(t->cwd, _fs_cwd);
        return 0;
    case SYS_GETCWD:
        if (strlen(t->cwd) + 1 > b)
            return -ERANGE;
        strcpy((char *)a, t->cwd);
        return 0;
    case SYS_PIPE:
        return sys_pipe(t, (int *)a);
    case SYS_RECLAIM:
        for (r = 0; r < MAX_OBJS; r++)          /* lengths on the disk first: it trusts them */
            if (objs[r].refs && objs[r].file)
                fflush(objs[r].file);
        r = fs_reclaim();
        return r < 0 ? -errno : r;
    }
    return -ENOSYS;
}

/* TRAP: R1 = the call, R2 ... R5 its arguments, the answer in R0 */
static unsigned system_call(unsigned *f)
{
    struct task *t = cur, *c;
    unsigned n = f[2], a = f[3], b = f[4], d = f[5], e = f[6];
    int r = 0, rotate = 0;
    if (booting) {                      /* main()'s TRAP: the first switch, to the shell */
        booting = 0;
        return finish(0);
    }
    switch (n) {
    case SYS_EXIT:
        end_task(t, a);
        return finish(0);
    case SYS_SPAWN:
        strcpy(_fs_cwd, t->cwd);
        errno = 0;
        r = load_program(t, (char *)a, (char **)b, d, e);
        break;
    case SYS_WAIT:
        r = sys_wait(t, a, b, (int *)d);
        break;
    case SYS_KILL:
        if ((c = task_of(a)) == 0 || c->pid == SH_PID)
            r = -ESRCH;
        else if (c == t) {
            end_task(t, STATUS_KILLED);
            return finish(0);
        } else
            kill_now(c, STATUS_KILLED);
        break;
    case SYS_GETPID:
        r = t->pid;
        break;
    case SYS_YIELD:
        rotate = 1;
        break;
    case SYS_SLEEP:
        if (a) {
            t->wake = clock() + a;
            block_on(t, W_SLEEP);
        }
        rotate = 1;
        break;
    case SYS_TASKS:
        r = sys_tasks((struct task_info *)a, b);
        break;
    case SYS_FOREGROUND:
        if ((c = task_of(a)) == 0 || c->state == TASK_ZOMBIE)
            r = -ESRCH;
        else
            focus(c);
        break;
    case SYS_HALT:
        halt_all();
        break;
    case SYS_GETKEY:
        r = sys_getkey(t, a);
        break;
    case SYS_WAITFG:
        if (t->pid != fg_pid)
            block_on(t, W_FG);
        break;
    default:
        r = file_call(t, n, a, b, d);
    }
    if (t->state == TASK_READY)
        f[1] = r;
    return finish(rotate);
}

static unsigned on_trap(void)
{
    unsigned *f = (unsigned *)(RAM_BASE + cur->ctx.esp - 17);
    if (f[2] == SYS_GETKEY && cur->pid == fg_pid && !ex) {  /* what games call all the time: */
        int k = key_pressed();                              /* a key in front, answered at once */
        if (k || !f[3]) {
            f[1] = k;
            return 0;
        }
    }
    return system_call(f);
}

static unsigned on_irq(void)
{
    unsigned status = __builtin_in(INT_ACK_DEVICE), pending = status & 0xFF;
    struct task *t;
    int rotate = 0;
    irq_ack(pending);
    if (pending & IRQ_TIMER) {
        wake_sleepers();
        rotate = 1;
    }
    if ((pending & IRQ_KEYBOARD) && (t = task_of(fg_pid)) && t->state == TASK_BLOCKED
            && t->wait == W_KEY) {
        int c = key_pressed();
        if (c)
            answer(t, c);
    }
    return finish_timer(rotate, pending & IRQ_TIMER);
}

static void list_tasks(void)
{
    static const char *const states[] = {"", "ready", "waiting", "ended"};
    static const char *const waits[] = {"", " (keys)", " (child)", " (sleep)", " (screen)", " (pipe)"};
    int i;
    for (i = 1; i < MAX_TASKS; i++) {
        struct task *t = &table[i];
        if (t->state == FREE)
            continue;
        printf("  %3d %-12s %s%s%s\n", t->pid, t->name, states[t->state],
               t->state == TASK_BLOCKED ? waits[t->wait] : "", t->pid == fg_pid ? " [fg]" : "");
    }
}

/* the NMI (Esc): the foreground program; with the shell in front, nothing */
static unsigned on_nmi(void)
{
    struct task *t = task_of(fg_pid), *p;
    int c;
    if (t == 0 || t->pid == SH_PID || t->state == TASK_ZOMBIE)
        return 0;
    for (;;) {
        printf("\n[%s: 1 kill, 2 continue, 3 background, 4 tasks] ", t->name);
        do
            c = wait_key();
        while (c < '1' || c > '4');
        printf("%c\n", c);
        if (c != '4')
            break;
        list_tasks();
    }
    if (c == '1') {
        if (_int_depth > 1) {
            t->kill_pending = STATUS_KILLED;    /* inside a system call: at its end */
            kills = 1;
        } else
            kill_now(t, STATUS_KILLED);
    } else if (c == '3') {
        p = task_of(t->parent);
        focus(p ? p : task_of(SH_PID));
        if (p && p->state == TASK_BLOCKED && p->wait == W_CHILD && p->wait_pid == t->pid) {
            if (p->wait_who)
                *p->wait_who = t->pid;
            answer(p, WAIT_BACKGROUND);
        }
    }
    if (_int_depth > 1)
        return 0;                       /* the entry it interrupted finishes the job */
    return finish(0);
}

static unsigned on_fault(void)
{
    struct task *t = cur;
    if (_int_depth > 1 || t == &table[0]) {
        printf("\n[kernel: stack overflow at 0x%x: stopped]\n", frame(t)[0] & 0x1FFFFFF);
        halt_all();
    }
    printf("\n[%s: stack overflow at 0x%x]\n", t->name, frame(t)[0] & 0x1FFFFFF);
    end_task(t, STATUS_FAULT);
    return finish(0);
}

static void idle(void)
{
    for (;;)
        wait_for_interrupt();
}

int main(void)
{
    static char *sh_argv[] = {"sh", 0};
    int r, n;
    if (_fs_mount()) {
        printf("Tynix: no disk, or not formatted: start the simulator with --disk FILE\n"
               "(python tynix/make_disk.py makes one)\n");
        halt_all();
    }
    n = fs_reclaim();
    if (n > 0)
        printf("[boot: freed %d lost block%s]\n", n, n == 1 ? "" : "s");
    tex1_exit[0] = 0x0E02;              /* CPY R0, R2: the status */
    tex1_exit[1] = 0x0301;              /* DATA R1, SYS_EXIT */
    tex1_exit[2] = SYS_EXIT;
    tex1_exit[3] = 0x2300;              /* TRAP */
    tex1_exit[4] = 0x0F00;              /* HALT (not reached) */
    start_frame(&table[0], (unsigned)idle_stack, IDLE_STACK, (unsigned)idle, 0);
    table[0].state = TASK_READY;
    strcpy(table[0].name, "idle");
    cur = &table[0];
    _int_cur = &boot;
    if ((r = load_program(0, "/bin/sh", sh_argv, 1, SPAWN_FG)) < 0) {
        printf("Tynix: /bin/sh: %s\n", strerror(-r));
        halt_all();
    }
    _int_klimit = (unsigned)kstack - RAM_BASE + KSTACK - MARGIN;
    _int_kstack = (unsigned)kstack - RAM_BASE;
    set_interrupt_handler(INT_NMI, on_nmi);
    set_interrupt_handler(INT_IRQ, on_irq);
    set_interrupt_handler(INT_TRAP, on_trap);
    set_interrupt_handler(INT_FAULT, on_fault);
    irq_enable(IRQ_TIMER | IRQ_KEYBOARD);
    booting = 1;
    cur = task_of(SH_PID);
    _int_next = &cur->ctx;
    software_interrupt();               /* the first switch: main() never comes back */
    halt_all();
    return 0;
}
