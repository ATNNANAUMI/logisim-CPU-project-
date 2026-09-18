#   Machine Code Reader, input a rom input file or a sequence of machine code(in hex)
#   and outputs what each instruction does


input = '''v2.0 raw
00000b10 00000700 00001401 00000608 00000007 00000500 00000008 00001d00
00000b40
'''

instr_dict= {
    '30': 'FLOAT ADD RA AND RB OUTPUT IN RB',
    '31': 'FLOAT SUBTRACT ( RA - RB ) OUTPUT IN RB',
    '32': 'FLOAT MULTIPLICATE RA AND RB OUTPUT IN RB',
    '33': 'FLOAT DIVISION( RA / RB )',
    '34': 'FLOAT SHIFT LEFT RA AND STORE IN RB',
    '35': 'FLOAT SHIFT RIGHT RA AND STORE IN RB',
    '36': 'INT TO FLOAT',
    '37': 'FLOAT TO INT',
    '3b': 'INCREMENT RA AND STORE IN RB',
    '3c': 'DECREMENT RA AND STORE IN RB',
    '3d': 'TWO`S COMPLEMENT NEGATE RA AND STORE IN RB',
    '3f': 'COMPARE RA AND RB',
    '10': 'ADD RA AND RB OUTPUT IN RB',
    '11': 'SUBTRACT ( RA - RB ) OUTPUT IN RB',
    '12': 'MULTIPLICATE RA AND RB OUTPUT IN RB',
    '13': 'DIVISION( RA / RB ) INTEGER',
    '14': 'SHIFT LEFT RA AND STORE IN RB',
    '15': 'SHIFT RIGHT RA AND STORE IN RB',
    '16': 'BITWISE NOT RA AND STORE IN RB',
    '17': 'BITWISE RA AND RB ',
    '18': 'BITWISE RA OR RB',
    '19': 'BITWISE EXCLUSIVE OR',
    '1a': 'RA MODULUS RB',
    '1b': 'INCREMENT RA AND STORE IN RB',
    '1c': 'DECREMENT RA AND STORE IN RB',
    '1d': '2S COMPLEMENT NEGATE RA AND STORE IN RB',
    '1e': 'nothing',
    '1f': 'COMPARE RA AND RB',
    '00': 'NO OPERATION(DOES NOTHING)',
    '01': 'LOAD RB FROM RAM ADDR IN RA',
    '02': 'STORE RB TO RAM ADDR IN RA',
    '03': 'LOAD NEXT BYTE TO RB',
    '04': 'JUMP TO THE ADDRESS IN RB',
    '05': 'JUMP TO THE ADDRESS IN THE NEXT BYTE',
    '06': 'JUMP IF ANY TESTED FLAG IS ON ( RB )',
    '07': 'CLEAR ALL FLAGS IN FLAG REG',
    '08': 'RA RB',
    '09': 'GET ADDRESS FROM IAR TO RB',
    '0a': 'JUMP IF ANY TESTED FLAG IS OFF ( RB )',
    '0b': 'STACK MEMORY OPERATIONS, RA RB',
    '0c': 'LOAD VALUE FROM ARRAY WITH ADDRESS IN RA AND INDEX IN RB TO REGISTER 0',
    '0d': 'STORE VALUE TO ARRAY WITH ADDRESS IN RA AND INDEX IN RB FROM REGISTER 0',
    '0e': 'COPY CPU REGISTER RA TO RB',
    '0f': 'HALT CPU UNTIL RESUME SIGNAL IS ENABLED'
}

input = input.replace('\n', ' ')
input = input.replace('v2.0 raw ', '')
input = input.split(' ')
jump = 0
registers = [0]*16
instr = ""
for el in input:
    if(jump == 1):
        jump = 0
        print(el)
        continue
    el = el.zfill(4)
    arg_a = 'r' + str(int(el[-2], 16))
    arg_b = 'r' + str(int(el[-1], 16))
    code = el[-4:-2:1].lower()
    instr = instr_dict.get(code)
    if (code == '06' or code == '0a'):
        arg_b = []
        bin = list(format(int(el[-1], 16), 'b').zfill(4))
        if(int(bin[0])):
            arg_b += ['carry']
        if(int(bin[1])):
            arg_b += ['A greater than B']
        if(int(bin[2])):
            arg_b += ['A equal to B']
        if(int(bin[3])):
            arg_b += ['zero']
        arg_b = ', '.join(arg_b)
    if(code == '08'):
        arg_a = []
        bin = list(format(int(el[-2], 16), 'b').zfill(2))
        if(int(bin[0])):
            arg_a += ['OUTPUT']
        else:
            arg_a += ['INPUT']
        if(int(bin[1])):
            arg_a += ['ADDRESS']
        else:
            arg_a += ['DATA']
        if(int(bin[0])):
            arg_a += ['TO PERIPHERAL FROM']
        else:
            arg_a += ['FROM PERIPHERAL TO']
        arg_a = ' '.join(arg_a)
    if(code == '0b'):
        bin = el[-2]
        if(int(bin == '0')):
            arg_a = 'push'
        elif(int(bin == '1')):
            arg_a = 'pop'
        elif(int(bin == '2')):
            arg_a = 'callFrame'
        elif(int(bin == '3')):
            arg_a = 'retFrame'
        elif(int(bin == '4')):
            arg_a = 'set from'
        elif(int(bin == '5')):
            arg_a = 'get to'
    instr = instr.split()
    instr = list(map(lambda x: arg_a if x == 'RA' else x, instr))
    instr = list(map(lambda x: arg_b if x == 'RB' else x, instr))
    instr = ' '.join(instr)
    if (instr == None):
        print('error, no such instruction')
        continue
    print(instr)
    if ('NEXT BYTE' in instr):
        jump = 1
