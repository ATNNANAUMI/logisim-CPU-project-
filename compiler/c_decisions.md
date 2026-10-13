# Tiny C: decisions, guesses and open questions

Written while building the C compiler (October 2026), for review. Each
decision says why; each guess says what it rests on and how to check it.
The language itself is described in [`c_language.md`](c_language.md).

## Decisions

### The machine

1. **`CHAR_BIT` is 32: char, short, int, long and pointers are all one
   word.** The CPU addresses words; packing four chars per word would make
   every character access a shift-and-mask sequence and would not match the
   assembly library's one-character-per-word strings. C allows it (some DSPs
   do the same). Cost: code that assumes 8-bit chars or `sizeof(int) == 4`
   behaves differently.
2. **`double` and `long double` are the 32-bit float.** The CPU has only a
   float32 unit; a software 64-bit double would be very slow and large.
   `DBL_DIG` is therefore 6, below the 10 the C standard asks for. Test
   programs use `float` and `f` constants to stay comparable with gcc.
3. **No `long long`: it is an error**, not a silent 32-bit type, so a
   program that needs 64 bits fails loudly. Likewise `int8_t`, `int16_t`,
   `int64_t` (and unsigned) are left out of `<stdint.h>`.
4. **`unsigned char` and `unsigned short` promote to `unsigned int`**, as
   the C rules say when `int` can't hold all their values.
5. **char is signed**, like gcc on x86.

### Code generation

6. **The calling convention is the assembly library's** (arguments pushed
   first to last, `CALL f, N`, result in R0, every register may change), so
   C and assembly call each other with no glue.
7. **Variadic calls push the variadic arguments first, then the fixed
   ones, then the count of variadic words.** The fixed parameters then sit
   where a normal function expects them, and `va_start` computes the rest.
8. **Struct results come back through a hidden first argument** pointing
   at a buffer in the caller's frame.
9. **Registers: R1-R12 for expression temporaries and local variables, R13
   for frame indexes and addresses, R14/R15 left to CALL/RET/RESTORE and the
   runtime helpers.** Up to 7 locals live in registers (R6-R12), chosen by
   use counts weighted by loop depth against the cost of saving them around
   the calls where they are still needed (2 instructions per use saved, 4
   per call where they must be kept, 3 to load a parameter). If an
   expression runs out of temporaries, the function is compiled again with
   fewer register variables.
10. **A register variable changed inside a call's own arguments** (`f(i++)`)
    is written to its stack slot just before the call and read back after,
    because SAVE/RESTORE around the whole call would undo the change.
11. **Locals are reached with `STK GET/SET` (EBP-relative)**, so no frame
    pointer register is needed. A function that takes the address of a
    local computes `FP = 0x10000 + EBP` once, reading EBP with
    `STK CALL / STK GET 0 / STK RET` (measured on the circuit, `diag12`).
12. **Frames bigger than 15 words are reserved by setting ESP directly**
    with two `STK RET`s (also measured in `diag12`); smaller ones with
    `STK PUSH`es.
13. **Unsigned comparisons use `SUB` and the carry flag** (C = borrow,
    measured in `diag12`/`diag13`), signed ones `CMP` and the A flag, float
    ones `FCMP` and N/Z only (so NaN compares false; measured in `diag14`).
14. **Shifts:** `x << k` is `MULT` by `2^k`; logical `x >> k` is `SHR` then
    `DIV` by `2^(k-1)` (never dividing by `2^31`); arithmetic `>>` flips
    negative numbers with `NOT` around a logical shift. Shifts by a variable
    read `2^n` from a 32-word table (`_pow2` in `runtime.asm`).
15. **Unsigned division** calls `_udiv`/`_umod` in `runtime.asm` through a
    light call (return address in R14), which uses the signed `DIV` with at
    most one correction step: no loop.
16. **Dense switches** (5 or more cases, at most 3 slots per case) use a
    jump table; others a compare chain.
17. **C names keep their name as assembly labels**; names the assembler
    rejects get a `_X` prefix. Labels the compiler makes start with `_` and a
    capital letter (reserved in C).

18. **Calls are written out instead of using `CALL`/`RET`**: `RJMP` to the
    function, no R0-keeping copies when the result is unused, a 3-instruction
    return from `void` functions. Same stack layout and registers, so
    assembly code still calls C and C still calls assembly.

### Data and start-up

19. **String literals and `const` global data live in ROM.** Writes to
    them are ignored (undefined behaviour in C anyway). Saves RAM and the
    copy at start-up.
20. **Initialised globals: starting values in ROM, copied to RAM by a
    per-file `_init_` routine that also clears the other globals.** The
    start-up code (crt0, generated per build) calls them all, so a reset
    without clearing RAM restarts the program correctly.
21. **`main` is called as `main(0, {NULL})`; its result goes to `exit`,
    which halts with the status in R0.** HALT is in a loop so RESUME stops
    again instead of running into whatever follows.
22. **malloc's heap is everything from `_end` (a label the build puts after
    all RAM data) to the end of RAM.** One-word headers, first fit, free
    neighbours joined during the search.

### The library

23. **The C library is written in C (plus `runtime.asm` and
    `setjmp.asm`), and `stdlib.asm` is not linked into C programs.**
    `stdlib.asm` exports names like `min`, `max` and `print_int`, which
    could clash with a program's own functions (its integer `pow` was renamed
    `ipow` on 2026-10-11, so at least that one can't be mistaken for C's); a valid C
    program must be able to use those names.
24. **Library files are linked only when needed**, like a static library,
    and a program's own definition of a library function wins. Within a
    library file, only the functions and data the program uses are linked
    (the linker's `--lib` mode; the compiler starts a `.part` at every
    function and data object). The library
    is compiled once and cached in `compiler/ROM/libc/` (rebuilt when the
    compiler or the library changes).
25. **stdin is line-buffered with echo and backspace editing; Ctrl-D at
    the start of a line is end of file** - like a terminal, so programs that
    read with `scanf` or `getchar` behave as on a PC.
26. **printf prints floats exactly** (exact decimal expansion of the
    float, ties to even), so its digits match glibc's for the same float.
    This costs a few thousand instructions per float.
27. **`rand` is the C standard's example generator**, not glibc's: tests
    can't compare random numbers with gcc anyway, and this one is small.
28. **`time()` and `clock()` return -1** (no clock); `getenv` returns NULL;
    `fopen` fails; `signal` handlers run only for `raise`.
29. **math.h:** `sqrt`, `fmod` and the rounding functions are exact; the
    others aim for 1-2 units in the last place; `sin`/`cos`/`tan` use
    Payne-Hanek reduction above 100 so any argument works.

### Process

30. **Tests compare with gcc.** Every program in `compiler/src/cc/tests/`
    must print exactly what gcc's build prints; the `.expected` files come
    from gcc. Programs avoid undefined behaviour and type sizes.
31. **Accepted from GNU C**: case ranges, `typeof`, `, ## __VA_ARGS__`,
    `asm("...")`, `__attribute__` (ignored), binary constants. Not accepted:
    statement expressions, `?:` with the middle part left out.
32. **After an error the parser skips to the next statement or declaration** and carries on, up to 20 errors; the code generator only runs when there were none. Errors after the first can be knock-on effects of it, as with gcc.

## Measured on the circuit while doing this

* `diag12`/`diag13`: the carry flag is a *borrow* for `SUB`, and `CMP`,
  `--`, `NEG`, `MULT` never set it. The docs said otherwise; the simulator
  was changed to match.
* `diag12`: reading and setting ESP/EBP with `STK CALL`/`STK RET` works,
  stack slot `i` is RAM `0x10000 + i`, `FCMP`'s A flag is a float compare.
* `diag14`/`diag15`: float special cases (division by zero, NaN, INT out of
  range); see `TECHNICAL.md` section 8.
* `compiler/examples/c/circuit_test.c` passes on the circuit, and eight of
  the test programs print exactly gcc's output there (2026-10-11).
* `diag16`/`diag17` (2026-10-13): N and Z after `DIV`, `MOD` and `NOT`, and
  after `MULT`/`SHL` with a negative result, describe R0. Floats round to
  nearest, ties to even.
* `diag16`/`diag17` (2026-10-13): **the circuit's `NOT` inverts RA, not
  RB.** C's `~` on a register variable goes wrong on the circuit:
  `printf("%08x %08x", ~a, ~b)` printed `fffffffc 00000003` instead of
  gcc's `f0f0f0ed ff00ff03`. The compiler's other `NOT`s (in `>>` of
  negative numbers) always run on a value already in R0.

## Guesses (not measured)

* **N and Z after `OR` and `XOR`** are taken to describe R0, as the ISA
  says (the peephole pass drops a `TEST R0` after them); every other op it
  does that for is measured (`diag13`, `diag16`).
* **Performance numbers** (about 160 instructions a second on the circuit,
  200 000 in the simulator) are from single runs on this machine.
* **The cost model of the register allocator** (2/4/3 instructions) is an
  estimate; it was tuned only on the test programs.

## Open questions for you

* 64-bit `long long` in software is possible (pairs of words, with the
  carry flag now known); it was left out as large and slow. Worth doing?
* `project_files/` (your notes, not in git) still says the compiler isn't
  started and describes the old carry flag.
