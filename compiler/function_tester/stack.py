#test code for stack memory

stack = []
for _ in range(256):
    stack.append(0)
ebp = 0
esp = 0

def push(value):
    global stack
    global esp
    stack[esp] = value
    esp += 1
    return

def pop():
    global esp
    global stack
    global value
    esp -= 1
    value = stack[esp]

def set(index, num):
    global stack
    global esp
    mar = ebp+index
    stack[mar] = num

def get(index):
    global stack
    global esp
    global value
    mar = ebp+index
    value = stack[mar]
    return value

def callFrame():
    global stack
    global esp
    global ebp
    stack[esp] = ebp
    ebp = esp
    esp += 1
    return

def retFrame():
    global stack
    global ebp
    global esp
    esp = ebp
    ebp = stack[ebp]
    return

if __name__ == '__main__':
    value = 1
    push()
    value = 2
    push()
    value = 4
    push()
    value = 3
    push()
    value = 2
    push()
    value = 10
    push()
    value = 7
    push()
    get()
    callFrame()
    push()
    value = 2
    push()
    value = 4
    push()
    value = 3
    push()
    value = 2
    push()
    value = 1
    push()
    value = 10
    push()
    get()
    get()
    get()
    get()
    callFrame()
    value = 1
    push()
    value = 2
    push()
    value = 4
    push()
    value = 3
    push()
    value = 2
    push()
    value = 10
    push()
    value = 7
    push()
    get()
    retFrame()
    push()
    value = 5
    push()
    get()
    get()
    get()
    get()
    value = 10
    push()
    retFrame()
    