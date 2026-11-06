/* port_test.c - does the port (the Telnet component behind device 0x9C) work?
 *
 *   python compiler/src/cc build logisim/claude/port_test.c      (-> compiler/ROM/port_test.rom)
 *   python compiler/src/cc build logisim/claude/port_test.c -D PORT=0x9C
 *
 * Load the ROM, start the simulation, run  python logisim/claude/port_test.py
 * (or `nc localhost PORT` and type: every letter comes back with its case
 * flipped). Uses only the text display, the number display and the port.
 *
 * What it does, in a loop: take a byte from the port (device_in gives 0 when
 * there is none), show it on the text display (a newline as a newline, a dot for any other
 * non-printable byte),
 * show how many bytes it has taken so far on the hex display (device 0x3C), and
 * send a byte back:
 *   a letter      the same letter with its case flipped (so you can tell the CPU,
 *                 not the wire, answered)
 *   '#'           the count of bytes taken so far, in decimal, and a newline
 *                 (a burst of bytes followed by # shows how many got through)
 *   anything else the same byte
 *   '?'           "READY\n": the PC asks whether the program is running (the
 *                 component drops what is sent while no client is connected, so
 *                 the program does not announce itself at the start)
 * It never sends a 0 and treats a 0 as "nothing there".
 */
#include <stdio.h>
#include <cpu.h>

#ifndef PORT
#define PORT CLAUDE_DEVICE      /* the port's device address */
#endif

static void out(int c)
{
    device_out(PORT, c);
}

static void out_number(unsigned n)
{
    char digits[12];
    int i = 0;
    do {
        digits[i++] = '0' + n % 10;
        n /= 10;
    } while (n);
    while (i > 0)
        out(digits[--i]);
    out('\n');
}

int main(void)
{
    const char *ready = "READY\n";
    unsigned count = 0;
    int c;

    puts("port test: waiting for bytes");
    for (;;) {
        c = device_in(PORT);
        if (c == 0)
            continue;
        count++;
        show_hex(count);
        device_out(DISPLAY_DEVICE, (c >= ' ' && c < 127) || c == '\n' ? c : '.');
        if (c == '#')
            out_number(count);
        else if (c == '?')
            for (ready = "READY\n"; *ready; ready++)
                out(*ready);
        else if ((c | 0x20) >= 'a' && (c | 0x20) <= 'z')
            out(c ^ 0x20);
        else
            out(c);
    }
}
