/* mem_test.c - the RAM and its 24 address lines on the real circuit
 *
 * Build and run (from the project root):
 *   python compiler/src/cc build logisim/tests/mem_test.c
 *   python logisim/run_rom.py logisim/CPU.circ compiler/ROM/mem_test.rom
 * or in the simulator:  python compiler/src/cc run logisim/tests/mem_test.c
 *
 * Writes through pointers to absolute addresses, so it only builds with this
 * compiler (RAM word i is at 0x1000000 + i; the program's data and stack are in
 * the first 0x4100 words, which it leaves alone). One line per group, ok or FAIL,
 * and a last line:
 *   data bits   walking ones and zeros and the two checkerboards, all 32 bits
 *   addresses   one word at 0x1000000 | (1 << k) for each k from 15 to 23, then all
 *               read back: an address line that is not wired makes two of them the
 *               same word and one value is lost
 *   carries     arrays that run across a 16-bit, a 20-bit and a 23-bit boundary
 *               (the carry of the address adder)
 *   top         the last 16 words of RAM, 0x1FFFFF0 to 0x1FFFFFF
 *   malloc      blocks from the heap, filled and checked, freed and reused
 * About 28 000 instructions, a minute on the circuit.
 */
#include <stdio.h>
#include <stdlib.h>

static int failures;

static void check(const char *name, int ok)
{
    fputs(name, stdout);
    puts(ok ? " ok" : " FAIL");
    if (!ok)
        failures++;
}

static int run_ok(unsigned *p, int n, unsigned seed)
{
    int i, ok = 1;
    for (i = 0; i < n; i++)
        p[i] = seed + (unsigned)i * 0x01010101u;
    for (i = 0; i < n; i++)
        if (p[i] != seed + (unsigned)i * 0x01010101u)
            ok = 0;
    return ok;
}

int main(void)
{
    unsigned *p, *q;
    int i, k, ok;

    p = (unsigned *)0x1100000;
    ok = 1;
    for (i = 0; i < 32; i++) {
        p[0] = 1u << i;
        if (p[0] != 1u << i)
            ok = 0;
        p[0] = ~(1u << i);
        if (p[0] != ~(1u << i))
            ok = 0;
    }
    p[1] = 0xAAAAAAAAu;
    p[2] = 0x55555555u;
    p[3] = 0xFFFFFFFFu;
    p[4] = 0;
    if (p[1] != 0xAAAAAAAAu || p[2] != 0x55555555u || p[3] != 0xFFFFFFFFu || p[4] != 0)
        ok = 0;
    check("data bits", ok);

    ok = 1;
    *(unsigned *)0x1005000 = 0x0BADC0DEu;
    for (k = 15; k < 24; k++)
        *(unsigned *)(0x1000000u | (1u << k)) = 0x01010101u * (unsigned)(k + 1);
    for (k = 15; k < 24; k++)
        if (*(unsigned *)(0x1000000u | (1u << k)) != 0x01010101u * (unsigned)(k + 1))
            ok = 0;
    if (*(unsigned *)0x1005000 != 0x0BADC0DEu)
        ok = 0;
    check("address lines 15 to 23", ok);

    ok = 1;
    ok = run_ok((unsigned *)0x100FFF0, 32, 0x10000000u) && ok;     /* across bit 16 */
    ok = run_ok((unsigned *)0x10FFFF0, 32, 0x20000000u) && ok;     /* across bit 20 */
    ok = run_ok((unsigned *)0x17FFFF0, 32, 0x30000000u) && ok;     /* across bit 23 */
    check("arrays across 16, 20 and 23-bit boundaries", ok);

    ok = run_ok((unsigned *)0x1FFFFF0, 16, 0x40000000u);
    check("top of RAM", ok);

    ok = 1;
    p = (unsigned *)malloc(300);
    q = (unsigned *)malloc(300);
    if (p == 0 || q == 0 || p == q || (unsigned)p < 0x1000000u || (unsigned)q < 0x1000000u)
        ok = 0;
    else {
        ok = run_ok(p, 300, 0x50000000u) && ok;
        ok = run_ok(q, 300, 0x60000000u) && ok;
        for (i = 0; i < 300; i++)                           /* the first block was not touched */
            if (p[i] != 0x50000000u + (unsigned)i * 0x01010101u)
                ok = 0;
        free(p);
        free(q);
        p = (unsigned *)malloc(300);
        ok = p != 0 && run_ok(p, 300, 0x70000000u) && ok;
        free(p);
    }
    check("malloc, free and reuse", ok);

    puts(failures ? "SOME CHECKS FAILED" : "all checks passed");
    return failures != 0;
}
