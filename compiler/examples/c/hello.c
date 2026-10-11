/* hello.c - the smallest C program
 *
 *   python compiler/src/cc run compiler/examples/c/hello.c
 *   (or: python compiler/src/cc build compiler/examples/c/hello.c, then
 *    python logisim/run_rom.py logisim/CPU.circ compiler/ROM/hello.rom)
 *
 * prints:  hello, world
 */
#include <stdio.h>

int main(void)
{
    printf("hello, world\n");
    return 0;
}
