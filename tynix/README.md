# Tynix

The OS (simulator only). Reference: TECHNICAL §11.

| path | what it is |
| --- | --- |
| `kernel.c` | the ROM: boots, loads programs, switches between them, system calls |
| `shell.c` | `/bin/sh`, the shell |
| `bin/` | sources of the OS's own programs for `/bin` (editors, tools, file manager, `claude`); see [`bin/README.md`](bin/README.md) |
| `scripts/` | shell scripts that `make_disk.py` puts in `/home/user/bin` (on `PATH`): `backup` `restore` `trash` `untrash` `wc` `head` `tail` `nl` `uniq` `touch` `cleantmp` `changed`; usage is in each file's first lines |
| `basic/`, `chip8/` | sample BASIC programs and CHIP-8 test programs, copied to `/home/user/basic` and `/home/user/chip8` |
| `make_disk.py` | builds `disk.img` with `/bin/sh`, `bin/*` and the C examples built `--exe` |
| `run_with_video.sh` | builds everything, puts `video_player` in `/bin` and opens the window |
| `cpu_claude.md` | Claude's system prompt (what it knows about the machine) |
| `claude_access.conf` | the PC paths Claude may read or write |
| `claude/` | Claude's own folder on the PC (only its `README.md` is committed) |
| `disk.img` | the disk, made by `make_disk.py` (git-ignored) |

Run it: `python compiler/src/cc build tynix/kernel.c`, `python tynix/make_disk.py`, then `python cpu_sim/src/main.py compiler/ROM/kernel.rom --disk tynix/disk.img`.

## Shell scripts

The shell speaks a small POSIX sh (TECHNICAL §11, "The language"): `|` `;`
`&&` `||` `!`, `if`/`while`/`until`/`for`/`case`, `{ }` and `( )`,
functions with `local` and `return`, `$( )`, `$(( ))`, `${NAME:-default}`,
`${NAME#pat} ${NAME%pat}` (and the doubled forms) to cut a path apart, `* ? [..]` file names, `~`, `#` comments, `test`/`[ ]`, `read`, aliases.

A script is a text file. Write one at the prompt with `cat > FILE` (Ctrl-D
ends it), with `ed`/`edit`, or on the PC with `python compiler/src/disk put
tynix/disk.img backup.sh /home/user/bin/backup`:

```sh
#!/bin/sh
# backup: copy the text files of a folder (default: here) into /tmp/backup
dir=${1:-.}
mkdir /tmp/backup
n=0
for f in $dir/*.txt; do
    [ -f "$f" ] || continue
    cp "$f" /tmp/backup && n=$((n + 1))
done
echo "$n files copied from $dir"
```

Run it with `sh backup [dir]`, or by its name: a text file whose first line
is `#!/bin/sh` runs as a program, so in a folder of `$PATH` (the disk's
`/etc/profile` puts `/home/user/bin` there; make it once with `mkdir
/home/user/bin`) it is just `backup /home/user/Documents`.
`$0` is its path, `$1 ...` the arguments, `exit N` its status, and Esc kills
it like any program. `run FILE` (or `. FILE`) runs a file in the current
shell instead, so what it sets stays.

Aliases name a command line; put them in `/home/user/.profile`, which the
shell runs at start after `/etc/profile`:

```sh
alias ll='ls -l'
alias bk='backup /home/user/Documents'
alias primes7='primes | grep 7'
up() { cd ..; ls; }
```

`alias` lists them, `type NAME` says what a name is, `unalias NAME` forgets
one. Things to know: quote `( ) | & < > *` when they are text (`calc '2 *
(3 + 4)'`); a built-in, function or loop in a pipeline runs in a new shell,
so what it sets stays there (`ls | while read f; do n=$((n+1)); done` leaves
`n` as it was); an endless loop typed at the prompt can't be stopped (put it
in a script: Esc kills that).
