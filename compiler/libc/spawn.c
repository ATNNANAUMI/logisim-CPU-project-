/* spawn.c - spawnv(): run a program from the disk and wait for it (unistd.h)
 *
 * A program for the OS is built with `python compiler/src/cc build prog.c
 * --exe` and copied to the disk (`python compiler/src/disk put`). Its file
 * (binary, one word per element) is a TEX1 executable:
 *
 *   word 0   0x31584554 ("TEX1" read as bytes)
 *   word 1   the load address (linker.py's PROGRAM_BASE, 0x1100000)
 *   word 2   n, the number of words that follow the header
 *   word 3   the entry address (the load address: an RJMP to its start)
 *   word 4   words of RAM after those n to set to 0 (its variables)
 *   then the n words, which go to the load address
 *
 * spawnv() copies the program there and jumps to its entry with R1 = a
 * block of four words: argc, argv, the address its _Exit jumps back to
 * (with R0 = the status), and the caller's current directory. The program's
 * start-up code (driver.py's crt0 for --exe) reads them; it has its own
 * copy of the C library, and the stack is the caller's, above its frame.
 * The program's exit(), or the end of its main(), comes back here through
 * longjmp, however deep its stack was.
 *
 * Programs are loaded over each other at the same address, so a program
 * for the OS can't call spawnv() itself (the build refuses), and the caller
 * keeps its own variables and heap below PROGRAM_BASE (crt0's _heap_end).
 */
#include <string.h>
#include <errno.h>
#include <setjmp.h>
#include <unistd.h>
#include "local.h"

#define EXE_MAGIC 0x31584554
#define EXE_HEADER 5
#define PROGRAM_BASE 0x1100000  /* linker.py's PROGRAM_BASE */
#define RAM_END 0x2000000       /* one past the last RAM word */

jmp_buf _spawn_back;            /* spawn.asm's _spawn_return jumps back through it */
int _spawn_status;
void _spawn_jump(unsigned entry, unsigned *block);     /* spawn.asm */
void _spawn_return(void);

static unsigned block[4];

int spawnv(const char *path, char *const argv[])
{
    unsigned head[EXE_HEADER], load, n, zero;
    int argc = 0;
    _Node node;
    if (_fs_lookup(path, &node))
        return -1;
    if (node.flags & _FS_DIR) {
        errno = EISDIR;
        return -1;
    }
    if (node.flags & _FS_PACKED || node.length < EXE_HEADER) {
        errno = ENOEXEC;
        return -1;
    }
    _fs_read(node.first, 0, head, EXE_HEADER);
    load = head[1];
    n = head[2];
    zero = head[4];
    if (head[0] != EXE_MAGIC || n != node.length - EXE_HEADER
            || load < PROGRAM_BASE || load >= RAM_END || n > RAM_END - load
            || zero > RAM_END - load - n || head[3] < load || head[3] >= load + n) {
        errno = ENOEXEC;
        return -1;
    }
    _fs_read(node.first, EXE_HEADER, (unsigned *)load, n);
    memset((void *)(load + n), 0, zero);
    while (argv && argv[argc])
        argc++;
    block[0] = argc;
    block[1] = (unsigned)argv;
    block[2] = (unsigned)_spawn_return;
    block[3] = (unsigned)_fs_cwd;
    if (setjmp(_spawn_back) == 0)
        _spawn_jump(head[3], block);
    _fs_forget();               /* the program may have changed the disk */
    return _spawn_status;
}
