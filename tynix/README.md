# Tynix

The OS (simulator only). Reference: TECHNICAL §11.

| path | what it is |
| --- | --- |
| `kernel.c` | the ROM: boots, loads programs, switches between them, system calls |
| `shell.c` | `/bin/sh`, the shell |
| `bin/` | sources of the OS's own programs for `/bin` (editors, tools, file manager, `claude`); see [`bin/README.md`](bin/README.md) |
| `make_disk.py` | builds `disk.img` with `/bin/sh`, `bin/*` and the C examples built `--exe` |
| `run_with_video.sh` | builds everything, puts `video_player` in `/bin` and opens the window |
| `cpu_claude.md` | Claude's system prompt (what it knows about the machine) |
| `claude_access.conf` | the PC paths Claude may read or write |
| `claude/` | Claude's own folder on the PC (only its `README.md` is committed) |
| `disk.img` | the disk, made by `make_disk.py` (git-ignored) |

Run it: `python compiler/src/cc build tynix/kernel.c`, `python tynix/make_disk.py`, then `python cpu_sim/src/main.py compiler/ROM/kernel.rom --disk tynix/disk.img`.
