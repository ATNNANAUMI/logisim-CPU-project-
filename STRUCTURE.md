# Project structure (context for Claude)

Project: **logisim-CPU-project**. A 32-bit CPU built from logic gates in
Logisim-evolution 4.1.0, plus its toolchain: an assembler and linker written
in Python, an assembly standard library, a C compiler ("tiny C") with its
own C library, and a Python simulator that runs the same ROM images as the
circuit. Python 3.10+, standard library only (`tkinter` for the simulator
window). Detailed docs are in `TECHNICAL.md`. The assembly language
reference is `compiler/assembly_syntax.md`, the C one `compiler/c_language.md`.

## Pipeline

```
.c ──(C compiler)──► .asm
                       │
.asm ──(assembler)──► .obj (JSON) ──(linker)──► .rom (Logisim "v2.0 raw")
                                    ▲             ├──► cpu_sim/src/main.py      (Python simulator)
       crt0 + C library (.obj) ─────┘             └──► logisim/run_rom.py       (real circuit, headless)
```

## Directory tree

```
logisim-CPU-project-/
├── README.md                 short overview + quick start
├── TECHNICAL.md              full technical reference (ISA, circuit, sim, asm, stdlib, open questions, outdated list)
├── STRUCTURE.md              this file
├── run.py                    single entry point: `python run.py [asm|sim|build|test|img] ...` (menu if no args)
├── check_docs.py             checks the docs against the repo (paths exist, examples and TWEAKS listed); part of `run.py test`
│
├── logisim/
│   ├── CPU.circ              THE CIRCUIT. Top-level circuit = "PC" (RGB Video fed by RGB_Display)
│   ├── run_rom.py            patches a .rom into the ROM inside subcircuit "RAM", runs Logisim headless, prints TTY
│   └── cpu datas/            old notes: stack micro-steps, personal TODO
│
├── compiler/
│   ├── assembly_syntax.md    CURRENT assembly language reference
│   ├── c_language.md         the C language (tiny C): types, what's supported, library, mixing with asm
│   ├── c_decisions.md        why the C compiler is the way it is; guesses; open questions
│   ├── src/asm/              assembler + linker (run as `python compiler/src/asm <cmd>`)
│   │   ├── __main__.py       CLI: assemble | link | build  (-o out, --map); writes to compiler/ROM/; reports errors from every input
│   │   ├── parser.py         text → pieces: comments, labels, operands, strings, value expressions
│   │   ├── encoding.py       ISA tables (SYSTEM_OPS, ALU_OPS, COMM_OPS, STK_OPS, FLAGS), word(), jump_offset()
│   │   ├── assembler.py      two-pass assembler: one .asm → ObjectFile (+ relocations, pseudo-op expansion)
│   │   ├── objfile.py        ObjectFile / Reloc (abs|rel, rom_only for CALL targets), saved as JSON (.obj)
│   │   ├── linker.py         .obj files → ROM image; --lib: only the needed parts; checks externs/RAM calls; format_raw(), format_map()
│   │   ├── errors.py         AsmError (file:line: message), AsmErrors (batch)
│   │   ├── selftest.py       20 checks (incl. building every compiler/examples program)
│   │   └── asm_grammar.py    generates railroad-diagram HTML of the grammar (needs railroad-diagrams)
│   ├── src/cc/               C compiler (run as `python compiler/src/cc <cmd>`); imports src/asm's modules
│   │   ├── __main__.py       CLI: compile | build | run  (-o, --map, -I, -D, -w, --no-libc; run: --keys --steps --stats --trace)
│   │   ├── lexer.py, preprocessor.py   tokens; #include/#define/#if, macro expansion (hide sets)
│   │   ├── typesys.py        types (sizes in words), promotions, compatibility
│   │   ├── nodes.py          syntax tree Node, Obj (variable/function)
│   │   ├── cparser.py        parser + type checker (chibicc style), initializers, constant folding
│   │   ├── regalloc.py       which locals get registers; which a call must keep
│   │   ├── codegen.py        tree → assembly (Val/Addr model, calls, frames, switch tables)
│   │   ├── peephole.py       clean-ups per function
│   │   ├── driver.py         build pipeline: compile, library cache/selection, crt0, link, run in simulator
│   │   ├── cerror.py         CError (file:line:col: error: ...)
│   │   ├── selftest.py       15 checks (incl. every tests/ program against gcc's output)
│   │   └── tests/            *.c + *.expected (gcc's output); difftest.py compares with gcc (--update);
│   │                         fuzz.py: random programs, gcc vs tiny C
│   ├── src/img/              PNG -> compressed image for gfx_image() (run as `python compiler/src/img pic.png`)
│   │   ├── __main__.py       CLI: writes pic.h (static const array) next to the PNG; --size --colors --dither --preview
│   │   ├── imagefile.py      PNG reader (every colour type and depth, not interlaced) and writer, area-average resize
│   │   ├── palette.py        RGB565 (truncated like GFX_RGB), median cut + k-means (fit_colors), Floyd-Steinberg
│   │   ├── video.py          a video (ffmpeg) or PNG folder -> clip.h of frames for video_player.c: one shared
│   │   │                     palette, frame 0 whole, later frames only the changed pixels (rest transparent)
│   │   ├── codec.py          THE FORMAT (docstring): palette + bit stream of literals and runs
│   │   │                     (previous pixel, above, above-left, above-right; gamma lengths), or packed
│   │   │                     indices when that is smaller (b bits a pixel); encode, decode
│   │   └── selftest.py       10 checks (incl. gfx_image() on the simulator against codec.decode, video_player.c)
│   ├── libc/                 the C library: include/*.h, *.c (stdio, string, stdlib, malloc, math, gfx, gfx_image, ...),
│   │                         local.h (library-internal), runtime.asm (_pow2, _udiv, _umod, _Exit), setjmp.asm
│   ├── examples/
│   │   ├── programs/         hello, print_a-z, count_0-9, sum_1-10, abs_value, stack_reverse, echo (no stdlib); guess, untested (with stdlib)
│   │   ├── stdlib/stdlib.asm             standard library (I/O, strings, memory, math, conversion)
│   │   ├── stdlib/stdlib_demo.asm        uses every stdlib function except input
│   │   ├── stdlib/stdlib_input_demo.asm  read_line / read_int / read_float / read_char
│   │   ├── stdlib/stdlib_more_demo.asm   the functions added 2026-10-03 (no typing, no hex display)
│   │   ├── two_files/main.asm, lib.asm   multi-file linking example
│   │   ├── c/                C examples: hello, primes, structs, guess (input), gfx_demo (RGB screen); circuit_test (self-checking, for the circuit)
│   │   │                     image_demo (gfx_image) with c/images/: mandelbrot, smiley (.png + the .h made from it)
│   │   │                     video_player (plays a video.py .h on time with clock()) with c/videos/demo (.mp4 + .h)
│   │   │                     game_of_life (64x64 torus, 7 scenes of well-known patterns, checks itself; keys 1-7 n r space s)
│   │   └── tests/            io_test (keyboard), diag10 (INT below 1), diag11 (INT, STK GET/SET edge cases),
│   │                         diag12 (ESP/EBP tricks, flags, MULT, DIV), diag13 (carry flag),
│   │                         diag14, diag15 (float division by zero, NaN, INT out of range),
│   │                         diag16, diag17 (STK SET/GET wrap, NOT, MOD by 0, float opcodes, rounding),
│   │                         diag18 (flags after OR/XOR, NOT as assembled now)
│   └── ROM/                  build output (.obj/.rom/.map/.asm), git-ignored, created on first build;
│                             ROM/libc/ caches the compiled C library
│
└── cpu_sim/
    ├── src/                  simulator (modules import each other by plain name: run as scripts)
    │   ├── config.py         sizes, device addresses, TWEAKS (behaviour switches, marked confirmed/guess)
    │   ├── isa.py            decode(), disassemble(), opcode tables
    │   ├── alu.py            int_op(), float_op() → (R0 value, flags)
    │   ├── memory.py         ROM/RAM banks, v2.0 raw loader
    │   ├── devices.py        Display (0x5C), Keyboard (0xF0, empty reads 0), Timer (ms since reset, 0x7C), Video (RGB 0x6C, clear 0x6D), DeviceBus (+ hex display value, 0x3C)
    │   ├── cpu.py            CPU: step() (traced), run() (fast loop), reset(), stack ops, COMM
    │   ├── gui.py            Tk window (registers, ROM/RAM panes, C source tab + line stepping, display, live keyboard, breakpoints, speed)
    │   ├── debuginfo.py      reads the .map (labels, C lines from .loc); step_line / step_out
    │   ├── main.py           CLI: `python cpu_sim/src/main.py [rom] [--headless --steps N --trace --keys TEXT --ram IMG --screen F.png]`
    │   └── selftest.py       22 checks
```

## Circuit hierarchy (`logisim/CPU.circ`)

```
PC (top)                  has the output pin `halt` that ends headless runs at HALT
├── CPU
│   ├── CONTROL_SECTION   decoder/sequencer (gates); uses CLOCK (clk, clk_s, clk_e via "buffer" delay) and stepper (4-bit)
│   ├── CPU_REG           16 × REGISTER (32-bit), one-hot set/enable selects
│   ├── ALU → FPU         integer ops + float unit (hand-built IEEE-754 path + Logisim FP components)
│   ├── ACC, TMP          ALU latches
│   ├── FLAG_REG          C A N Z
│   ├── IAR               17-bit counter (T flip-flops); the toolchain now wants 25 (TECHNICAL 2.4)
│   └── INTRUCTION_REGISTER  16-bit
├── RAM                   memory system: MAR(17), ROM 64K×32 (PROGRAM LIVES HERE), RAM 64K×32, ESP/EBP (14-bit); still 16-bit banks
├── display               text TTY at 0x5C
├── NUMBER_DISPLAY        8 hex digits at 0x3C
├── KEYBOARD              keyboard at 0xF0
└── RGB_Display           RGB Video at 0x6C (x, y, colour from one word; Video's enable tied to 1). No 0x6D clear yet
Unused subcircuits: ROM, program_loader, sign_controller, teste
```

The design follows the "But How Do It Know?" style: a single bus,
`*_S` = set (latch from the bus), `*_E` = enable (drive the bus).

## ISA cheat sheet

* 32-bit words. 16 registers `R0`–`R15`. 25-bit addresses, 16M words per
  bank: bit 24 = RAM. ROM `0x0000000–0x0FFFFFF` (read-only), stack = RAM
  `0x1000000–0x1003FFF`, linker data from `0x1004000`, end of RAM
  `0x1FFFFFF`. The memory map lives in `linker.py` and `config.py` (and
  `malloc.c`/`stdlib.asm` write down the end of RAM). **The circuit still
  has the 16-bit map** (bit 16 = RAM, 64K words per bank) and can't run
  these programs until it is widened (TECHNICAL 2.4); `run_rom.py` refuses.
* Instruction: `bit14 IMM | bit13 FLOAT | bit12 ALU | 11..8 opcode | 7..4 RA | 3..0 RB`.
  Groups: `0x0` system, `0x1` int ALU, `0x3` float ALU, `0x5`/`0x7` = with an
  immediate (the next word).
* **Every ALU result goes to R0** and every ALU op rewrites all flags.
  `CMP`/`FCMP` write 0 to R0 and set the flags from `RA − RB`.
* Confirmed on the circuit: the `A` flag (`RA > RB`) is signed, `SHR` is
  logical, `DIV` truncates and `MOD` keeps the dividend's sign, `INT`
  (float→int) truncates toward zero, ESP/EBP wrap at 14 bits, the `A` flag
  after `FCMP` is a float compare. `DIV` by 0 gives the dividend, `MOD` by 0
  gives 0 (`diag16`/`diag17`).
* `NOT` inverts RB on the circuit since it was rewired on 2026-10-15
  (`diag17`); before, it inverted RA. The assembler still writes `NOT Rx` with
  x in both fields (`0x16xx`), which gives `~Rx` either way; `A` after it is 0.
* Carry flag (measured, `diag12`/`diag13`): `ADD`/`++` carry out, `SUB` sets C
  on a **borrow** (`RA < RB` unsigned), `SHL`/`SHR` the bit shifted out;
  `CMP`, `--`, `NEG`, `MULT` never set it.
* Floats (measured, `diag14`/`diag15`): IEEE-754 (`0/0` = NaN, `1/-0` = -inf,
  subnormals kept); `INT` = Java's `(long)` cast, low 32 bits (`INT(3e9)` wraps,
  `INT(+inf)` = `FFFFFFFF`, `INT(NaN)` = 0); `FCMP` with a NaN clears all flags.
  Rounding is to nearest, ties to even (`diag16`). Float opcode 4 (no
  mnemonic) writes `RB × 2`; 8/9/A/E write 0; 5/B/C give `FFFFFFFF` with N and Z
  both on (an undriven bus?), which the simulator doesn't copy.
* System ops: NOP LD ST DATA RJMP RJF RJNF CLF COMM ADDR JMRB STK ALD AST CPY HALT.
  `CPY RA, RB` copies RA → RB. `ALD`/`AST` use R0 with `mem[RA+RB]`.
* Jumps are relative to the **address of the offset word**. `RJF` = any
  listed flag on, `RJNF` = any listed flag off. Mask: C=8 A=4 N=2 Z=1.
* Stack grows up. `STK PUSH/POP` use R0. `STK CALL/RET` only move the frame
  (no jump). `STK SET/GET, RB` = `stack[EBP+RB]`; that sum wraps at the RAM's
  address width, across the whole RAM (EBP=0, RB=-1 → last RAM word
  `0x1FFFFFF`; measured at 16 bits on the circuit, `diag11`/`diag16`).
* `COMM INDATA|INADDR|OUTDATA|OUTADDR, RB`. Display `0x5C`, number display
  `0x3C`, keyboard `0xF0` (empty reads 0). RGB screen: `0x6C` one pixel per
  word (x bits 31–24, y 23–16, RGB565 15–0), `0x6D` clears (simulator only:
  not built on the circuit yet). Pictures: `compiler/src/img` compresses
  a PNG (palette + runs, about 10–60× smaller than a word per pixel),
  `gfx_image()` draws it (32–50 instructions a pixel). Timer (planned, in
  the simulator and C's `clock()`): `0x7C`, `INDATA` = milliseconds since
  reset (real time in the simulator, stopped while the window is paused).
  Videos: `compiler/src/img/video.py` -> frames that `video_player.c` draws
  on time (about 350k instructions a 128×96 frame: pypy3 keeps up at 12 fps).

## Assembler conventions

* Directives: `.rom .ram .global .extern .equ .word .string .space .part .loc`
  (`.loc "file", line`: source line info for the `.map`, written by the C compiler).
  `.ram` allows only labels + `.space`.
* Immediates use `#`: `ADD R1, #5`. Values can be dec, hex, bin, `'c'`, or
  floats (stored as float32 bits), with `+`/`-` and at most one label.
* Pseudo-ops: `CALL label[, n]` (7 or 9+n words, clobbers R0/R15), `RET`
  (6 words, clobbers R14/R15), `SAVE r…` / `RESTORE r…`.
* The linker puts `RJMP start` at address 0. Exactly one file needs
  `.global start`. Every `.extern` must be exported by some file. Calling or
  jumping to a RAM label is an error.
* `--lib FILE`: a library; only the *parts* the program needs are linked.
  Parts start at every `.global` label and at `.part`; a part that can fall
  through keeps the next one. Jumps between parts are relocations.
* Calling convention: push args first→last, `CALL f, N`, result in R0. R0,
  R14, R15 always clobbered; R1–R13 caller-saved. Inside, arg i of N is at
  `STK GET` index `-(N+1)+(i-1)`; the last arg is at -2.
* stdlib: `read_char` doesn't echo; `read_line` echoes and handles backspace.

## C compiler conventions (details: `compiler/c_language.md`)

* Every scalar is one word: `sizeof(char) == sizeof(int) == 1`, `CHAR_BIT`
  is 32; `double` is the 32-bit float; no `long long` (an error). Strings are
  one char per word, like the asm stdlib's.
* Same calling convention as the asm stdlib; C names are asm labels
  (`_X` prefix for names the assembler rejects, like `add`). Variadic calls
  push variadic args first, then fixed ones, then the variadic word count.
* Registers in compiled code: R1-R12 temporaries and register variables,
  R13 scratch, R14/R15 left to CALL/RET/RESTORE and the runtime helpers.
* C programs link the C library (`compiler/libc/`), not `stdlib.asm`; only
  the library files a program needs are linked; a program's own function
  with a library name wins.
* String literals and const globals are in ROM (writes ignored).
  Initialised globals are copied to RAM by per-file `_init_` routines that
  crt0 calls before `main`; malloc's heap runs from `_end` to `0x1FFFFFF`.
* stdin: a line at a time, echoed, backspace edits, Ctrl-D (0x04) = EOF.
* Tests: `compiler/src/cc/tests/*.c` must print exactly gcc's output
  (`.expected`); `difftest.py` checks with gcc.

## Common commands

```
python run.py test
python compiler/src/asm build prog.asm compiler/examples/stdlib/stdlib.asm [--map]   # -> compiler/ROM/prog.rom
python compiler/src/asm build prog.asm --lib compiler/examples/stdlib/stdlib.asm       # only the stdlib functions used
python cpu_sim/src/main.py compiler/ROM/prog.rom                       # GUI
python cpu_sim/src/main.py compiler/ROM/prog.rom --headless --steps 2000000 --keys $'text\n'
python logisim/run_rom.py logisim/CPU.circ compiler/ROM/prog.rom   (jar: $LOGISIM_JAR or the Arch package path)
python compiler/src/cc run prog.c [--keys $'12\n'] [--stats]      # C: build + run in the simulator
python compiler/src/cc build prog.c [more.c x.asm] [-o prog.rom]   # C: -> compiler/ROM/prog.rom (+ prog.asm)
python run.py build prog.c                                          # C or asm: build, then open the simulator
python compiler/src/cc/tests/difftest.py [--update]                # C tests against gcc
python compiler/src/img pic.png [--colors 16] [--size 64x]         # PNG -> pic.h for gfx_image(x, y, pic)
python compiler/src/img/video.py clip.mp4 [--fps 10] [--seconds 5]  # video -> clip.h for video_player.c (needs ffmpeg)
pypy3 compiler/src/cc run compiler/examples/c/video_player.c -I . -D 'VIDEO="clip.h"' --steps 2000000000
```

## Open questions / gotchas

* Float opcodes 5, B and C read back as `FFFFFFFF` with N and Z both on, on
  the circuit; the simulator writes 0. No mnemonic emits them.
* `STK SET/GET` used to wrap at 14 bits in the simulator, but the circuit wraps
  `EBP + RB` across the whole RAM (`diag11.asm`, `diag16.asm`); the simulator now
  matches, and also gives 0 for `MOD` by 0 like the circuit.
* `STK GET/SET/PUSH` misusing RB was a circuit bug, now fixed.
* The carry flag was documented as "set when there is no borrow" for
  `SUB`/`CMP`; the circuit sets it on a borrow for `SUB` and never for `CMP`
  (`diag12.asm`, `diag13.asm`). The simulator now matches the circuit.
* The simulator also gave `0.0/0.0 = +inf`, `1.0/-0.0 = +inf` and `INT(inf) = 0`;
  `diag14.asm`/`diag15.asm` measured the circuit and the simulator now matches.
* Still-unconfirmed behaviours can be switched in `cpu_sim/src/config.py`
  (TWEAKS).
* The C library is compiled once and cached in `compiler/ROM/libc/`; the
  cache key includes the compiler's sources and the headers, so it rebuilds
  itself. Deleting `compiler/ROM/` is always safe.
* The circuit runs about 160 instructions a second: a C program for the
  circuit should avoid `printf` in loops (a float `printf` costs thousands of
  instructions). `compiler/examples/c/circuit_test.c` takes about 15 000.
* Outdated notes: `logisim/cpu datas/` (see TECHNICAL.md §9). The old
  hand-assembled programs were removed on 2026-10-06 (still in git history).
