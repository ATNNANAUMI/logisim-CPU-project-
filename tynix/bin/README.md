# tynix/bin: the OS's own programs

Each file is one program, built with `cc build --exe` by `tynix/make_disk.py` and put in `/bin/NAME` on the disk. Programs from `compiler/examples/c/` that also go to `/bin` are listed in `make_disk.py`.

| program | what it does |
| --- | --- |
| `ed` | line editor for text files (`a i c d p s w q`) |
| `edit` | full-screen editor on the RGB screen |
| `visual_file_manager` | two-pane file manager on the RGB screen |
| `more` | show a file a page at a time |
| `grep`, `find` | search inside files; find paths by name |
| `tree`, `du` | a folder as a tree; disk use in KB |
| `diff`, `hexdump` | the lines that differ between two files; a file in hex |
| `calc` | 32-bit integer calculator |
| `claude` | talk to Claude through the Claude device (`cpu_sim/src/claude.py`) |
