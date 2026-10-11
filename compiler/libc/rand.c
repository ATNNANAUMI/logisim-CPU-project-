/* rand, srand: the generator from the C standard's example
 * (next = next * 1103515245 + 12345; bits 16..30 are the result) */
#include <stdlib.h>

static unsigned long next = 1;

int rand(void)
{
    next = next * 1103515245 + 12345;
    return (unsigned)(next / 65536) % 32768;
}

void srand(unsigned int seed)
{
    next = seed;
}
