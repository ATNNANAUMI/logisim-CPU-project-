/* guess.c - guess the number (1 to 100), with keyboard input
 *
 *   python run.py build compiler/examples/c/guess.c      (then type in the window)
 *   python compiler/src/cc run compiler/examples/c/guess.c --keys $'x50\nabc\n1\n'
 *
 * The first key seeds the random numbers: how long you take to press it is
 * the only randomness the CPU has. Then type guesses and Enter. With the
 * keys above (all typed before the start, so the seed is 0 and the number
 * is 1) the display shows:
 *   guess the number (1-100)
 *   press a key to start
 *   guess: 50
 *   lower
 *   guess: abc
 *   that's not a number
 *   guess: 1
 *   got it in 2 tries
 */
#include <stdio.h>
#include <stdlib.h>
#include <cpu.h>

int main(void)
{
    unsigned waited = 0;
    int secret, guess, tries = 0;

    printf("guess the number (1-100)\npress a key to start\n");
    while (!key_pressed())
        waited++;
    srand(waited);
    secret = rand() % 100 + 1;

    for (;;) {
        printf("guess: ");
        if (scanf("%d", &guess) != 1) {
            printf("that's not a number\n");
            while (getchar() != '\n')
                ;
            continue;
        }
        tries++;
        if (guess < secret)
            printf("higher\n");
        else if (guess > secret)
            printf("lower\n");
        else
            break;
    }
    printf("got it in %d tries\n", tries);
    return 0;
}
