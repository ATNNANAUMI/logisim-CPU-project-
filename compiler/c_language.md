# Tiny C - the C language for the logic-gate CPU

A C compiler for the CPU, with a C library. It takes C99 (and some C11
and GNU additions), turns each `.c` file into assembly for
`compiler/src/asm`, and links the result with the C library into a ROM image
that runs in the simulator and on the circuit.

The rule it follows: **a program that is valid C, and doesn't depend on the
sizes of types, prints the same as when it is built with gcc.** The test
programs in `compiler/src/cc/tests/` are checked against gcc's output. Where
the machine forces a difference (32-bit `char`, 32-bit `double`, no
`long long`), the compiler says so with an error, or this document says so.

The compiler is in `compiler/src/cc/`, the library in `compiler/libc/`
(headers in `compiler/libc/include/`), examples in `compiler/examples/c/`.
The choices made while building it, and what is still a guess, are listed
in [`c_decisions.md`](c_decisions.md).


## 1. Using the compiler

Run from the project root:

```
python compiler/src/cc run prog.c                  # build, then run in the simulator (no window)
python compiler/src/cc build prog.c [more.c x.asm y.obj] [-o prog.rom] [--map]
python compiler/src/cc compile prog.c [-o prog.asm]   # C to assembly only
python compiler/src/cc build prog.c --exe          # a program for the OS: prog.exe, for the disk
python run.py build prog.c                         # build, then open the simulator window
```

* `build` and `run` take `.c`, `.asm` and `.obj` files together and link
  the C library in. Output goes to `compiler/ROM/` like the assembler's (the
  first input's name with `.rom`; `-o name.rom` picks another name, an `-o`
  with a folder is used as written). `build` also writes each `.c` file's
  `.asm` next to the `.rom`, with the C source lines as comments, and a
  `.map` (labels and C line addresses: the simulator window uses it to show
  the C source and step by C lines).
* `run` prints what the program writes on the display. `--keys TEXT` types
  keys first (`--keys $'12\n'` in bash for Enter), `--steps N` limits the
  instructions (default 50 million), `--stats` prints the instruction count
  and R0 at the end, `--trace` prints every instruction, `--screen F.png`
  saves the RGB screen, `--disk FILE` attaches a disk image (created if
  missing).
* `-I dir` adds a folder for `#include`, `-D NAME[=value]` defines a macro,
  `-w` hides warnings, `--no-libc` leaves the library and start-up code out
  (the program then needs its own `start`), `--lib FILE` links an assembly
  (or `.obj`) library, keeping only the functions the program uses (like the
  assembler's `--lib`).
* `build --exe` makes a **program for the OS**: `compiler/ROM/prog.exe`, to
  copy to the disk (`python compiler/src/disk put disk.img
  compiler/ROM/prog.exe /bin/prog`) and run with `spawnv()` (section 4).
  Any C program works; it gets `argc`/`argv` from its caller.
* On the circuit: `python logisim/run_rom.py logisim/CPU.circ compiler/ROM/prog.rom`.
  The circuit runs about 160 instructions a second, so keep circuit runs
  small: `hello.c` takes 1 400 instructions, a `printf` with a float a few
  thousand.

Errors and warnings look like gcc's: `prog.c:12:5: error: 'x' undeclared`.
After an error the compiler skips to the next statement or declaration and goes on, so one run reports up to 20 errors (a preprocessor error still stops it).


## 2. The machine as C sees it

The CPU addresses 32-bit words, not bytes. So every scalar type is one word:

| type | size (`sizeof`) | range / format |
| --- | --- | --- |
| `char`, `signed char` | 1 | 32-bit two's complement (char is signed) |
| `unsigned char` | 1 | 0 .. 4294967295 |
| `short`, `int`, `long` | 1 | 32-bit two's complement |
| `unsigned short`, `unsigned`, `unsigned long` | 1 | 0 .. 4294967295 |
| `_Bool` | 1 | 0 or 1 |
| `float`, `double`, `long double` | 1 | IEEE-754 single precision (the CPU's float unit) |
| pointers | 1 | a 25-bit address: ROM `0x0000000`-`0x0FFFFFF`, RAM `0x1000000`-`0x1FFFFFF` |
| `enum` | 1 | `int` |

* `CHAR_BIT` is 32 and `sizeof(char) == sizeof(int) == 1`. This is allowed
  by the C standard (some DSPs do the same). A string holds one character per
  word, like the assembly library's strings.
* A `char` never wraps at 8 bits: `char c = 300;` keeps 300. Code that relies
  on 8-bit wrap-around needs `& 0xFF`.
* `unsigned char` and `unsigned short` promote to `unsigned int` (an `int`
  can't hold all their values).
* `double` is the same 32-bit float as `float`: about 7 significant digits.
  Constants without `f` are rounded to float too.
* `long long` is an error (no 64-bit integers). `int8_t`, `int16_t`,
  `int64_t` and their unsigned forms don't exist in `<stdint.h>` (a 32-bit
  stand-in would wrap at the wrong place); `int32_t`, `uint32_t`, the
  `least`/`fast` types and `intptr_t` do.
* Structs have no padding: every member takes its size in words. A
  bit-field packs into 32-bit words.
* `NULL` is address 0 (the ROM word that holds the entry jump; no object is
  ever there).

Behaviour C leaves to the implementation:

| what | here |
| --- | --- |
| `>>` on a negative number | arithmetic (sign bits come in), like gcc |
| `/` and `%` | truncate toward zero, `%` has the dividend's sign (C99) |
| signed overflow | wraps around (undefined in C: don't rely on it) |
| division by 0 | `x / 0` gives `x` and `x % 0` gives 0, like the CPU's `DIV`/`MOD` (an unsigned `x` of 2^31 or more gives something else; undefined in C) |
| float to int out of range, or NaN | whatever the CPU's `INT` gives (see `c_decisions.md`) |
| writing to a string literal | the write is ignored: string literals are in ROM (on the circuit it also raises the "tried writing in ROM" line) |
| writing to a `const` global | the same: `const` global data is in ROM |
| `char` | signed |
| the order arguments are evaluated | left to right |
| bit-fields | from bit 0 up, in 32-bit words; plain `int` bit-fields are signed |


## 3. What is supported

Everything in C99 except variable-length arrays, `long long`, complex
numbers and wide-character functions:

* every operator and statement, `switch` (dense ones become a jump table),
  `goto` and labels
* `int`, `char`, `short`, `long`, `unsigned`, `float`, `double`, `_Bool`,
  pointers, arrays (any number of dimensions), structs, unions, enums,
  bit-fields, `typedef`, function pointers
* structs and unions assigned, passed and returned by value
* initializers: nested braces, designated (`.x = 1`, `[3] = 4`, also
  `[2 ... 5] = 0`), strings for `char` arrays, arrays sized by their
  initializer, flexible array members
* compound literals, declarations anywhere, `for (int i = ...)`, `//`
  comments, `inline`, `restrict`, `__func__`, `_Static_assert`, `_Generic`,
  `_Alignof`/`_Alignas` (everything is aligned to one word), anonymous struct
  and union members
* variadic functions (`<stdarg.h>`), `setjmp`/`longjmp`
* the preprocessor: `#include`, object and function-like macros, `#`, `##`,
  `__VA_ARGS__`, `#if`/`#elif` with `defined` and `__has_include`, `#error`,
  `#warning`, `#pragma once`; `__FILE__`, `__LINE__`, `__DATE__`, `__TIME__`,
  `__COUNTER__`. `__STDC_VERSION__` is `199901L`; `__TINYC__` is defined.
* from GNU C: case ranges (`case 1 ... 5:`), `typeof`, `, ## __VA_ARGS__`,
  `__attribute__((...))` (read and ignored), `asm("...")` (section 6)

Not supported, each with a clear error: `long long`, variable-length
arrays, K&R-style function definitions, implicit function declarations,
GNU statement expressions `({ ... })`, `a ?: b`, `_Thread_local`, `_Atomic`.


## 4. Memory, start-up and the stack

```
ROM  0x00000   RJMP start (from the linker)
               crt0, your code, the library code, string literals, const data,
               and the starting values of initialised globals
RAM  0x1000000 the stack (16K words), grows upward
     0x1004000 global and static variables
     _end      the heap (malloc) up to 0x1FFFFFF (up to 0x10FFFFF in a
               program that calls spawnv: programs are loaded from 0x1100000)
```

* `start` (in the generated start-up code, crt0) calls each file's
  `_init_<file>` routine, which copies the starting values of the file's
  global variables from ROM into RAM and clears the rest. A reset (without
  clearing RAM) therefore starts the program cleanly again.
* Then `main(0, {NULL})` runs (`argc` is 0), and `exit(main's result)`:
  `atexit` functions run, then the CPU halts with the exit status in R0.
  RESUME halts it again.
* Each call takes 2 words of stack plus its arguments and its locals; deep
  recursion can run past the 16K words of stack (it wraps, nothing checks).
* **A program for the OS** (`build --exe`) lives all in RAM: its code,
  constants and variables from `0x1100000`, its heap after them up to
  `0x1FFFFFF`. `spawnv(path, argv)` loads it from the disk and calls
  `main(argc, argv)`; `exit()` or the end of `main` goes back to the caller
  with the status (`spawnv`'s result) instead of halting. Its variables
  start fresh on every run, it starts in the caller's current directory,
  and it shares the stack with the caller (above the caller's frame). It
  has its own copy of the library: open files, `errno`, the heap and
  `atexit` are its own. Nothing protects the caller's memory from it.


## 5. Calling convention and mixing with assembly

C functions use the same convention as `compiler/examples/stdlib/stdlib.asm`
(`TECHNICAL.md` 5.1), so C and assembly can call each other:

* the caller pushes the arguments first to last and uses `CALL f, N`; the
  result is in R0; every register may change in a call
* inside the function, argument word i of N is at `EBP - (N+1) + i`
* a struct argument is pushed word by word; a struct result is written
  through a hidden pointer, passed as the first argument
* a variadic function gets its variadic arguments pushed first, then the
  fixed ones, then the number of variadic words: the fixed arguments keep
  their usual places and `va_start` finds the rest

A C name is its assembly label: `int twice(int n)` is `twice:` and is
`.global` unless `static`. Names the assembler can't take (instruction or
register names like `add`, `data`, `r1`, or names starting with `__`) get a
`_X` prefix: `add` is `_Xadd`. Calling an assembly function from C needs
only a prototype; the build links the `.asm` file given with the `.c` files:

```c
int twice(int n);              /* in twice.asm, .global twice */
```

`compiler/src/cc/selftest.py` (`check_mixed_with_assembly`) has a complete
example in both directions. The assembly standard library
(`compiler/examples/stdlib/stdlib.asm`) is not linked into C programs: the
C library has its own functions with the standard names. It can still be
used: declare the functions you need and give the file with `--lib`, so only
those are linked:

```c
void print_int(int n);           /* in stdlib.asm */
int ipow(int base, int exp);
```

```
python compiler/src/cc run prog.c --lib compiler/examples/stdlib/stdlib.asm
```

Some of its names (`abs`, `rand`, `malloc`, ...) are also C library names;
a program that uses both gets a link error naming the clash. (Its integer
power function is `ipow`, so it doesn't clash with C's `pow`.)


## 6. Machine-specific features

`<cpu.h>`:

| | |
| --- | --- |
| `show_hex(v)` | shows v on the 8-digit hex display (device `0x3C`) |
| `key_pressed()` | the next key if one was typed, else 0: no waiting, no echo |
| `wait_key()` | waits for one key and returns it, no echo |
| `wait_ms(ms)` | does nothing for `ms` milliseconds (the timer, device `0x7C`) |
| `device_out(d, v)` / `device_in(d)` | raw `COMM` to any device (`__builtin_out`, `__builtin_in`) |
| `DISK_SEEK_DEVICE`, `DISK_DATA_DEVICE` | the disk (simulator only, `cc run --disk FILE`): `device_out(DISK_SEEK_DEVICE, n)` goes to word n, `device_in(DISK_SEEK_DEVICE)` is the size in words (0: no disk); `device_out`/`device_in` on `DISK_DATA_DEVICE` write/read a word and move on to the next |
| `halt()` | stops the CPU (`__builtin_trap()`) |

**Inline assembly:** `asm("text");` (also `__asm__`) puts its text, one
instruction per line, into the output. Inside a function the compiler keeps
its variables across it (as across a call), so the text may change any
register; it can't name C variables. At file scope it adds assembly to the
file, for example a whole function with its label. Only this basic form of
`asm` is supported.

`<gfx.h>`: drawing on the 128×128 RGB screen (devices `0x6C`/`0x6D`, see
the header for the wiring). Colours are RGB565 (`GFX_RGB(r, g, b)` from
0–255 parts, `GFX_RED`, `GFX_WHITE`, ...); everything is clipped to the
screen, which can't be read back.

| | |
| --- | --- |
| `gfx_clear()`, `gfx_fill(c)` | all black (one reset pulse), all one colour |
| `gfx_pixel(x, y, c)` | one pixel |
| `gfx_hline(x, y, w, c)`, `gfx_vline(x, y, h, c)` | lines across and down |
| `gfx_line(x0, y0, x1, y1, c)` | any line (Bresenham) |
| `gfx_rect`, `gfx_fill_rect(x, y, w, h, c)` | outline / filled rectangle |
| `gfx_circle`, `gfx_fill_circle(cx, cy, r, c)` | outline / filled circle |
| `gfx_char(x, y, ch, fg, bg)` | a 5×7 character in a 6×8 cell (`bg` = `GFX_NONE`: transparent); returns the next x |
| `gfx_text(x, y, s, fg, bg)` | a string, `\n` goes to the next row under x; returns the x after it |
| `gfx_bitmap(x, y, w, h, pixels)` | `w*h` colours row by row, `GFX_NONE` ones skipped |
| `gfx_image(x, y, img)` | a compressed picture, top-left corner at (x, y); returns 0, or -1 if `img` isn't one. `GFX_IMAGE_WIDTH(img)`, `GFX_IMAGE_HEIGHT(img)`: its size |

Pictures: `python compiler/src/img picture.png` writes `picture.h` next to
the PNG, holding `static const unsigned int picture[]` (in ROM once
compiled), so a program can do

```c
#include <gfx.h>
#include "picture.h"
...
    gfx_image(0, 0, picture);
```

The picture is stored with a palette of up to 256 colours and runs of
pixels copied from a neighbour: about 10–60 times smaller than one word per
pixel (a 128×128 picture: 270–1800 words instead of 16 384), and never more
than the bits a palette index needs (black and white: 32 pixels a word, as
for a dithered photo, where runs don't help). Pictures with
more colours are reduced (`--colors N` for fewer and smaller, `--dither`);
bigger ones are shrunk to fit the screen (`--size WxH` to choose);
transparent pixels (PNG alpha) are left out when drawing. At most 256
pixels wide. Drawing costs 32–50 instructions a pixel. More in TECHNICAL.md
7.4; see `compiler/examples/c/image_demo.c`.

`cc run --screen out.png` saves the screen after the run; the simulator
window shows it in its "RGB screen" tab.

Builtins: `__builtin_va_start()`, `__builtin_offsetof(type, member)` (used
by `<stdarg.h>` and `<stddef.h>`), `__builtin_expect(e, c)`,
`__builtin_trap()` and `__builtin_unreachable()` (both halt),
`__builtin_out(device, value)`, `__builtin_in(device)`.


## 7. The C library

Headers: `assert.h`, `cpu.h`, `ctype.h`, `dirent.h`, `errno.h`, `float.h`,
`gfx.h`, `inttypes.h`, `iso646.h`, `limits.h`, `locale.h`, `math.h`,
`setjmp.h`, `signal.h`, `stdalign.h`, `stdarg.h`, `stdbool.h`, `stddef.h`,
`stdint.h`, `stdio.h`, `stdlib.h`, `stdnoreturn.h`, `string.h`, `sys/stat.h`, `sys/statvfs.h`,
`time.h`, `unistd.h`.

Only the library files a program uses are linked in, and a program may
define its own function with a library name (it is used instead).

**stdio.h**

* Output: `printf`, `fprintf`, `sprintf`, `snprintf`, `vprintf` and the
  other `v` forms, `puts`, `putchar`, `fputs`, `fputc`/`putc`, `fwrite`.
  `stdout` and `stderr` both go to the display (`'\f'` clears it). `printf` supports
  `%d %i %u %o %x %X %c %s %p %f %F %e %E %g %G %n %%` with flags, width and
  precision; length modifiers are accepted and change nothing. Floats are
  printed exactly (the decimal digits of the float's exact value, rounded
  to nearest with ties to even), so `printf("%.2f", x)` gives the same
  digits as glibc for the same float.
* Input: `getchar`, `fgetc`/`getc`, `ungetc`, `fgets`, `fread`, `scanf`,
  `sscanf`, `vscanf`, `vsscanf`, `fscanf`, `vfscanf`. The keyboard is read a line at
  a time, like a terminal: keys are shown as they are typed, backspace
  removes the last one, and the program gets the line after Enter.
  **Ctrl-D** (`0x04`) at the start of a line is end of file. `scanf`
  supports `%d %i %u %o %x %c %s %[...] %f %e %g %n` with `*` and widths.
* **Files** are on the disk (simulator only: `cc run --disk FILE` or the
  window's `disk` button, on an image made with `python compiler/src/disk
  format FILE`; TECHNICAL §7.6 has the TFS1 format). `fopen` (modes `r w a`,
  `+`, `b`), `fclose`, `fflush`, `fseek`/`ftell`/`rewind` (`SEEK_SET`,
  `SEEK_CUR`, `SEEK_END`), `remove` (files and empty directories),
  `rename` (also into another directory; fails if the new name exists),
  and every function above on a `FILE *`. A **text** file (no `b`) holds 4
  chars a word, so only the low 8 bits of a char are kept and the image
  reads as plain text on the PC; a **binary** file (`b`) holds one whole
  word per char, so `fgetc` can return a word equal to `EOF` (`feof` tells
  them apart; `fread` already does). Which kind a file is is fixed when it
  is created (or emptied by `w`). Paths start at the root (`/a/b`) or at
  the current directory; names are 1-127 chars, no `/`, spaces or control
  characters. At most 8 files are open at once; open files are saved by
  `fclose`, `fflush`, `exit` and the end of `main`. Without a formatted
  disk `fopen` returns `NULL` with `errno` `ENODEV`.

**unistd.h, dirent.h:** `chdir`, `getcwd`, `mkdir(path, ...)` (a mode is
ignored; POSIX puts `mkdir` in `sys/stat.h`), `rmdir` (empty directories);
`opendir`, `readdir` (`d_name`, `d_type` `DT_DIR`/`DT_REG`, and `d_size`, not
standard: chars for a text file, words otherwise; `.` and `..` aren't
listed), `closedir`, at most 4 open. Errors set `errno`: `ENOENT`,
`EEXIST`, `ENOTDIR`, `EISDIR`, `ENOTEMPTY`, `ENOSPC`, `ENODEV`, `EMFILE`,
`ENAMETOOLONG`, `EINVAL`, `EBUSY` (the root), with Linux's numbers;
`strerror` and `perror` print them.

**sys/stat.h:** `stat(path, &st)` gives `st_mode` (`S_ISDIR`, `S_ISREG`, and
the non-standard `S_ISTEXT`: a text file, packed 4 chars a word, as opposed to
a binary one), `st_size` (chars for a text file, words for a binary one, the
words of the entries for a directory), `st_ino` (the first block), `st_blocks`,
`st_nlink` (1) and `st_blksize` (256). No times, owners or permissions.

**sys/statvfs.h:** `statvfs(path, &s)` gives the disk's size and free
space in blocks of `f_bsize` (256) chars: `f_blocks`, `f_bfree` (=
`f_bavail`), `f_namemax` (127); `f_files` and friends are 0. It reads the
whole FAT (14 instructions a block, 0.9 million on a 64 MB disk).

**unistd.h: `spawnv(path, argv)`** runs the program in the file `path` (made
with `cc build --exe`) with `argv[0]`, `argv[1]`, ... up to a `NULL`, waits
for it and returns its exit status (like DOS's `spawnv(P_WAIT, ...)`), or
-1 with `errno` set when it can't be loaded: `ENOENT`, `EISDIR`, or
`ENOEXEC` (not a program). It starts in the current directory. Close the
files you have open first: the caller's open `FILE`s don't see the
program's changes. A `--exe` program can't call `spawnv` (the build
refuses). `os/shell.c` (TECHNICAL §11) is a shell built on it.

**stdlib.h:** `malloc`, `calloc`, `realloc`, `free` (first fit, from
`_end` to the end of RAM, or to `0x1100000` with `spawnv`); `exit`, `atexit`, `_Exit`, `abort`; `abs`,
`labs`, `div`, `ldiv`; `atoi`, `atol`, `atof`, `strtol`, `strtoul`, `strtod`,
`strtof`; `rand` (0..32767, the generator from the C standard's example, so
not the same numbers as glibc), `srand`; `qsort`, `bsearch`; `getenv`
(always `NULL`), `system` (fails).

**string.h:** `memcpy`, `memmove`, `memset`, `memcmp`, `memchr`, `strlen`,
`strnlen`, `strcpy`, `strncpy`, `strcat`, `strncat`, `strcmp`, `strncmp`,
`strcoll`, `strxfrm`, `strchr`, `strrchr`, `strspn`, `strcspn`, `strpbrk`,
`strstr`, `strtok`, `strerror`, `strdup`. A `size_t` count is in words.

**ctype.h:** the `is...` classes and `toupper`/`tolower`, for ASCII.

**math.h:** `fabs`, `floor`, `ceil`, `round`, `trunc`, `rint`, `fmod`,
`remainder`, `modf`, `frexp`, `ldexp`, `fmin`, `fmax`, `copysign`, `sqrt`,
`cbrt`, `hypot`, `exp`, `exp2`, `expm1`, `log`, `log2`, `log10`, `log1p`,
`pow`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `sinh`,
`cosh`, `tanh`, and more; `isnan`, `isinf`, `isfinite`, `signbit`,
`fpclassify`; `M_PI` and friends; the `f` and `l` names (`sinf`) are the
same functions. `sqrt`, `fmod` and the rounding functions are exact;
`exp`, `log` and the trigonometric functions are within 1-2 units in the
last place (`sin`, `cos`, `tan` for any argument); `pow` is exact for an
integer exponent and a few units off otherwise.

**Others:** `assert` (prints the failed condition and aborts), `errno`,
`setjmp`/`longjmp`, `signal`/`raise` (a handler runs only for `raise`),
`setlocale` (the "C" locale), `clock()` (milliseconds since reset, from
the timer at device `0x7C`; `CLOCKS_PER_SEC` is 1000) and `time` (returns
-1: there is no calendar).


## 8. Speed

On the circuit every instruction counts (about 160 a second). The compiler:

* keeps the most-used scalar local variables in registers (R6-R12), and
  saves them around a call only when they are needed after it
* keeps the rest of the locals in the stack frame, reached with
  `STK GET`/`STK SET`
* cleans up the generated code (repeated loads of a constant, needless
  copies, `TEST`s whose flags are already set, jumps to the next line)

Things that help: use local variables for loop counters and pointers (not
globals, not variables whose address is taken); avoid `printf` in loops
(`putchar`/`puts` are much cheaper); prefer `int` to `float` when you can.
A call costs about 20-30 instructions. Unsigned division by a variable
calls a helper; signed division is one instruction.


## 9. Checking the compiler

```
python compiler/src/cc/selftest.py           # part of python run.py test
python compiler/src/cc/tests/difftest.py     # every test program against gcc (needs gcc)
python compiler/src/cc/tests/difftest.py --update   # rewrite the .expected files
python compiler/src/cc/tests/fuzz.py --count 50     # random programs, gcc against tiny C (needs gcc)
```

`compiler/examples/c/circuit_test.c` checks the compiler's tricky code
paths on the circuit itself: every line must say `ok`.
