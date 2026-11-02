/* sys/tynix.h - what the Tynix kernel (tynix/kernel.c) and the C library
 * of its programs (compiler/libc/tynix/, linked by `cc build --exe`) agree on:
 * the system call numbers, the block a program gets in R1, the TEX2 header.
 *
 * A system call is TRAP with R1 = the number and R2..R5 = the arguments; the
 * result comes back in R0. A negative result is -errno (the library's
 * wrappers turn it into -1 and errno). Calls that wait (a key, a child, a
 * time, the screen) put the program to sleep: other programs run meanwhile.
 * Programs should use the C functions (unistd.h, stdio.h, cpu.h), not these.
 */
#ifndef _SYS_TYNIX_H
#define _SYS_TYNIX_H

/* processes */
#define SYS_EXIT 0          /* (status) never returns */
#define SYS_SPAWN 1         /* (path, argv, out_fd, flags) -> pid; flags: SPAWN_FG | SPAWN_IN(fd) */
#define SYS_WAIT 2          /* (pid or -1, flags, int *who) -> status, or WAIT_BACKGROUND, WAIT_RUNNING */
#define SYS_KILL 3          /* (pid) */
#define SYS_GETPID 4
#define SYS_YIELD 5
#define SYS_SLEEP 6         /* (ms) */
#define SYS_TASKS 7         /* (struct task_info *buf, max) -> how many */
#define SYS_FOREGROUND 8    /* (pid): give it the keyboard and the screen */
#define SYS_HALT 9          /* close every file and stop the CPU */
/* files: numbers ("descriptors") as Unix */
#define SYS_OPEN 16         /* (path, mode) -> fd */
#define SYS_CLOSE 17        /* (fd) */
#define SYS_READ 18         /* (fd, buf, n) -> words read, 0 at the end */
#define SYS_WRITE 19        /* (fd, buf, n) -> words written */
#define SYS_SEEK 20         /* (fd, offset, whence) -> the new position */
#define SYS_STAT 21         /* (path, struct stat *) */
#define SYS_REMOVE 22       /* (path) */
#define SYS_RENAME 23       /* (from, to) */
#define SYS_MKDIR 24        /* (path) */
#define SYS_RMDIR 25        /* (path) */
#define SYS_CHDIR 26        /* (path) */
#define SYS_GETCWD 27       /* (buf, size) */
#define SYS_OPENDIR 28      /* (path) -> fd */
#define SYS_READDIR 29      /* (fd, struct dirent *) -> 1, or 0 at the end */
#define SYS_STATVFS 30      /* (path, struct statvfs *) */
#define SYS_RECLAIM 31      /* -> blocks freed */
#define SYS_LENGTH 32       /* (fd) -> the file's length (chars or words) */
/* keyboard and screen */
#define SYS_GETKEY 40       /* (wait) -> a key, or 0 (no wait and none typed) */
#define SYS_WAITFG 41       /* sleep until this program is in the foreground */

#define SPAWN_FG 1          /* SYS_SPAWN: the new program gets the foreground */
#define SPAWN_IN(fd) ((fd) << 8)    /* SYS_SPAWN: its stdin (fd 0) is that open file (0: the caller's) */
#define WAIT_NOHANG 1       /* SYS_WAIT: don't sleep, return WAIT_RUNNING if it still runs */
#define WAIT_BACKGROUND (-1000) /* SYS_WAIT's result: the NMI menu sent it to the background */
#define WAIT_RUNNING (-1001)

/* the block a program gets in R1 (in the kernel's memory, read-only for it
   except B_LOST, which gfx_lost() clears) */
#define B_ARGC 0
#define B_ARGV 1            /* copied into the program's own region */
#define B_PID 2
#define B_END 3             /* one past the program's region: where its heap ends */
#define B_OUT 4             /* 1: stdout (fd 1) is a file, from the shell's > */
#define B_FG 5              /* the address of the kernel's word holding the foreground pid */
#define B_LOST 6            /* 1: the RGB screen was taken away and given back (redraw) */
#define B_IN 7              /* 1: stdin (fd 0) is a file, not the keyboard (SPAWN_IN, or the parent's) */
#define B_WORDS 8

/* SYS_TASKS fills these */
struct task_info {
    int pid, parent, state, fg;     /* state: TASK_READY ... */
    unsigned base, words;           /* the region */
    char name[32];
};
#define TASK_READY 1
#define TASK_BLOCKED 2
#define TASK_ZOMBIE 3

/* TEX2: a program for the OS that can be loaded anywhere (cc build --exe) */
#define TEX2_MAGIC 0x32584554       /* "TEX2" read as bytes */
#define TEX1_MAGIC 0x31584554
#define TEX2_HEADER 8   /* magic, linked base, n, entry, data words to zero, stack words,
                           region words wanted (0: the default), r relocations;
                           then the n words, then r offsets (into the n words) of words
                           that hold an address: the loader adds load - base to them */

#endif
