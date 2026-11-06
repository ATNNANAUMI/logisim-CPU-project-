/* claude_term.c - a terminal to Claude for the bare CPU: no shell, no OS
 *
 *   python compiler/src/cc build logisim/claude/claude_term.c       (-> compiler/ROM/claude_term.rom)
 *   python compiler/src/cc build logisim/claude/claude_term.c -D PORT=0x9C
 *
 * Load the ROM in the circuit, run python logisim/claude/bridge.py on the PC
 * (README.md next to this file), start the simulation and type on the keyboard.
 *
 * Claude does not run on this CPU: the CPU is its terminal. What you type goes,
 * a char at a time, to the port device (PORT, 0x9C like the simulator's Claude
 * device; on the circuit the Telnet component behind it), and a 0 sends the
 * line. The PC answers with the reply, a char at a time, and a 4 (EOT) at its
 * end; this program prints it, breaking lines at a space near the display's 64 columns.
 *
 * It uses only the text display (0x5C), the keyboard (0xF0) and the port: no
 * timer, no interrupts, no disk. It waits for the port by polling. A reply char costs
 * about 21 instructions here (140 with stdio's putchar and a word buffer).
 *
 * Keys: Enter sends the line, Backspace edits it, Ctrl-X stops a reply that is
 * coming, Ctrl-D on an empty line ends (the CPU halts). Lines starting with /
 * are commands for the PC side (/help lists them; /new starts a new
 * conversation, which this program does itself, without a round trip).
 *
 * The same program runs in the simulator, whose Claude device is at 0x9C:
 *   python cpu_sim/src/main.py compiler/ROM/claude_term.rom --claude-system logisim/claude/system.md
 * (needs the `anthropic` package and a key on the PC for the real thing).
 */
#include <stdio.h>
#include <string.h>
#include <cpu.h>

#ifndef PORT
#define PORT CLAUDE_DEVICE      /* the port's device address */
#endif
#define WIDTH 64                /* the text display's columns */
#define LINE_MAX 200
#define CTRL_X 24
#define CTRL_D 4

static char line[LINE_MAX];
static int col;                 /* the display's column: 0 at the start of a line */
static int ahead[LINE_MAX];     /* keys typed while a reply came in (key_pressed() takes them off the keyboard) */
static int n_ahead, i_ahead;

static int next_key(void)       /* type-ahead first, then wait for the keyboard */
{
    if (i_ahead < n_ahead)
        return ahead[i_ahead++];
    n_ahead = i_ahead = 0;
    return wait_key();
}

static void show(int c)
{
    putchar(c);
    col = c == '\n' ? 0 : col + 1;
}

static void new_line(void)
{
    if (col) {
        device_out(DISPLAY_DEVICE, '\n');
        col = 0;
    }
}

static void send(const char *s)
{
    while (*s)
        device_out(PORT, *s++);
    device_out(PORT, CLAUDE_SEND);
}

/* the reply, up to the 4 that ends the turn; Ctrl-X asks the PC to stop it. Each
   char goes straight to the display (stdio costs over a hundred instructions a
   char and this CPU runs a few hundred a second); the usual char comes first in
   the loop and nothing is called for it. A space in the last 12 columns becomes
   the line break; the display wraps a longer word by itself. */
static void reply(void)
{
    int c, k, stopped = 0;
    for (;;) {
        c = device_in(PORT);
        if (c >= ' ') {
            if (c == ' ' && col >= WIDTH - 12) {
                c = '\n';
                col = 0;
            } else if (++col == WIDTH)
                col = 0;
            device_out(DISPLAY_DEVICE, c);
            continue;
        }
        if (c == 0) {
            k = key_pressed();
            if (k == CTRL_X) {
                if (!stopped)
                    device_out(PORT, CLAUDE_STOP);
                stopped = 1;
            } else if (k && n_ahead < LINE_MAX)     /* shortcut: keys past LINE_MAX during one reply are dropped */
                ahead[n_ahead++] = k;
            continue;
        }
        if (c == CLAUDE_END)
            break;
        if (c == '\n') {
            col = 0;
            device_out(DISPLAY_DEVICE, c);
        } else if (c == CLAUDE_TOOL) {          /* tools are off on the PC; if one comes, say no */
            while (device_in(PORT) != CLAUDE_STOP)
                ;
            send("tools are not available here");
        }
    }
    new_line();
}

/* one line from the keyboard, echoed; 0 for Ctrl-D on an empty line */
static int read_line(void)
{
    int n = 0, k;
    for (;;) {
        k = next_key();
        if (k == CTRL_D && n == 0)
            return 0;
        if (k == '\n' || k == '\r') {
            show('\n');
            break;
        }
        if (k == '\b' || k == 127) {
            if (n > 0) {
                n--;
                putchar('\b');
                col--;
            }
        } else if (k >= ' ' && k < 127 && n < LINE_MAX - 1) {
            line[n++] = k;
            show(k);
        }
    }
    line[n] = 0;
    return 1;
}

int main(void)
{
    device_out(PORT, CLAUDE_HELLO);             /* a program starts: drop what is left of an old turn */
    puts("Claude through a port. /help lists commands, /new starts over,");
    puts("Ctrl-X stops a reply, Ctrl-D ends.");
    for (;;) {
        fputs("you> ", stdout);
        col = 5;
        if (!read_line())
            break;
        col = 0;
        if (line[0] == 0)
            continue;
        if (strcmp(line, "/new") == 0) {
            device_out(PORT, CLAUDE_NEW);
            puts("(a new conversation)");
            continue;
        }
        send(line);
        reply();
    }
    new_line();
    halt();
    return 0;
}
