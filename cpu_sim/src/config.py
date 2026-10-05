"""Machine sizes and the few behaviours that were not fully pinned down.

The "TWEAKS" block holds behaviours that can be switched.  Each says whether
it is confirmed on the circuit or still a guess; flip a guess here if the
real circuit does something else.
"""

# ---------------------------------------------------------------- hardware
WORD_BITS = 32
WORD_MASK = 0xFFFFFFFF
SIGN_BIT = 1 << 31

ADDR_BITS = 17                 # IAR is 17 bits: bit16 selects RAM
ADDR_MASK = (1 << ADDR_BITS) - 1
RAM_BIT = 1 << 16
BANK_WORDS = 1 << 16           # 64K words of ROM and 64K words of RAM

STACK_WORDS = BANK_WORDS // 4  # bottom 25% of RAM, 14-bit index
STACK_MASK = STACK_WORDS - 1

DISPLAY_ADDR = 0x5C
HEX_DISPLAY_ADDR = 0x3C       # 8-digit hex display: shows the last word sent
KEYBOARD_ADDR = 0xF0           # its decoder wants bits 0-3 = 0, bits 4-7 = 1

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
# can help catch a runaway stack while debugging.
# small difference from circuit, circuit wraps the entire ram, not just the registers
STOP_ON_STACK_WRAP = False

# Still a guess: undefined float opcodes (1000, 1001, 1010, 1110) and the
# float ops that "do nothing" (SHL, SHR, ++, --) write this to R0.
FLOAT_NOP_RESULT = 0
