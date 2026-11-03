# Action plan: the next 20 features

Written 2026-11-03 on branch `os` (at `d1938af`, after Phase 8), from the
ranked list of 100 ideas brainstormed that day. Chosen by rank: 1–7, 10–12,
21, 27, 30, 32, 36, 37, 39, 44, 45, 66. Nothing here is built yet; this file
says what each one would do, how, what it touches, how it is checked, what
follows from it, and whether it is worth it.

Every item follows the repo's rules: standard-library Python, the doc rows in
`CLAUDE.md` ("Keeping the docs in sync"), `python run.py test` green before a
commit, and a vault update after each phase (`os_roadmap.md`, the topic
notes, a "How it works" note when it is an OS part).

Scores are 1–5. **Value** is what it adds to the project (learning, showing
off, making later work easier). **Effort** is 1 for an afternoon, 2 for a
day, 3 for 2–4 days, 4 for a week, and 5 for more.

---

## 0. Summary and order

| # | rank | feature | value | effort | phase | depends on |
|---|---|---|---|---|---|---|
| 1 | 1 | CI on GitHub Actions | 4 | 1 | A | – |
| 2 | – | `machine_view.py`: a shared machine-introspection layer (new, needed by 8–12) | 4 | 2 | A | – |
| 3 | 2 | `<` input redirection in the shell | 3 | 1 | B | – |
| 4 | 66 | Environment variables, `PATH` | 3 | 2 | B | – |
| 5 | 6 | Shell history and tab completion | 4 | 2 | B | – |
| 6 | 3 | Pipes `a \| b` (kernel pipe objects), plus `;` and `&&` | 4 | 3 | B | 3 |
| 7 | 44 | Memory viewer extras | 2 | 1 | C | 2 |
| 8 | 10 | Call-stack viewer | 4 | 2 | C | 2 |
| 9 | 32 | Heap visualiser | 3 | 2 | C | 2 |
| 10 | 45 | Memory map picture | 3 | 2 | C | 2, 9 |
| 11 | 7 | Machine snapshots (save/load state) | 4 | 2 | C | – |
| 12 | 37 | Disassembler that rebuilds labels | 3 | 2 | D | – |
| 13 | 36 | Interactive ISA reference page | 3 | 2 | D | – |
| 14 | 27 | Compiler explorer (how the compiler works) | 4 | 3 | D | – |
| 15 | 21 | Animated datapath, driven by the microcode table | 5 | 4 | D | – |
| 16 | 39 | Mouse device | 3 | 2 | E | – |
| 17 | 4 | BASIC interpreter | 5 | 3 | E | (4, 6 nice to have) |
| 18 | 5 | Raycaster (3D maze) | 5 | 3 | E | – |
| 19 | 11 | CHIP-8 interpreter | 4 | 2 | E | – |
| 20 | 12 | A falling-block puzzle game of our own | 4 | 2 | E | – |
| 21 | 30 | Tutorial series, from gates to the shell | 4 | 3+ | F | 13, 14, 15 |

Phases (each one branch and one PR into `os`, as for Phases 6–8):

* **A. Foundations:** CI first, so every later PR is checked, then
  `machine_view.py`.
* **B. Shell and kernel:** `<`, then environment variables, then history and
  tab completion, then pipes. Each is a small change to `shell.c` and the
  kernel, with the disk self-check's `SHELL_OUTPUT` growing each time.
* **C. Simulator window:** the panels that read the machine's state, all
  through `machine_view.py`.
* **D. Seeing the toolchain and the CPU:** disassembler, ISA page, compiler
  explorer, datapath. The last three become the tutorial's illustrations.
* **E. Devices and programs:** the mouse, then the four programs for `/bin`.
  The programs can be written in any order or in parallel; they don't
  depend on C or D.
* **F. Tutorial:** written alongside, one chapter per finished part.

Total: about 45–60 days of focused work at the effort scale above.
Phases B and E can overlap with C and D.

---

## A. Foundations

### 1. CI on GitHub Actions (rank 1)

**What it does.** On every push and pull request to `main` and `os`, it
runs `python run.py test` (the five self-check suites and `check_docs.py`)
on Ubuntu, and fails the PR if anything breaks. A second job runs the
C-against-gcc checks: `difftest.py` on every test program, and `fuzz.py
--count 200` with a fixed seed plus one random seed printed in the log.

**Facts measured today.** `python run.py test` takes **1 min 41 s** under
CPython 3.13 here (22 + 51 + 18 + 10 + 23 checks, plus 3 doc checks). It
needs no tkinter (`selftest.py` skips the GUI check on `ImportError`), no
network (the Claude device uses `FakeBackend`), and no Logisim or javac.
ffmpeg is optional (`img` selftest notes its absence).

**Plan.**
1. `.github/workflows/test.yml`: `ubuntu-latest` on Python 3.10 (the
   documented minimum) and 3.13. Cache `compiler/ROM/libc/` keyed on a hash
   of `compiler/libc/**`.
2. A second job, `gcc`: `apt install gcc` (already on the runner), then
   `difftest.py` and `fuzz.py --count 200 --seed 1`.
3. An optional third job, `pypy`: `bench.py --repeat 1` under pypy3, which
   checks the end-state digests and keeps the speed in the log (no
   threshold, since runners vary).
4. Upload `compiler/ROM/` as an artifact when a job fails, for debugging.
5. Add a status badge to the README.

**Checks.** The workflow itself. Push a branch with a deliberately broken
`.expected` file and confirm the job turns red (then drop that commit).

**Docs.** README (badge, one line in "Quick start"), TECHNICAL §7.3 (how
the checks run in CI), STRUCTURE tree (`.github/`).

**Risks.** Only that a check may depend on timing (the timer device follows
the real clock). If one is flaky on slow runners, fix the check; don't
skip it.

**Follow-ups.** A nightly job with a longer fuzz run. Once the circuit is
widened, `run_rom.py` checks in CI with the Logisim jar downloaded and
cached.

**Verdict: do it first.** It is an afternoon, and it guards everything
after it.

### 2. `machine_view.py`: one place that understands the running machine (new)

This item is not in the list of 100, but items 7–11 all need it, so it is
built once, first.

**What it does.** `cpu_sim/src/machine_view.py` (not `inspect.py`: the simulator imports its
sibling modules by plain name, and that would shadow Python's own `inspect`)
gives the window and the tools:
* `labels(addr)` and `symbol(name)`: from the `.map` (already parsed by
  `debuginfo.py`; reuse it).
* `tasks()`: when the ROM is the Tynix kernel, its programs: pid, name,
  state, region base and size, and the `.map` of the `.exe` (found by name
  in `compiler/ROM/`) with the region offset (`base - 0x1100000`), so RAM
  addresses in a task map back to function names and C lines.
* `frames(esp, ebp, iar)`: the call chain (item 8).
* `heap(start, end)`: the malloc blocks (item 9).
* `regions()`: the memory layout (item 10).

**Key design choice: how Python reads the kernel's task table.** Reading
`struct task` directly would tie Python to the C struct's layout, which
breaks silently whenever a field is added. Instead, the kernel keeps a small
debug table that is part of its contract: `unsigned _dbg_tasks[16][4] =
{pid, base, words, name address}` and `_dbg_version`, updated in the kernel's
spawn and exit. The table costs 64 words and a few stores per spawn.
`machine_view.py` finds it through the `.map`. The disk self-check compares
it with `jobs` output.

**Checks.** Simulator selftest: boot the kernel with `--keys`, start two
programs, and check that `tasks()` matches `jobs`. Check `frames()` and
`heap()` on small C programs with known shapes.

**Docs.** TECHNICAL §3.1 (module list), §11 (the debug table), STRUCTURE
tree, the CLAUDE.md row "a system call, the block a program gets, or TEX2"
gains `_dbg_tasks`.

**Verdict:** a prerequisite, not a feature. Without it, items 7–11 would
each reinvent it.

---

## B. Shell and kernel

### 3. `<` input redirection (rank 2)

**What it does.** `prog < file` gives a program a file as its stdin
(`getchar`, `fgets`, `scanf` read the file, EOF at its end). Both can be
combined: `sort < in.txt > out.txt` (once a sort program exists). `cat <
file` works too.

**What exists.** The kernel already supports it: `SPAWN_IN(fd)`, the block's
`B_IN`, and `spawn_io(path, argv, in, out, flags)` in `unistd.h`. Only the
shell is missing it.

**Plan.**
1. In `split()` (shell.c), take `< FILE` out like `> FILE`, into `input`.
2. In `run_program()`, call `fopen(input, "r")`, or `"rb"` when `stat()`
   says the file is binary, as `cp` already does. Then call
   `spawn_io(path, argv, in, out, flags)` instead of `spawn_to`, and close
   the shell's `FILE` at once, as for `>`.
3. Built-ins: only `cat` reads stdin. `cat < f` behaves as `cat f`. Others
   ignore `<` with a message, as `&` does today.
4. `sh -c` and `run` get it for free, since they go through `run_line()`.

**Checks.** Disk self-check `SHELL_OUTPUT`: `guess < answers.txt` (scripted
input to a game), `cat < notes.txt`, a missing file's error, `<` with `>`.

**Docs.** shell.c header and help, TECHNICAL §11 (built-ins and the
redirection paragraph), STRUCTURE, `tynix/cpu_claude.md` (Claude can then
feed input to programs).

**Verdict: do it.** About an hour of work, and it unlocks scripted testing of
interactive programs, both for the self-checks and for Claude.

### 4. Environment variables and `PATH` (rank 66)

**What it does.**
* Shell built-ins `set NAME=value` (shell only), `export NAME[=value]`
  (passed to children), `unset NAME`, and `env` (list them).
* `$NAME` and `${NAME}` expand inside words and double quotes, but not in
  single quotes. `$?` gives the last status.
* `PATH` (default `/bin`, colon-separated) is searched for a plain name, so
  `/usr/bin` or `~/bin` can hold your own programs.
* `HOME` (`/home/user`), `PWD`, and `PS1` (the prompt, with `\w` for the
  directory) are set by the shell.
* `getenv()` in the C library works for programs (today it is a stub that
  returns 0), and so do `setenv()` and `unsetenv()` for the program's own
  copy.
* `/etc/profile` is run with `run` at shell start, if it exists, so settings
  persist on the disk.

**Plan.**
1. Block: add `B_ENV`, the address of a `NAME=value\0...\0\0` area. The
   kernel copies it to the region's top next to argv, as it does for argv
   today (`spawn()` gains an `envp` argument, or `SYS_SPAWN` reads it from a
   struct). This changes the program block, so it follows the doc row for
   "a system call, the block a program gets, or TEX2": `sys/tynix.h`,
   `kernel.c`, `compiler/libc/tynix/`, `driver.py`'s crt0 if the block's
   size changes, TECHNICAL §10.4/§10.5/§11, `c_language.md` §7.
2. libc: `getenv` reads the area; `setenv` makes a private copy on first
   change. A ROM program (no kernel) gets an empty environment.
3. Shell: a table of 64 entries, expansion in `split()` before the quote
   handling, and a `PATH` search in `run_program()`.
4. `make_disk.py`: a default `/etc/profile` (comments plus `export
   PATH=/bin:/home/user/bin`).

**Checks.** `SHELL_OUTPUT`: `export X=1`, then `sh -c 'echo $X'`, a C test
program in `/bin` that prints `getenv("X")`, `PATH` with two folders, `$?`,
and single quotes not expanding.

**Risks.** Old TEX1 programs have no `B_ENV`: their block keeps its old
shape, and `getenv` returns 0 there.

**Follow-ups.** `PS1` colours (no colours on the TTY); `alias`; `cd -`.

**Verdict: worth it.** Small, and it makes the shell feel like a real one.
`PATH` and `/etc/profile` matter once there are user programs (BASIC
programs, games).

### 5. Shell history and tab completion (rank 6)

**What it does.**
* **Up** and **Down** walk through the last 32 lines. **Enter** runs the
  shown line.
* **Tab** completes the word under the cursor: the first word from the
  built-ins and the names in `/bin` (and the `PATH` folders, after item 4),
  other words from the paths in the folder typed so far. A unique match is
  completed. Several matches are completed up to their common prefix, and a
  second Tab lists them under the line and prints the prompt and line
  again.
* Optionally, `history` lists the lines and `!N` runs one again.
* History persists in `/home/user/.sh_history` (the last 100 lines), read at
  start and appended after each line.

**Constraint that shapes it.** The text display (TTY) has no cursor
addressing: only printing, backspace (`0x08`, which erases), newline, and
form feed. So:
* the cursor is always at the end of the line;
* replacing the line means sending as many backspaces as it has characters,
  then the new text;
* left/right editing in the middle of a line is **not** in v1. It could be
  done later by erasing back to the cursor and reprinting the tail, with
  the cursor's position marked by the reprint.

The shell reads keys raw with `wait_key()` (no echo) and echoes them
itself, only when its stdin is the keyboard (`isatty(0)`). `sh -c`, `run`
and `<` keep using `fgets`. The arrow codes 28–31 come from the simulator's
keyboard (`key_code()` in devices.py). The circuit's Logisim keyboard has no
arrows; there, Ctrl-P and Ctrl-N work too.

**Lines that wrap.** A line longer than 64 columns wraps on the display. A
backspace at column 0 in the simulator's display, and Logisim's TTY: check
what they do before relying on it, and limit the edited line to what one
backspace run can erase, or redraw on a fresh line (`\n` + prompt) when it
wrapped.

**Checks.** `SHELL_OUTPUT` with `--keys` containing `\x1c` (up) and `\t`:
the transcript shows the recalled line and the completion. A self-check that
`.sh_history` holds the lines afterwards.

**Docs.** shell.c header, TECHNICAL §11, `cpu_claude.md` (Claude runs `sh
-c`, unaffected, but should know).

**Follow-ups.** Ctrl-R search; Ctrl-U (erase the line) and Ctrl-W (erase a
word), both cheap with backspaces.

**Verdict: do it.** This is what you notice every minute in the shell.

### 6. Pipes, `;` and `&&` (rank 3)

**What it does.** `ls -l /bin | grep exe`, `cat log.txt | grep error | more`.
Every program of a pipeline runs at once (Tynix is preemptive), joined by
kernel pipes. Also `a ; b` (one after the other) and `a && b` (b only if a
succeeded). `&` at the end runs the whole pipeline in the background.

**Two ways, and the recommendation.**
* (a) **Temp files.** `a > /tmp/p1; b < /tmp/p1`: the programs run one after
  the other. It is about a day of shell-only work, but it is not a real
  pipe (`yes | head` never ends) and it would be thrown away later.
* (b) **Kernel pipe objects (rec).** A new object kind next to the kernel's
  `FILE`s: a 256-word ring buffer, with reader and writer counts. `read` on
  an empty pipe blocks (a new wait kind, `W_PIPE`, woken by the next
  write), unless every writer has closed, which gives EOF. `write` on a
  full pipe blocks the same way. A write with no reader left fails with
  `EPIPE`, and the program ends with status 141, as in Unix. A new system
  call `SYS_PIPE(fds[2])`. Programs need no change: their stdin and stdout
  already go through `read`/`write` system calls when they are files, and
  the kernel's `read`/`write` dispatch on the object kind.

**Plan (b).**
1. kernel.c: `struct obj` gains `kind` (file or pipe), a ring buffer, the
   reader and writer counts, and the wake-up of blocked readers and writers
   in `sys_read`/`sys_write`; closing at exit decrements the counts.
2. `sys/tynix.h`: `SYS_PIPE`. libc: `pipe(int fds[2])` in `unistd.h`, and
   `fdopen()`-like wrapping so the shell can hand the ends to `spawn_io`.
3. shell.c: split the line at `|` (outside quotes), spawn every stage with
   its stdin from the previous pipe and its stdout to the next, wait for all
   of them, and use the last one's status. `;` and `&&` are split first.
   Built-ins in a pipeline: v1 refuses them with a message (they run inside
   the shell). v2 runs them in a child `sh -c`.
4. `isatty()` is 0 on a pipe, so `more` at the end of a pipe still pages and
   `grep` in the middle doesn't.
5. Keys: a program in the middle of a pipeline that calls `wait_key()`
   still reads the keyboard if it is the foreground program; only the last
   stage gets the foreground.

**Checks.** `SHELL_OUTPUT`: `ls /bin | grep e`, a three-stage pipeline,
`hexdump x | more`, a pipe whose reader quits early (status 141 for the
writer), `false && echo no; echo yes`. A kernel test with a tiny writer that
writes 10,000 words through a 256-word pipe, to check blocking both ways.

**Docs.** The doc row for system calls (sys/tynix.h, kernel.c, libc/tynix/,
TECHNICAL §10.5/§11, c_language.md §7), TECHNICAL §11.3 (remove "there are
no pipes", and the tools can read stdin when given no path), `cpu_claude.md`,
STRUCTURE.

**Follow-ups.** `grep` and `more` reading stdin with no path (`grep` today
needs a path); `wc`, `head`, `tail`, `sort` and `uniq` become worth writing
(the §11.3 list of "not done on purpose" items gets revisited); `2>`
redirection.

**Verdict: do it, with (b).** It is the biggest change in phase B, and the
one that makes the tools compose.

---

## C. Simulator window

All of these are new tabs or panes in `cpu_sim/src/gui.py`, and read the
machine through `machine_view.py` (item 2). They redraw with the state panes
(at most 10 times a second, `STATE_FPS`), so none of them slows the program.

### 7. Memory viewer extras (rank 44)

**What it does.** The ROM/RAM panes (`MemoryPane`) gain:
* a **float** column (float32 from the word, `alu.bits_to_float`) and a
  **text** column showing the 4 chars packed in a word, as TFS1 stores text
  files; each column can be switched on or off;
* **label names** in the margin at their addresses (from the `.map`, and
  per Tynix task);
* a **go-to box** that takes an address, a label (with completion), a
  register (`R3`, `ESP`), or an expression like `ESP-4`;
* **changed-word highlighting:** words that changed since the last redraw
  are drawn in a colour that fades over a few redraws. This keeps the
  previous page and compares, so it costs nothing in the running program;
* **bookmarks**, kept in a small JSON file next to the ROM.

**Checks.** The GUI self-check (it runs when tkinter is present) builds the
pane on a ROM with a map and checks the label column and the go-to parser.

**Docs.** TECHNICAL §3.3 ("The window").

**Verdict: do it,** as a warm-up for phase C.

### 8. Call-stack viewer (rank 10)

**What it does.** A "Stack" pane lists the call chain of the program being
run, innermost first: function name, the C file and line of the call, the
frame address (EBP), and the first argument words. Clicking a frame shows
that line in the C source tab and that frame in the RAM pane. Under Tynix
it shows the chain of the running task, labelled with the task's name.

**How (from the calling convention).** A `CALL` pushes the return address
and then `STK CALL` saves EBP: `stack[EBP]` = the caller's EBP, and
`stack[EBP-1]` = the return address. Arguments sit below that (`EBP-2`,
...). The pane walks that chain. The return address maps to the function
(`debuginfo.py`) and to the line of the call (the line holding the address
`return - 1`). Stops: EBP = 0 (crt0's frame), a return address outside code,
a loop, or 256 frames.

**Edge cases.**
* Between a `CALL` and the function's `STK CALL` (its first words), the top
  frame is not built yet. The pane notices that IAR is within the
  function's prologue and shows the frame as "entering".
* An interrupt entry (18 words, TECHNICAL §1.8) sits on the task's stack
  when the kernel runs. The pane stops there with "interrupt".
* Argument counts are unknown without help from the compiler. v1 shows
  three raw words.

**Follow-up (the real prize): variables.** The C compiler knows each
function's parameters and locals and their frame offsets (or registers).
Writing them to the `.map` (a `# frames` section: function, name, type,
`EBP+off` or `Rn`) lets this pane show `n = 12, p = 0x1004a20`. That is the
"C variable inspector", rank 25.

**Checks.** Simulator selftest: a C program with recursion
(`fact(5)`) and a breakpoint in the innermost call. The chain must be
`fact` ×5, then `main`, with the right lines.

**Docs.** TECHNICAL §3.3.

**Verdict: do it.** Debugging recursion and crashes gets much easier.

### 9. Heap visualiser (rank 32)

**What it does.** A "Heap" pane draws malloc's heap as a bar: used blocks
red, free blocks green, headers grey, to scale or one cell per block when
there are many. Hovering a block shows its address, size and first words;
clicking one opens it in the RAM pane. It shows totals: used, free, block
count, largest free block, and a fragmentation figure (1 − largest free ÷
total free). It shows a damaged header (size 0, or past the end, which
`malloc.c` refuses too) in yellow, with "heap damaged here".

**How.** `malloc.c` keeps a header word before each block: its size in words
(header included), positive when free and negative when used, from `_end` to
`_heap_end` (both linker symbols, found in the `.map`). The walk is
`machine_view.heap(start, end)`, capped at 20,000 blocks per redraw. Under
Tynix each task has its own heap, from its relocated `_end` to the block's
`B_END`. The pane picks the running task, or one chosen from a list. The
kernel's own heap is the kernel ROM's `_end`.

**Checks.** Selftest: a C program that mallocs and frees in a known pattern,
stopped at a breakpoint. The walk must give the expected sizes and states.

**Follow-ups.** An allocation timeline (needs a hook in `malloc` and `free`,
for example writes to a debug device, `0x7D`); leak listing at exit.

**Verdict: worth it,** mainly as a teaching view and for `structs.c`-style
programs, BASIC (item 17), and the kernel.

### 10. Memory map picture (rank 45)

**What it does.** A "Map" tab draws ROM and RAM as two columns, split into
their real parts, each labelled with its range and size:
* **ROM:** vectors (0–9), start-up code, every function (the bigger ones
  named), constant data.
* **RAM:** linker data, the stack (with live ESP and stack-limit markers),
  the heap (filled by how much is used, from item 9), free RAM.
* **Under Tynix:** the kernel's data and 8K-word stack, then each task's
  region from `0x1200000` (name, pid, size), split into `code + data`,
  `stack`, `heap`, `argv`, and the free gaps between regions (where the
  next program would go, first fit).

The scale is not linear: 16M words would make the vectors invisible. Each
part gets a minimum height and shows its real size as text. Clicking a part
opens it in the memory pane.

**Checks.** Selftest on `machine_view.regions()` for a ROM program and for
the kernel with two tasks (compared with `jobs`).

**Verdict: worth it.** Cheap once items 2 and 9 exist, and it is the
picture for the tutorial's memory chapter.

### 11. Machine snapshots (rank 7)

**What it does.** **Save state** and **Load state** buttons in the window,
`--save-state FILE` and `--load-state FILE` in `main.py`, and
`cc run ... --load-state`. A snapshot holds everything needed to continue
exactly:
* registers, IAR, flags, ESP, EBP, stack limit, the interrupt bits (`ie`,
  `in_nmi`, `inhibit`, `waiting`, pending NMI and fault), the instruction
  count;
* ROM and RAM as runs of non-zero words, zlib-compressed (a booted Tynix
  is a few hundred K words, so a few hundred KB, not 256 MB);
* devices: the display text, the RGB screen's pixels, the keyboard buffer,
  the hex display, the timer's milliseconds and period, the interrupt
  controller's pending and enable bits, the selected device addresses, and
  the disk position;
* the ROM's path and a hash, and the disk's path.

It is a zip with `state.json` and the binary parts, versioned
(`"format": 1`).

**The disk question.** The disk is a 64 MB sparse file that keeps changing.
Options:
* (a) save only its path, and warn on load if it changed since (rec for v1);
* (b) `--with-disk` copies it into the snapshot, sparse-aware (only the
  written blocks, using `SEEK_DATA` or the FAT).

**Not saved:** the Claude device's conversation (it is reset, with a note),
and the translated code (rebuilt: `cpu.forget_code()` after loading).

**Checks.** A selftest using `bench.py`'s end-state digest: run a program N
steps, save, load in a fresh CPU, run M steps; the digest must equal a
straight run of N+M steps. Do this for a ROM program, for the kernel with a
disk, and for a program taking timer interrupts (the timer is stopped
during the test, as `bench.py` does).

**Docs.** TECHNICAL §3.3 (window, flags), README "Quick start",
STRUCTURE commands, this CLAUDE.md's Commands.

**Follow-ups.** Snapshot on halt or crash, for later inspection; quick-save
slots in games; rewinding by keeping a snapshot every second (the base of
"reverse stepping", rank 52).

**Verdict: do it.** It is high value for debugging long runs (Tynix boot,
videos), and its digest test also makes it an exact regression tool.

---

## D. Seeing the toolchain and the CPU

### 12. Disassembler that rebuilds labels (rank 37)

**What it does.** `python compiler/src/asm disasm prog.rom [--map prog.map]
[-o prog.asm]` and `disasm prog.exe` write **assembly that the assembler
accepts again** and that builds the **same words**:
* finds code by following control flow from address 0, the vectors and
  every jump target; the rest becomes `.word` data, with chars shown in
  comments;
* turns jump offsets into labels (`L_00123`), or the `.map`'s names when
  given;
* recognises the pseudo-op patterns (`CALL target[, n]`, `RET`, `SAVE`,
  `RESTORE`) and writes them back as pseudo-ops, unless `--raw`;
* writes `DATA Rn, <label>` when the operand is an address in the program.
  For a TEX2 `.exe` this is exact, because the relocation list says which
  words are addresses; for a ROM it is a guess, marked `; guess` in a
  comment;
* adds C line comments when the `.map` has source lines.

**Checks.** Assembler selftest: for every example ROM and every `/bin`
`.exe`, disassemble, assemble again, and compare the words exactly (with
and without the map). This also checks `isa.py` and `encoding.py` against
each other once more.

**Docs.** `assembly_syntax.md` §10, TECHNICAL §4.1, STRUCTURE commands,
CLAUDE.md Commands.

**Follow-ups.** The window's disassembly uses the rebuilt labels; a `disasm`
program in Tynix's `/bin` (a C port, for `hexdump`'s cousin).

**Verdict: worth it.** The round-trip test makes it trustworthy, and it
answers "what did the compiler really produce" for any binary.

### 13. Interactive ISA reference page (rank 36)

**What it does.** `python compiler/src/asm/isa_page.py [-o isa.html]` writes
one self-contained HTML file (no network; opened locally, like
`asm_grammar.py`'s railroad page):
* every instruction in a table by group, with mnemonic, encoding, words,
  effect and flags;
* clicking one shows its **bit fields** drawn as a 16-bit row (opcode, RA,
  RB, IMM/FLOAT/ALU bits), an example with its machine word, the flags it
  changes, its **micro-steps** from `logisim/microcode/microcode.py` (which
  control lines each step raises), and a badge "simulator only (TECHNICAL
  2.6)" for group `0x2`;
* a **decoder box**: type a hex word, see the instruction (a small JS
  decoder generated from the same tables);
* an **encoder box**: pick an instruction and registers, see the word.

**Single source of truth.** Encodings come from `encoding.py`, steps from
`microcode.py`, and descriptions from the tables in `assembly_syntax.md` §4
(parsed, not copied), so the page can't drift from the docs. `check_docs.py`
gains a check that every opcode in `encoding.py` has a row in §4.

**Checks.** Assembler selftest: the page builds, every opcode appears, and
the JS decoder's tables equal `isa.py`'s decode on all 65,536 words (checked
in Python on the generated tables, not by running JS).

**Docs.** TECHNICAL §4, STRUCTURE tree, README "Documentation".

**Verdict: worth it.** It's 1–2 days of work, it's the tutorial's ISA
chapter, and its consistency check is useful by itself.

### 14. Compiler explorer: how the compiler works (rank 27)

**What it does.** `python compiler/src/cc explore prog.c [-o prog.html]`
writes one self-contained HTML page that shows a C program going through
every stage of tiny C, side by side and linked:
1. **C source.** Hovering a line highlights everything it became in the
   other panes.
2. **Preprocessed tokens** (after `#include` and `#define`), collapsed by
   default.
3. **Syntax tree** of the selected function, as an indented tree with types
   (`int`, `char *`).
4. **Register allocation:** which locals got registers (`regalloc.py`), which
   live in the frame and at which `EBP` offset, and which registers each
   call keeps.
5. **Assembly before the peephole pass** and **after it**, as a diff, with
   each removed or changed line labelled by the rule that did it (`jumps`,
   `stack_reload`, `flags`, `unreachable`, `known_values`...). This covers
   the "peephole before/after" idea (#30 of the 100) as well.
6. **Machine words:** addresses and hex words from the linked program, with
   the disassembly, and the C line each one came from (`.loc` → `.map`
   lines).
7. **Run statistics** (optional, `--run`): run it in the simulator and show
   the instruction count per C line as a heat bar beside the source.

**Changes inside the compiler (small, opt-in).**
* `peephole.optimize()` takes an optional `log` list and records `(rule,
  before, after)` when given one. With no log there is no cost.
* `driver.py` exposes the intermediate results it already has (tokens,
  tree, assembly before and after the pass) through an `explore()`
  function.
* Per-line instruction counts: `CPU.run()` has no per-address counts on the
  fast path, so use `step()` (slow, fine for small programs) or a
  `--profile` mode that counts at translated-block granularity.

**Checks.** C compiler selftest: `explore` runs on every program in
`compiler/src/cc/tests/`; every assembly line is linked to a C line or
marked crt0/prologue/epilogue; the peephole log's "after" equals the real
output.

**Docs.** `c_language.md` (a section "seeing what the compiler does"),
TECHNICAL §10, STRUCTURE commands, CLAUDE.md Commands.

**Follow-ups.** A "why is this slow" mode that marks spills and reloads;
the tutorial's compiler chapter uses it throughout.

**Verdict: do it.** It explains the most complex part of the project,
helps when improving the compiler, and makes great video material.

### 15. Animated datapath (rank 21)

**What it does.** A "Datapath" tab in the window draws the CPU's parts as
`CPU.circ` has them: the bus, R0–R15, TMP, the ALU, ACC, FLAGS, IAR, IR,
MAR, ROM/RAM, the stack unit (ESP/EBP), the I/O block, and the stepper. When
you single-step it **plays the instruction micro-step by micro-step**:
* the part that drives the bus lights up (an `_E` line, `clk_e`), and the
  parts that latch from it (`_S` lines, `clk_s`);
* the value on the bus is written on it;
* the step number, the control lines raised, and a sentence ("step 4: RB
  onto the bus, TMP latches it").

It plays at an adjustable speed, with play/pause and next/previous step.

**Where the steps come from.** `logisim/microcode/microcode.py`'s table,
read off the circuit and checked against its gates by `verify.py`. That
table holds, for every instruction and step, the 32 control bits.

**Values on the bus (the hard part).** The simulator executes a whole
instruction at once. To show values, add `cpu_sim/src/micro.py`: a
micro-step executor that runs the microcode table on a model of the
registers (bus, TMP, ACC, MAR, IR...). This is a **third implementation**
of the ISA: from the circuit's own control table, next to `cpu.py` and the
circuit. A selftest runs every example program both ways, and the
architectural state must match after every instruction, so the animation
becomes a check that the circuit's microcode and the simulator agree.

**Limits.**
* Group `0x2` (interrupts, Phase 6) is not in the microcode: the tab shows
  "not on the circuit yet (TECHNICAL 2.6)" and skips the animation.
* The 16-bit banks of the real circuit: the tab models the circuit as it
  will be after widening, and says so.

**Plan.**
1. `micro.py` (executor) and its comparison selftest. This is the core,
   and it is useful even without the drawing.
2. A layout description: a list of parts with positions, and which control
   bit drives each. Drawn once on a Tk `Canvas`.
3. The animation driver: given an instruction and its micro-steps, colour
   the parts per step, with an `after()` timer.
4. Optional: export one instruction's animation as an animated GIF or a
   series of PNGs, for the tutorial and the video.

**Checks.** The `micro.py` comparison on every example (runs of 100,000
instructions); the GUI check builds the tab.

**Docs.** TECHNICAL §2.5 (microcode) and §3, STRUCTURE.

**Follow-ups.** When the microcode ROM is wired into `CPU.circ` (rank 23)
and Phase 6 is built on the circuit, the same table drives everything;
`micro.py` then also runs group `0x2`.

**Verdict: do it, in two parts.** `micro.py` and its check first (high
value, effort 3), then the drawing (effort 2–3). It's the single most
"wow" feature for the video.

---

## E. Devices and programs

### 16. Mouse device (rank 39)

**What it does.** Programs can read the mouse over the RGB screen:
position in screen pixels (0–255, 0–255), buttons (left, right, middle) and
wheel steps, by polling or by interrupt.

**The device (simulator only).**
* `0xBC` `INDATA`: the state, `x` in bits 31–24 and `y` in bits 23–16 (the
  same layout as a pixel word, so `gfx_` code can reuse it), buttons in bits
  2–0, a "pointer is over the screen" flag in bit 3.
* `0xBD` `INDATA`: the next event from a queue (press, release, wheel up or
  down, with the position), 0 when empty.
* The interrupt source `IRQ_MOUSE = 2` (interrupt controller `0xAC/0xAD`) is
  raised on a button event, not on motion, to avoid floods.
* Window: `<Motion>`, `<ButtonPress>`, `<ButtonRelease>` and the wheel on
  the screen canvas, converted by the zoom. Headless: `--mouse
  "x,y,buttons@step;..."` for scripted tests.

These are free addresses (in use today: `0x3C 0x5C 0x6C 0x6D 0x7C 0x8C 0x8D
0x9C 0xAC 0xAD 0xF0`).

**Software.**
* `cpu.h`: `mouse_state(&x, &y)` (returns the buttons), `mouse_event(&ev)`.
* Tynix: like the keyboard and screen, only the foreground program gets the
  mouse. A system call `SYS_MOUSE` answers for the foreground task and
  blocks a background one.
* `gfx.h` gains a cursor helper (save the pixels under a 5×7 arrow, draw,
  restore). The screen can't be read back, so the program keeps the saved
  pixels itself.

**The circuit.** Logisim-evolution has no mouse component. Its Joystick
(analog x/y and a button) could stand in later, as a decision to take then.
Keep the device listed as simulator-only (TECHNICAL §1.7).

**First users (the device is only worth it with programs that use it).**
`visual_file_manager` (click to select, double-click to open),
`edit` (click to move the cursor), and a small `paint` program. The
raycaster (item 18) could add mouse-look.

**Checks.** Simulator selftest with `--mouse` scripts; a C test program that
prints the events it reads; the disk self-check runs `paint` with a script
and compares the screen's PNG.

**Docs.** The interrupts doc row (cpu.py, devices.py, config.py, TECHNICAL
§1.7/§1.8), `cpu.h`, `c_language.md` §7, the system-call row, STRUCTURE.

**Verdict: worth it with at least one user program in the same PR.**
Without one, it's a device nobody calls. It's also the first step to the
window system (rank 24).

### 17. BASIC interpreter (rank 4)

**What it does.** `basic` in `/bin`: a home-computer BASIC on Tynix.
* **Interactive:** numbered lines are stored; `RUN`, `LIST [a-b]`, `NEW`,
  `SAVE "file"`, `LOAD "file"` (text files on the disk); unnumbered lines run
  at once.
* **Statements:** `PRINT` (with `;` and `,`), `INPUT`, `LET` (optional),
  `IF ... THEN ... [ELSE ...]`, `GOTO`, `GOSUB`/`RETURN`,
  `FOR ... TO ... STEP`/`NEXT`, `WHILE`/`WEND`, `DIM` (arrays), `REM`, `END`,
  `STOP`, `DATA`/`READ`/`RESTORE`, `RANDOMIZE`.
* **Values:** numbers (32-bit float, the machine's `double`), strings
  (`A$`); functions `ABS INT SQR SIN COS RND LEN MID$ LEFT$ RIGHT$ CHR$ ASC
  STR$ VAL`.
* **Machine extras:** `CLS`, `PLOT x,y,c`, `LINE`, `CIRCLE`, `COLOR`, `TEXT`
  (the RGB screen through `gfx.h`); `INKEY$` (`key_pressed()`); `SLEEP ms`;
  `PEEK`/`POKE` (RAM, within the program's own region) for fun.
* **Errors:** `?SYNTAX ERROR IN 120`. Esc goes to the kernel's NMI menu;
  Ctrl-C at `INKEY$`/`INPUT` stops the program and returns to the prompt.
* `basic prog.bas` runs a file and exits, so BASIC programs work like
  commands (with `PATH`, item 4).

**Design.** Lines are tokenised when entered (keywords as one word each,
which keeps the interpreter fast at 32-bit-word chars); a recursive-descent
expression evaluator; a variable table with hashing; a `GOSUB`/`FOR` stack.
Strings use malloc with free on reassignment (a showcase for the heap view,
item 9). One file, `tynix/basic.c`, about 1,500–2,500 lines of C.

**A test bonus.** The core (no `gfx`) is portable C, so a test program in
`compiler/src/cc/tests/` can run a built-in BASIC listing under gcc and tiny
C and compare outputs, which also stresses the compiler (recursion, strings,
switch, floats).

**Checks.** Disk self-check: `basic` runs a few `.bas` files (FizzBuzz,
primes, a `GOSUB`-heavy one, string functions, `SAVE`/`LOAD`), and the
transcript is compared. `make_disk.py` puts sample programs in
`/home/user/basic/`.

**Docs.** The `/bin` row (shell.c help, make_disk.py `PROGRAMS`, TECHNICAL
§11 and a §11.x for BASIC, STRUCTURE, `SHELL_OUTPUT`), `cpu_claude.md`
(Claude can write and run BASIC).

**Follow-ups.** A BASIC program library on the disk; `RENUM`; sound
statements once there is a sound device; a compiler from BASIC to the
assembly (far later).

**Verdict: do it.** It turns the machine from "runs my C programs" into
"a computer you can sit at and program", the classic experience.

### 18. Raycaster: a 3D maze (rank 5)

**What it does.** `maze3d` in `/bin`: walk through a maze in first-person
3D on the RGB screen.
* **Controls:** W/S move, A/D turn, Q/E strafe, M toggles a minimap, `q`
  or Ctrl-D quits, Esc for the NMI menu.
* Walls shaded by distance and by side (x or y faces), a floor and ceiling
  gradient, and the maze's exit marked. A timer shows how long the run
  took; the best time is saved to a file.
* Mazes are generated (randomised depth-first search) or loaded from a text
  file (`#` for walls), so players can make their own in `edit`.
* All art is procedural and original (no textures or levels from any
  existing game).

**Technique.** Classic grid raycasting with a DDA per screen column, in
32-bit floats (single instructions on this CPU). `sin`/`cos` come from a
256-entry table made at start. The view renders at 128 columns × 2 pixels
wide, drawn with `gfx_vline` per wall slice; only columns that changed
height or colour since the last frame are redrawn, to save pixel writes.

**Speed estimate.** About 50,000 pixel writes for a full frame (a few
instructions each), plus about 128 × 30 DDA steps, so roughly 300–400K
instructions per frame. That matches `video_player`'s measured 350K per
128×96 frame, which plays at 12 fps under CPython and pypy3. Expect 10–20
fps at `max`, more with the changed-columns trick. The window's
`settle()`/hold-back logic already avoids showing half-drawn frames.

**Input constraint.** The keyboard gives presses only (no key-up), with the
PC's auto-repeat. So motion is "one step per press" with smoothing; holding
a key works through auto-repeat. A key-up event would be a later device
change.

**Checks.** Disk self-check: run it with scripted keys
(`--keys 'wwwwddq'`) and compare the screen PNG's hash; a run against a
fixed seed checks the maze generator.

**Docs.** The `/bin` row; its own header; TECHNICAL §5.3 if it goes in
`compiler/examples/c/games/` instead (recommended: it is a C example that
also runs as a ROM).

**Follow-ups.** Procedural textures; sprites (keys, an exit door);
mouse-look (item 16); doors; a "speedrun" ghost.

**Verdict: do it.** It's the best demo of the float unit and the screen, and
an excellent video moment.

### 19. CHIP-8 interpreter (rank 11)

**What it does.** `chip8 FILE` in `/bin` runs CHIP-8 programs (the 1970s
virtual machine). This means a whole other machine's programs run on our
CPU.
* 4K memory, 16 `V` registers, `I`, a stack of 16, the 35 instructions, and
  the two 60 Hz timers driven by `clock()`;
* its 64×32 display drawn at 4× scale (256×128) in the middle of the RGB
  screen, redrawn only where pixels changed (XOR drawing);
* the 16-key hex pad on `1234 / QWER / ASDF / ZXCV`;
* a speed setting (instructions per frame), and a debug key that shows the
  registers on the text display.

**Constraints and answers.**
* **Key held vs pressed:** CHIP-8's `SKP` and `SKNP` ask "is key X held?",
  but our keyboard has presses only. A key counts as held for 150 ms after
  each press, which the PC's auto-repeat refreshes. This is a known
  approximation, and the plan's main risk.
* **Loading the ROM files:** CHIP-8 programs are bytes. Check how a text
  file stores a byte 0 (TFS1 packs 4 chars a word; a 0 char may end the
  text). If it can't hold one, add `disk put --bytes` (one byte per word,
  binary) and read with `fread`.
* **Which programs to ship:** only programs we write ourselves, with a
  small Python CHIP-8 assembler in `tools/` or hand-assembled hex. Users can
  put their own `.ch8` files on the disk. No third-party ROMs in the repo.

**Checks.** Disk self-check: our own test ROMs (one per instruction group,
drawing a known pattern), with the screen hash compared. A unit test
compares the C interpreter against a small Python reference interpreter on
those ROMs, the same way `codec.py` is the reference for `gfx_image.c`.

**Docs.** The `/bin` row, its header.

**Follow-ups.** SUPER-CHIP extensions (128×64, scrolling); a CHIP-8
assembler running *inside* Tynix.

**Verdict: worth it.** A fun "emulator on an emulator" story, moderate work,
and the reference-interpreter test keeps it honest.

### 20. A falling-block puzzle game of our own (rank 12)

**What it does.** A new game in the falling-block genre, with **our own
name, look and rules**. It's not a copy of any existing game: no
trademarked name, no copied visuals, no copied music. Proposed: **"Stackfall"**
(name to be chosen by you).
* A well 10 wide and 20 tall on the RGB screen; pieces fall on the timer
  (`clock()`), faster with each level.
* Move with A/D, rotate with W, soft drop with S, hard drop with space.
* A next-piece preview, a score, lines and level, and high scores in
  `/home/user/.stackfall` (top 10, name entry).
* **Our own twist, to make it ours:** pick one (a choice for you):
  * (a) pentomino mode, with 5-cell pieces;
  * (b) "gravity" mode, where after a clear, blocks with nothing below fall
    and can chain;
  * (c) colour matching, where three same-colour cells in a row also
    clear.
* It redraws only the cells that changed, handles `gfx_lost()` (redraw when
  it gets the screen back), and pauses on `p`.

**Checks.** Disk self-check with scripted keys and a fixed random seed: the
final score and the screen hash.

**Docs.** The `/bin` row, or `compiler/examples/c/games/` (TECHNICAL §5.3,
STRUCTURE tree), its header.

**Verdict: do it.** It's quick, it's fun, and it's the first game people try.

---

## F. Tutorial series (rank 30)

**What it is.** A public, step-by-step "build a computer from gates to an OS"
series in the repo, `tutorial/NN-name.md`. Each chapter follows **one
concrete example** through its layer, with numbers from real runs, as the
vault's "How it works" notes do for the OS. Those notes are private and
**must not be copied**: the tutorial is written fresh from the repo and the
tools.

**Chapters (draft).**
1. Bits and gates: the ALU's adder in `CPU.circ`.
2. Registers and the bus: one `CPY`.
3. The control section: steps and micro-steps (the datapath, item 15).
4. Memory and I/O: printing a char.
5. The ISA: one program by hand (the ISA page, item 13).
6. The assembler and linker: `hello.asm` to `.rom` (the disassembler, item
   12).
7. The C compiler: one function through every stage (the compiler
   explorer, item 14).
8. The simulator: interpreting vs translating, and why pypy is fast.
9. Interrupts: the timer, `RTI`, the stack limit.
10. The kernel: two programs sharing the CPU (the memory map, item 10).
11. The filesystem: a file's blocks on the disk.
12. The shell: from a typed line to a running program (pipes, item 6).
13. Programs: BASIC and the raycaster as case studies.
14. Claude on the CPU: the device and `claude`.

**A rule that keeps it true.** Each chapter's code and commands live in
`tutorial/code/NN/`. A new check (in `check_docs.py`, or a sixth suite) runs
every command and compares the output written in the chapter, so the
tutorial breaks the build instead of going stale.

**Effort.** About 1–2 days per chapter; written alongside the phases (a
chapter when its part is done).

**Follow-ups.** The YouTube series (rank 53) follows the chapters; a
project website (rank 62) can render them.

**Verdict: do it, gradually.** It turns the project into something others
can learn from, and the checked-commands rule keeps it from rotting.

---

## Decisions for you

These are the open choices this plan raises, each with a recommendation.
(The vault isn't reachable from this cloud session, so they're listed here
instead of in the vault's `OS questionnaire.md`; copy them there when you
next work locally.)

1. **Pipes:** (a) temp files, or (b) kernel pipe objects **(rec)**.
2. **Environment:** (a) passed in the program block, inherited **(rec)**,
   or (b) a file on the disk (`/etc/env`) that programs read.
3. **Snapshot disk:** (a) path only, with a warning **(rec for v1)**, or (b)
   always copied.
4. **Datapath:** (a) a Tk tab in the simulator **(rec)**, or (b) a
   standalone HTML page.
5. **Mouse addresses** `0xBC`/`0xBD` and `IRQ_MOUSE = 2`: OK?
6. **BASIC dialect:** (a) line-numbered, classic **(rec)**, or (b)
   structured, without line numbers.
7. **Falling-block game:** its name, and the twist (pentomino, gravity
   chains or colour matching).
8. **Tutorial location:** (a) `tutorial/` in this repo **(rec)**, or (b) a
   separate repo or site.
9. **Where the games live:** (a) `compiler/examples/c/games/` (they run as
   ROMs too, and are in `PROGRAMS`) **(rec)**, or (b) `tynix/`.
