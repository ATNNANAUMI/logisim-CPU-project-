# tynix/claude/

Claude's own folder on the PC: the Claude device (`cpu_sim/src/claude.py`,
TECHNICAL 11.5) lets Claude read and write here, and nowhere else on the PC
unless `tynix/claude_access.conf` says so. A path Claude gives without a
leading `/` or `~` starts here.

What Claude writes is not committed (`.gitignore`); only this file is.
