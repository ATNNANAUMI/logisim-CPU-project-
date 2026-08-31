import re
from pathlib import Path

# Define opcode maps based on instruction format
opcode_map = {
    # Integer ALU
    'ADD':    '010000', 'SUB': '010001', 'MULT': '010010', 'DIV': '010011',
    'SHL':    '010100', 'SHR': '010101', 'NOT': '010110', 'AND': '010111',
    'OR':     '011000', 'XOR': '011001', 'MOD': '011010', '++':  '011011',
    '--':     '01100', 'NEG': '011101', 'CMP': '011111', 'IADD': '1000000',

    # Float ALU
    'ADD.F':  '110000', 'SUB.F': '110001', 'MULT.F': '110010', 'DIV.F': '110011',
    'SHL.F':  '110100', 'SHR.F': '110101', 'FLOAT': '110110', 'INT': '110111',
    '++F':    '111011', '--F': '111100', 'NEG.F': '111101', 'CMP.F': '111111',

    # Memory
    'LD':     '000001', 'ST': '000010', 'DATA': '000011',
    'ALD':    '001100', 'AST': '001101', 'CPY': '001110',

    # Control
    'NOP':    '000000', 'JMRB': '000100', 'RJMP': '000100', 'RJF': '000101', 'RJNF': '000110',
    'CLF':    '000111', 'JMRB': '001010', 'HALT': '001111', 'ADDR': '001001',

    # Stack
    'STK':    '0010110',

    # Comm
    'COMM':   '001000'
}

# Register encoding
registers = {f'R{i}': f'{i:04b}' for i in range(16)}

# Flags
flag_bits = {'C': '1', 'A': '1', 'E': '1', 'Z': '1'}

# Stack opcodes
stk_ops = {'PUSH': '000', 'POP': '001', 'CALLF': '010', 'RETF': '011', 'SET': '100', 'GET': '101'}

# COMM modes
comm_modes = {'INDATA': '00', 'INADDR': '01', 'OUTDATA': '10', 'OUTADDR': '11'}

composite_instructions = {
    'PUSH': ['STK PUSH ARG1'],
    'POP': ['STK POP ARG1'],
    'CALL': ['STK CALLF', 'ADDR R0', 'DATA R1, 0x6', 'ADD R1, R0', 'PUSH R0','JMP ARG1'],# last JMP is to the function address, not yet implemented
    'RET': ['DATA R0, 0x1', 'STK GET R0', 'STK RETF', 'JMRB R0'], # load 1 into R0, get it(index in r0, get to rb), return from function, jump to address in R0
    
}

# Fixing formatting error when opcode is already a string (not int)
def assemble_line_fixed(line):
    line = line.strip()
    if not line or line.startswith(';'):
        return None
    elif line.startswith('.DBYTE'):
        byte = int(line.split()[1], 16)
        return [f'{byte:16b}']
    elif line.startswith('.BYTE'):
        byte = int(line.split()[1], 16)
        return [f'{byte:08b}']
    tokens = re.split(r'[,\s]+', line)
    inst = tokens[0].upper()
    args = tokens[1:]

    # Check for composite instruction
    if inst in composite_instructions:
        expanded = []
        # Map ARG1, ARG2, ... to actual user-supplied values
        arg_map = {f'ARG{i+1}': arg for i, arg in enumerate(args)}
        for template in composite_instructions[inst]:
            # Replace placeholders
            formatted = template
            for key, value in arg_map.items():
                formatted = formatted.replace(key, value)
            # Recursively assemble the real instruction
            expanded.extend(assemble_line_fixed(formatted))
        return expanded

    # Native instructions
    elif inst in {'CLF', 'HALT', 'NOP'}:
        return [opcode_map[inst] + '00000000']
    elif inst == 'RJMP':
        if args[0].startswith('0x'):
            hex_byte = bin(int(args[0], 16))[2:].upper().zfill(2)
            return [opcode_map[inst] + '00000000'] + [hex_byte]
        else:   # If not hex, assume it's a function label (uncertain if will keep this check here or put in compiler)
            print("JMP to function label not implemented")
            return None
    elif inst == 'DATA':                  # handle DATA instruction, DATA Rn, value (0x, 0b, 0d for hex, binary, decimal, none for decimal)
        rb = registers[tokens[1]]
        value = tokens[2]
        if value.startswith('0x'):
            byte = int(value, 16)
        elif value.startswith('0b'):
            byte = int(value, 2)
        elif value.startswith('0d'):
            byte = int(value[2:], 10)
        else:
            byte = int(value, 10)
        hex_byte = bin(byte)[2:].upper().zfill(4)
        return [opcode_map[inst] + '0000' + rb, hex_byte]
    elif inst == 'ADDR':
        rb = registers[tokens[1]]
        return [opcode_map[inst] + '0000' + rb]
    elif inst == 'JMRB':
        rb = registers[tokens[1]]
        return [opcode_map[inst] + '0000' + rb]
    elif inst in {'RJF', 'RJNF'}:
        flags = tokens[1]
        value = tokens[2]
        if value.startswith('0x'):
            byte = int(value, 16)
        elif value.startswith('0b'):
            byte = int(value, 2)
        elif value.startswith('0d'):
            byte = int(value[2:], 10)
        else:
            byte = int(value, 10)
        hex_byte = bin(byte)[2:].upper().zfill(4)
        bits = ''.join(['1' if f in flags else '0' for f in 'CAEZ'])
        return [opcode_map[inst] + '0000' + bits] + [hex_byte]
    elif inst == 'COMM':
        mode = comm_modes[tokens[1]]
        rb = registers[tokens[2]]
        return [opcode_map[inst] + '00' + mode + rb]
    elif inst == 'STK':
        op = stk_ops[tokens[1]]
        if op == '010' or op == '011':  # CALLF RETF
            return [opcode_map[inst] + op + '0000']
        rb = registers[tokens[2]]
        return [opcode_map[inst] + op + rb]
    elif inst == 'IADD':
        ra = registers[tokens[1]]
        if args[1].startswith('0x'):
            hex_byte = bin(int(args[1], 16))[2:].upper().zfill(2)
        return [opcode_map[inst] + ra + '0000'] + [hex_byte]
    elif inst in opcode_map:
        ra = registers[tokens[1]]
        rb = registers[tokens[2]]
        base_opcode = opcode_map[inst]
        return [base_opcode + ra + rb]

    raise ValueError(f"Unknown instruction: {line}")


def assemble_code_fixed(asm_code):
    binary_output = []
    for line in asm_code.splitlines():
        result = assemble_line_fixed(line)
        if result:
            binary_output.append(result)
    return binary_output
# Reassemble the example code
"""
; MAIN ROUTINE
DATA R1, 0x12
PUSH R1

DATA R2, 0x34
PUSH R2

DATA R4, 0x1
STK GET R4
DATA R5, 0x2
STK GET R5

POP R3
POP R4

CALL 0x17

; FUNCTION (at address 0x10 = 16)
DATA R6, 0xFF
RET
"""
asm_example = """
;test
DATA R1, 0x10
DATA R1, 0x10
DATA R1, 0x10
RJMP, 0x10 
"""

binary_matrice = assemble_code_fixed(asm_example)
#binary_code = []
def flatten_recursive(nested):
    flat = []
    for item in nested:
        if isinstance(item, list):
            flat.extend(flatten_recursive(item))
        else:
            flat.append(item)
    return flat

flat_binary = flatten_recursive(binary_matrice)

hex_code = [
    hex(int(bin_line, 2))[2:].upper().zfill((len(bin_line) + 3) // 4)
    for bin_line in flat_binary
]

path = r'C:\codes\cpu\compiler\output.txt'
with open(path, "w+", encoding="utf-8") as file:
    file.write("v2.0 raw\n")
    col = 0
    for instruction in hex_code:
        instruction = instruction.zfill(3)
        file.write(instruction + (" " if col < 7 else "\n"))
        col = (col + 1) % 8
    #file.write('\n')
    #file.write('\n'.join(binary_code))+++