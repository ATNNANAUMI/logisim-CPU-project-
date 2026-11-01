"""Machine sizes and the few behaviours that were not fully pinned down.

The "TWEAKS" block holds behaviours that can be switched.  Each says whether
it is confirmed on the circuit or still a guess; flip a guess here if the
real circuit does something else.
"""

# ---------------------------------------------------------------- hardware
WORD_BITS = 32
WORD_MASK = 0xFFFFFFFF
SIGN_BIT = 1 << 31

# Each bank (ROM and RAM) has a 24-bit address: 16M words each. The IAR is
# one bit wider, and that top bit selects RAM. The linker has the same
# layout (compiler/src/asm/linker.py); change both together. The circuit
# still has 16-bit banks (TECHNICAL.md 2.4 lists what to widen).
BANK_BITS = 24
BANK_WORDS = 1 << BANK_BITS    # 16M words of ROM and 16M words of RAM
BANK_MASK = BANK_WORDS - 1
ADDR_BITS = BANK_BITS + 1      # IAR is 25 bits: bit 24 selects RAM
ADDR_MASK = (1 << ADDR_BITS) - 1
RAM_BIT = 1 << BANK_BITS
ADDR_DIGITS = (ADDR_BITS + 3) // 4   # hex digits in a printed address

STACK_WORDS = 1 << 14          # the bottom 16K words of RAM, 14-bit index
STACK_MASK = STACK_WORDS - 1
# STK SET/GET reach the RAM word EBP + RB, and that sum wraps at the RAM's
# address width, across all of RAM, not at the stack area's 14 bits
# (measured on the 16-bit circuit with diag11 and diag16, 2026-10-13; with
# 24-bit banks it is taken to wrap at 24).
STACK_INDEX_MASK = BANK_MASK

DISPLAY_ADDR = 0x5C
HEX_DISPLAY_ADDR = 0x3C       # 8-digit hex display: shows the last word sent
KEYBOARD_ADDR = 0xF0           # its decoder wants bits 0-3 = 0, bits 4-7 = 1

# RGB Video (565 colour), RGB_Display on the circuit (2026-10-22): each word
# sent to VIDEO_ADDR is one pixel, x in bits 31-24, y in 23-16, colour in
# 15-0: with 256 x 256 pixels (2026-10-31) all 32 bits are used. Any word
# sent to VIDEO_CLEAR_ADDR pulses the component's reset (all black); that
# one isn't built on the circuit yet.
VIDEO_ADDR = 0x6C
VIDEO_CLEAR_ADDR = 0x6D
VIDEO_WIDTH = 256              # powers of two, 256 at most (x and y are 8 bits each)
VIDEO_HEIGHT = 256

# Timer (planned wiring, not on the circuit yet): INDATA from TIMER_ADDR
# reads milliseconds since reset, wrapping at 32 bits (C's clock()). The
# simulator follows the computer's real clock and stops it while paused.
TIMER_ADDR = 0x7C

# Disk (simulator only: Logisim's RAM can't keep its contents in a file).
# OUTDATA to DISK_SEEK_ADDR sets the word position; INDATA from it reads the
# disk's size in words. DISK_DATA_ADDR moves one word: OUTDATA writes it,
# INDATA reads it, and both move the position on by one. Past the end, reads
# give 0 and writes are dropped. The disk is a binary file, 4 bytes per word,
# little-endian; a missing file is created (sparse) with DISK_WORDS words.
DISK_SEEK_ADDR = 0x8C
DISK_DATA_ADDR = 0x8D
DISK_WORDS = 1 << 24           # 64 MB
DISK_MAX_WORDS = 1 << 30       # 4 GB, 30-bit word positions

# ------------------------------------------------------------------ TWEAKS
# A flag = "RA > RB".  Signed compare (True) or unsigned magnitude (False)?
# Confirmed: signed.
A_FLAG_SIGNED = True

# SHR: logical (False) or arithmetic / sign-preserving (True)?
# Confirmed on the circuit (2026-10-02): logical, the top bit fills with 0.
SHR_ARITHMETIC = False

# Integer DIV/MOD rounding: truncate toward zero (True, C-like) or floor.
# Confirmed on the circuit (2026-10-02): truncate, so MOD keeps the
# dividend's sign (-7 MOD 3 = -1).
DIV_TRUNCATE = True

# Confirmed on the circuit (2026-10-02): ESP and EBP are 14-bit registers,
# so they overflow and wrap.  True stops the simulated CPU instead, which
# can help catch a runaway stack while debugging.  (STK SET/GET add EBP and
# RB in a wider sum that wraps across all of RAM: see STACK_INDEX_MASK.)
STOP_ON_STACK_WRAP = False

# Float opcodes with no defined result write this to R0. Confirmed on the
# circuit (2026-10-13, diag16/diag17) for 1000, 1001, 1010 and 1110. Of the
# float ops that "do nothing": SHL doubles RB (alu.py does that too); SHR,
# ++ and -- read back as FFFFFFFF with N and Z both on, which looks like an
# undriven bus, so the simulator doesn't copy it and writes this instead.
FLOAT_NOP_RESULT = 0
