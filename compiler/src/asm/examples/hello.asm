; Print "Hello, world!" and keep the number of characters printed in RAM.
;   python src/asm build examples/asm/hello.asm

        .equ DISPLAY, 0x5C
        .global start

        .ram
count:  .space 1            ; one word of RAM, at 0x14000

        .rom
start:  DATA R2, DISPLAY
        COMM OUTADDR, R2
        DATA R1, msg        ; R1 = address of the string
        DATA R2, 0          ; R2 = index
loop:   ALD R1, R2          ; R0 = mem[msg + index]
        TEST R0             ; stop at the 0 at the end
        RJF Z, done
        COMM OUTDATA, R0
        ++ R2
        CPY R0, R2
        RJMP loop
done:   DATA R3, count
        ST R3, R2           ; count = number of characters
        HALT

msg:    .string "source files (order = link order) (numbers, e.g. 1 3): 3 4output: compiler/src/asm/examples/two_files/lib.rom$ python /home/arthur/projects/logisim-CPU-project-/compiler/src/asm build /home/arthur/projects/logisim-CPU-project-/compiler/src/asm/examples/two_files/lib.asm /home/arthur/projects/logisim-CPU-project-/compiler/src/asm/examples/two_files/main.asm -o /home/arthur/projects/logisim-CPU-project-/compiler/src/asm/examples/two_files/lib.rom/home/arthur/projects/logisim-CPU-project-/compiler/src/asm/examples/two_files/lib.rom: 68 words of ROM, 1 words of RAM[arthur@desknemesis logisim-CPU-project-]$ /usr/bin/python /home/arthur/projects/logisim-CPU-project-/run.py\n"
