/* video_player.c - plays a video made by compiler/src/img/video.py on the
 * RGB screen, at the video's own speed: frame i is drawn when clock() (the
 * timer, in milliseconds) reaches i * 1000 / VIDEO_FPS, and the last one
 * stays up for its share too. Then it prints how many frames came late and
 * how long it all took.
 *
 * pypy3 compiler/src/cc run compiler/examples/c/video_player.c --steps 2000000000
 * python compiler/src/cc build compiler/examples/c/video_player.c, then open
 *     compiler/ROM/video_player.rom in the simulator window ("max" speed)
 *
 * (a program that waits on the clock runs through millions of instructions
 * a second while it waits, hence the big --steps for a run in the terminal)
 *
 * It plays videos/demo.h (ffmpeg's moving test picture, 4 s at 12 frames a
 * second). Your own, from
 * the folder that holds clip.mp4:
 *     python compiler/src/img/video.py clip.mp4          (writes clip.h)
 *     ... video_player.c -I . -D 'VIDEO="clip.h"'        (build or run)
 * A frame drawn more than one frame late counts as late: the CPU (or the
 * simulator) is too slow for it. Frames can't be skipped, as each one draws
 * only what changed, so a late video catches up when frames get cheaper.
 *
 * Expected output (with pypy3; plain python is too slow for 12 frames a
 * second, so most frames come late and it takes longer):
 *   48 frames, 0 late, 4.0 s (the video is 4.0 s)
 */
#include <gfx.h>
#include <stdio.h>
#include <time.h>

#ifndef VIDEO
#define VIDEO "videos/demo.h"
#endif
#include VIDEO

#define TIMES 1         /* how many times to play it; 0 = for ever */

int main(void)
{
    int x = (GFX_WIDTH - VIDEO_WIDTH) / 2, y = (GFX_HEIGHT - VIDEO_HEIGHT) / 2;
    int i, round, late = 0;
    long frames = 0;
    clock_t start, due, took, one = CLOCKS_PER_SEC / VIDEO_FPS;

    gfx_clear();
    start = clock();
    for (round = 0; TIMES == 0 || round < TIMES; round++) {
        for (i = 0; i < VIDEO_FRAMES; i++, frames++) {
            due = start + frames * CLOCKS_PER_SEC / VIDEO_FPS;
            if (clock() - due > one)
                late++;
            while (clock() - due < 0)
                ;
            gfx_image(x, y, video_data + video_start[i]);
        }
    }
    due = start + frames * CLOCKS_PER_SEC / VIDEO_FPS;     /* the last frame's time */
    while (clock() - due < 0)
        ;
    took = clock() - start;
    printf("%ld frames, %d late, %ld.%ld s (the video is %ld.%ld s)\n", frames, late,
           took / 1000, took / 100 % 10, frames / VIDEO_FPS, frames * 10 / VIDEO_FPS % 10);
    return 0;
}
