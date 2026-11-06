#!/usr/bin/env bash
# Demo launcher: venv, API key, build and run, in one command.
#   logisim/claude/demo.sh sim       Claude terminal in the simulator window (real API)
#   logisim/claude/demo.sh bridge    build the ROM, run bridge.py for the circuit's Telnet component
#   logisim/claude/demo.sh fake      bridge.py with canned answers (no key, no network) for the circuit
#   logisim/claude/demo.sh tynix     boots the OS: the shell opens, type `claude` (real API)
#   logisim/claude/demo.sh test      the self-check
# Add --window to open it in a new big-font kitty window instead of this terminal.
# The key is read from ~/.config/logisim-claude.env (one line: ANTHROPIC_API_KEY=sk-ant-...), never from the repo.
# A script cannot change the terminal that started it (its exports die with it); --window is the way to get a
# configured terminal. To configure your own: source .venv/bin/activate.fish
set -e
cd "$(dirname "$0")/../.."
mode=${1:-sim}
if [ "$2" = --window ] || [ "$1" = --window ]; then
    [ "$1" = --window ] && mode=sim
    exec kitty -o font_size=18 --title "Claude on a CPU" "$0" "$mode"
fi
. .venv/bin/activate
if [ "$mode" != fake ] && [ "$mode" != test ]; then
    [ -f ~/.config/logisim-claude.env ] && { set -a; . ~/.config/logisim-claude.env; set +a; }
    [ -n "$ANTHROPIC_API_KEY" ] || { echo "no key: put ANTHROPIC_API_KEY=... in ~/.config/logisim-claude.env (or use 'fake')"; exit 1; }
fi
SYS=(--claude-system logisim/claude/system.md)
case $mode in
    sim)    pypy3 compiler/src/cc build logisim/claude/claude_term.c
            exec pypy3 cpu_sim/src/main.py compiler/ROM/claude_term.rom "${SYS[@]}" ;;
    fake)   pypy3 compiler/src/cc build logisim/claude/claude_term.c
            exec pypy3 logisim/claude/bridge.py --fake --port "${PORT:-2323}" ;;
    bridge) pypy3 compiler/src/cc build logisim/claude/claude_term.c
            echo "ROM: compiler/ROM/claude_term.rom (load it in the circuit, start the simulation)"
            exec pypy3 logisim/claude/bridge.py --port "${PORT:-2323}" ;;
    tynix)  pypy3 compiler/src/cc build tynix/kernel.c
            [ -f tynix/disk.img ] || pypy3 tynix/make_disk.py
            exec pypy3 cpu_sim/src/main.py compiler/ROM/kernel.rom --disk tynix/disk.img ;;
    test)   exec pypy3 logisim/claude/test.py ;;
    *)      sed -n 2,8p "$0"; exit 1 ;;
esac
