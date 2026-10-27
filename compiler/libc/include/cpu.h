/* cpu.h - things only this CPU has (not standard C)
 *
 *   show_hex(v)        show v on the 8-digit hex display (device 0x3C)
 *   key_pressed()      the next key if one was typed, else 0; no waiting,
 *                      no echo (getchar waits for a whole line)
 *   wait_key()         wait for one key and return it, no echo
 *   device_out(d, v)   send v to output device d (COMM OUTADDR/OUTDATA)
 *   device_in(d)       read one word from input device d (0 if it has none)
 *   wait_ms(ms)        do nothing for ms milliseconds (the timer, device 0x7C;
 *                      clock() in time.h reads it too)
 *   halt()             stop the CPU (RESUME continues after it)
 *
 * The disk (simulator only, run with --disk FILE): device_out(DISK_SEEK_DEVICE, n)
 * goes to word n; device_in(DISK_SEEK_DEVICE) is the disk's size in words.
 * device_out/device_in on DISK_DATA_DEVICE write/read one word and move on
 * to the next one. Past the end, reads give 0 and writes are dropped.
 * A formatted disk holds a filesystem (stdio.h's fopen, TFS1): raw writes
 * to it can break it.
 */
#ifndef _CPU_H
#define _CPU_H

#define DISPLAY_DEVICE 0x5C
#define HEX_DEVICE 0x3C
#define KEYBOARD_DEVICE 0xF0
#define TIMER_DEVICE 0x7C
#define DISK_SEEK_DEVICE 0x8C
#define DISK_DATA_DEVICE 0x8D

#define device_out(d, v) __builtin_out((d), (v))
#define device_in(d) __builtin_in(d)
#define halt() __builtin_trap()

void show_hex(unsigned int value);
int key_pressed(void);
int wait_key(void);
void wait_ms(unsigned int ms);

#endif
