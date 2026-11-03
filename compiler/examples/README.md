# Examples

Programs to read, build and run. Every file starts with a header that says what it does, how to build it and what it prints. The OS's own programs (`ed`, `grep`, `claude`, ...) are in [`tynix/bin/`](../../tynix/bin/README.md), not here.

## C (`c/`): `python compiler/src/cc run FILE.c`

| folder | files | what they show |
| --- | --- | --- |
| `basics/` | `hello`, `primes`, `structs`, `interrupts` | the smallest program; a sieve and the hex display; structs, `qsort`, `malloc`; timer and keyboard interrupts |
| `games/` | `snake`, `game_of_life`, `guess` | games on the RGB screen and the keyboard |
| `graphics/` | `gfx_demo`, `grapher`, `image_demo`, `qr`, `video_player` (+ `images/`, `videos/`) | the RGB screen: shapes and text, a graphing calculator, compressed pictures, QR codes, video |
| `os/` | `disk_notes`, `echo`, `loader` | programs that use the disk and the OS (`make_disk.py` puts `echo` and `disk_notes` in `/bin`) |
| `tests/` | `circuit_test`, `benchmark`, `sqrt_benchmark` | checks of the compiler's code on the real circuit; speed measurements |

## Assembly (`asm/`): `python compiler/src/asm build FILE.asm [stdlib.asm]`

| folder | files | what they show |
| --- | --- | --- |
| `programs/` | `hello`, `count_0-9`, `print_a-z`, `sum_1-10`, `abs_value`, `stack_reverse`, `echo`, `guess`, `untested` | small programs, simplest first |
| `stdlib/` | `stdlib.asm` (the library) and `stdlib_demo`, `stdlib_input_demo`, `stdlib_more_demo` | the standard library and a demo of its functions |
| `two_files/` | `main`, `lib` | linking two files together |
| `tests/` | `diag10` ... `diag18`, `io_test` | measurements of the real circuit (flags, floats, the stack); results are recorded in the file headers and in TECHNICAL §8 |

`echo`, `hello` and `guess` exist in both languages: the same idea in assembly and in tiny C.
