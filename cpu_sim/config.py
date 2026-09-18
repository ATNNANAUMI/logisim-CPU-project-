"""Machine sizes and the few behaviours that were not fully pinned down.

Everything in the "TWEAKS" block is a guess; flip it here if the real
circuit does something else.
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
KEYBOARD_ADDR = 0x0F

# ------------------------------------------------------------------ TWEAKS
# A flag = "RA > RB".  Signed compare (True) or unsigned magnitude (False)?
A_FLAG_SIGNED = True

# SHR: logical (False) or arithmetic / sign-preserving (True)?
SHR_ARITHMETIC = False

# Integer DIV/MOD rounding: truncate toward zero (True, C-like) or floor.
DIV_TRUNCATE = True

# Stack currently wraps on overflow/underflow.  Set True to stop the CPU
# instead (the "maybe the circuit should stop" idea).
STOP_ON_STACK_WRAP = False

# Undefined float opcodes (1000, 1001, 1010, 1110) and the float ops that
# "do nothing" (SHL, SHR, ++, --) write this to R0.
FLOAT_NOP_RESULT = 0
