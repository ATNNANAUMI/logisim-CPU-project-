/* keys_test.c - the keyboard on the real circuit (type on it)
 *
 * Build and run (from the project root):
 *   python compiler/src/cc build logisim/tests/keys_test.c
 * then load compiler/ROM/keys_test.rom in Logisim, start the clock and type in
 * the keyboard component (headless runs have no keyboard), or in the simulator:
 *   python compiler/src/cc run logisim/tests/keys_test.c --keys $'abc 123\n'
 *
 * Reads one line and prints each character as two hex digits, then the length.
 * Typing "abc 123" and Enter must print
 *   61 62 63 20 31 32 33
 *   7 characters
 * (the codes are ASCII; Enter ends the line and is not printed; Backspace edits
 * the line). Then it reads a second line the same way, until an empty one.
 */
#include <stdio.h>

int main(void)
{
    char line[64];
    int n;

    puts("type a line and press Enter (an empty line ends)");
    for (;;) {
        if (fgets(line, 64, stdin) == 0)
            break;
        n = 0;
        while (line[n] != '\n' && line[n] != 0) {
            printf("%02X ", (unsigned)line[n]);
            n++;
        }
        if (n == 0)
            break;
        printf("\n%d characters\n", n);
    }
    puts("done");
    return 0;
}
