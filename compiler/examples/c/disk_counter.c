/* disk_counter.c - the disk device (simulator only): adds 1 to word 1000 of
 * the disk, so every run on the same disk image counts one more
 *
 *   python compiler/src/cc run compiler/examples/c/disk_counter.c --disk test.img
 *   (or, after cc run/build: python cpu_sim/src/main.py compiler/ROM/disk_counter.rom
 *    and the window's "disk" button)
 *
 * prints:  disk: 16777216 words, this program ran 0 times before
 *          (then 1, 2, ... on the same image; a new image is 64 MB, sparse)
 *          without --disk: no disk (run with --disk FILE)
 */
#include <stdio.h>
#include <cpu.h>

int main(void)
{
    int size = device_in(DISK_SEEK_DEVICE);      /* 0: no disk attached */
    if (size == 0) {
        printf("no disk (run with --disk FILE)\n");
        return 1;
    }
    device_out(DISK_SEEK_DEVICE, 1000);
    int count = device_in(DISK_DATA_DEVICE);     /* the position moves on to 1001 */
    device_out(DISK_SEEK_DEVICE, 1000);
    device_out(DISK_DATA_DEVICE, count + 1);
    printf("disk: %d words, this program ran %d times before\n", size, count);
    return 0;
}
