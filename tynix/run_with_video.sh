#!/usr/bin/env bash
# run_with_video.sh - the OS shell in the simulator window, with video_player in /bin
#
#   tynix/run_with_video.sh                 plays what video_player.c includes by default (VIDEO there)
#   tynix/run_with_video.sh clip.h          plays that one (made by python compiler/src/img/video.py clip.mp4),
#                                        e.g. compiler/examples/c/graphics/videos/demo.h, the 4 s test picture
#   SIM_ARGS="--headless --keys \$'/bin/video_player\nhalt\n' --steps 400000000" tynix/run_with_video.sh
#                                        extra options for the simulator (here: no window)
#   DISK=other.img tynix/run_with_video.sh  another disk image (default tynix/disk.img)
#   PY=python tynix/run_with_video.sh       another interpreter (default pypy3, else python)
#
# pypy3 matters: the player needs about 50 million simulated instructions a
# second (1.6 million a frame at 30 fps), which plain python does not reach.
# Even so a few frames at the start come late (pypy's warm-up), and more in
# the window, which pauses the simulator between its 50 ms slices.
#
# Builds the shell and tynix/disk.img (what is already on the disk stays; delete
# the file for a fresh one), builds video_player as a program for the OS and
# puts it in /bin, then starts the simulator. In the window: run, speed "max",
# the "RGB screen" tab, and type /bin/video_player in the shell.
set -euo pipefail
cd "$(dirname "$0")/.."
DISK="${DISK:-tynix/disk.img}"
PY="${PY:-$(command -v pypy3 || command -v python)}"

CLIP_ARGS=()
if [ $# -ge 1 ]; then
    clip=$(realpath "$1")
    [ -f "$clip" ] || { echo "$1: no such file" >&2; exit 1; }
    CLIP_ARGS=(-I "$(dirname "$clip")" -D "VIDEO=\"$clip\"")
fi

"$PY" compiler/src/cc build tynix/shell.c
"$PY" tynix/make_disk.py "$DISK"
"$PY" compiler/src/cc build compiler/examples/c/graphics/video_player.c --exe \
    -o compiler/ROM/video_player.exe "${CLIP_ARGS[@]}"
"$PY" compiler/src/disk put "$DISK" compiler/ROM/video_player.exe /bin/video_player --binary
eval "\"$PY\" cpu_sim/src/main.py compiler/ROM/shell.rom --disk \"$DISK\" ${SIM_ARGS:-}"
