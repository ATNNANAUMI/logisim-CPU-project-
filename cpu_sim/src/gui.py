"""Tkinter front end: registers, ROM/RAM views, C source, display, keyboard,
controls."""

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import alu as alu
import config as config
from cpu import CPU
from debuginfo import DebugInfo, step_line, step_out
from isa import decode, disassemble
from memory import load_image

PAGE_WORDS = 256
MONO = "TkFixedFont"
MAX_PER_TICK = 100_000         # keeps the window responsive at high speeds
MAX_SLICE = 0.05               # seconds of running per window tick at "max"
STATE_CHARS = 30               # fixed width of the status block, so it never resizes the window

# label -> instructions per second (0 = as fast as the host manages)
SPEEDS = [
    ("1 Hz", 1), ("2 Hz", 2), ("4 Hz", 4), ("8 Hz", 8), ("16 Hz", 16),
    ("32 Hz", 32), ("64 Hz", 64), ("128 Hz", 128), ("256 Hz", 256),
    ("512 Hz", 512), ("1 kHz", 1_000), ("4 kHz", 4_000), ("16 kHz", 16_000),
    ("64 kHz", 64_000), ("256 kHz", 256_000), ("1 MHz", 1_000_000),
    ("max", 0),
]
SPEED_HZ = dict(SPEEDS)


def parse_word(text: str) -> int:
    """Accept 0x1F, 31, -5, 1.5f / 1.5 (stored as float32 bits)."""
    text = text.strip().lower().replace("_", "")
    if not text:
        raise ValueError("empty")
    if text.startswith(("0x", "-0x", "0b", "-0b")):
        return int(text, 0) & config.WORD_MASK      # hex/binary literal
    if text.endswith("f"):
        return alu.float_to_bits(float(text[:-1]))
    if "." in text or "e" in text:
        return alu.float_to_bits(float(text))       # 1.5 or 1e3 -> float32 bits
    return int(text, 0) & config.WORD_MASK


def key_code(keysym: str, char: str) -> int | None:
    """What Logisim's Keyboard would buffer for a key, or None to ignore it.

    Enter gives 0x0A and Backspace 0x08; any other key counts only if it
    types a printable ASCII character (Tab, arrows, Ctrl+... are ignored).
    """
    if keysym in ("Return", "KP_Enter"):
        return 0x0A
    if keysym == "BackSpace":
        return 0x08
    if len(char) == 1 and 32 <= ord(char) < 127:
        return ord(char)
    return None


def buffer_text(codes) -> str:
    """The keys waiting in the buffer, with Enter and Backspace made visible."""
    shown = {0x0A: "⏎", 0x08: "⌫"}
    return "".join(shown.get(c, chr(c) if 32 <= c < 127 else "·") for c in codes)


class MemoryPane(ttk.Frame):
    """A paged hex view of one bank, optionally disassembled."""

    def __init__(self, master, cpu: CPU, bank: str):
        super().__init__(master)
        self.cpu = cpu
        self.bank = bank                      # "rom" or "ram"
        self.page = 0
        self.follow = tk.BooleanVar(value=(bank == "rom"))
        self.disasm = tk.BooleanVar(value=(bank == "rom"))

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=4)
        ttk.Button(bar, text="<", width=3, command=lambda: self.turn(-1)).pack(side="left")
        ttk.Button(bar, text=">", width=3, command=lambda: self.turn(+1)).pack(side="left")
        ttk.Label(bar, text=" address ").pack(side="left")
        self.goto = ttk.Entry(bar, width=10)
        self.goto.pack(side="left")
        self.goto.bind("<Return>", self.jump_to)
        ttk.Button(bar, text="go", width=3, command=self.jump_to).pack(side="left")
        ttk.Checkbutton(bar, text="follow IAR", variable=self.follow).pack(side="left", padx=8)
        ttk.Checkbutton(bar, text="disassemble", variable=self.disasm,
                        command=self.render).pack(side="left")
        ttk.Button(bar, text="clear bp", width=8,
                   command=self.clear_breakpoints).pack(side="left", padx=4)
        ttk.Label(bar, text=" double-click edits, right-click sets a breakpoint"
                  ).pack(side="left")
        self.range_label = ttk.Label(bar, text="")
        self.range_label.pack(side="right")

        self.text = tk.Text(self, font=MONO, wrap="none", height=24, width=54)
        self.text.bind("<Double-Button-1>", self.edit_cell)
        self.text.bind("<Button-3>", self.toggle_breakpoint)
        scroll = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set, state="disabled")
        self.text.tag_configure("current", background="#ffe08a")
        self.text.tag_configure("breakpoint", background="#ffbcbc")
        self.text.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        scroll.pack(side="right", fill="y", pady=(0, 4))

    # -------------------------------------------------------------- paging
    @property
    def words(self):
        return getattr(self.cpu.mem, self.bank)

    @property
    def base(self) -> int:
        return config.RAM_BIT if self.bank == "ram" else 0

    def turn(self, delta: int) -> None:
        self.follow.set(False)
        pages = len(self.words) // PAGE_WORDS
        self.page = max(0, min(pages - 1, self.page + delta))
        self.render()

    def jump_to(self, _event=None) -> None:
        raw = self.goto.get().strip().replace("0x", "")
        if not raw:
            return
        try:
            addr = int(raw, 16)
        except ValueError:
            return
        self.follow.set(False)
        self.page = (addr & config.BANK_MASK) // PAGE_WORDS
        self.render()

    def follow_iar(self) -> None:
        if not self.follow.get():
            return
        iar = self.cpu.iar
        in_this_bank = (self.bank == "ram") == bool(iar & config.RAM_BIT)
        if in_this_bank:
            self.page = (iar & config.BANK_MASK) // PAGE_WORDS

    # -------------------------------------------------------- breakpoints
    def _index_at(self, event) -> int | None:
        line = int(self.text.index(f"@{event.x},{event.y}").split(".")[0])
        index = self.page * PAGE_WORDS + line - 1
        return index if index < len(self.words) else None

    def toggle_breakpoint(self, event) -> None:
        index = self._index_at(event)
        if index is None:
            return
        addr = self.base | index
        marks = self.cpu.breakpoints
        marks.discard(addr) if addr in marks else marks.add(addr)
        self.render()

    def clear_breakpoints(self) -> None:
        self.cpu.breakpoints.clear()
        self.render()

    # ------------------------------------------------------------ editing
    def edit_cell(self, event) -> None:
        index = self._index_at(event)
        if index is None:
            return
        addr = self.base | index
        answer = simpledialog.askstring(
            "edit memory", f"new value for 0x{addr:07X}\n(hex, decimal or 1.5f)",
            initialvalue=f"0x{self.words[index]:08X}", parent=self)
        if answer is None:
            return
        try:
            self.words[index] = parse_word(answer)
        except ValueError:
            messagebox.showerror("edit memory", f"cannot read {answer!r}")
            return
        self.render()

    # ------------------------------------------------------------ drawing
    def render(self) -> None:
        start = self.page * PAGE_WORDS
        end = min(start + PAGE_WORDS, len(self.words))
        iar = self.cpu.iar
        current = None
        lines = []
        marked = []

        skip_next = False
        for offset, index in enumerate(range(start, end)):
            word = self.words[index]
            addr = self.base | index
            if addr == iar:
                current = offset + 1
            mark = " "
            if addr in self.cpu.breakpoints:
                marked.append(offset + 1)
                mark = "*"
            if self.disasm.get():
                if skip_next:
                    skip_next = False
                    text = f"    (literal {self._signed(word)})"
                else:
                    ins = decode(word)
                    operand = self.words[index + 1] if (ins.takes_operand and
                                                        index + 1 < len(self.words)) else None
                    skip_next = ins.takes_operand
                    text = disassemble(word, operand)
                lines.append(f"{mark} 0x{addr:07X}  {word:08X}  {text}")
            else:
                lines.append(f"{mark} 0x{addr:07X}  {word:08X}  "
                             f"{self._signed(word):>12d}  {self._ascii(word)}")

        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines))
        for line in marked:
            self.text.tag_add("breakpoint", f"{line}.0", f"{line}.end")
        if current:
            self.text.tag_add("current", f"{current}.0", f"{current}.end")
            self.text.see(f"{current}.0")
        self.text.configure(state="disabled")
        self.range_label.configure(
            text=f"0x{self.base | start:07X} - 0x{self.base | (end - 1):07X}")

    @staticmethod
    def _signed(word: int) -> int:
        return word - (1 << 32) if word & config.SIGN_BIT else word

    @staticmethod
    def _ascii(word: int) -> str:
        char = word & 0xFF
        return chr(char) if 32 <= char < 127 else "."


class SourcePane(ttk.Frame):
    """The C source of the line being run (from the .map next to the ROM).

    The current line is highlighted; right-click a line to put a breakpoint
    on every piece of code it compiled to.
    """

    def __init__(self, master, cpu: CPU):
        super().__init__(master)
        self.cpu = cpu
        self.info = None
        self.shown = None                      # path in the text box
        self.texts = {}                        # path -> lines (cached)
        self.file_var = tk.StringVar(value="")
        self.follow = tk.BooleanVar(value=True)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=4, pady=4)
        self.files = ttk.Combobox(bar, textvariable=self.file_var, state="readonly", width=40)
        self.files.pack(side="left")
        self.files.bind("<<ComboboxSelected>>", self._pick_file)
        ttk.Checkbutton(bar, text="follow", variable=self.follow).pack(side="left", padx=8)
        ttk.Label(bar, text="right-click sets a breakpoint").pack(side="left")

        self.text = tk.Text(self, font=MONO, wrap="none", height=24, width=52)
        self.text.bind("<Button-3>", self.toggle_breakpoint)
        scroll = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set, state="disabled")
        self.text.tag_configure("current", background="#ffe08a")
        self.text.tag_configure("breakpoint", background="#ffbcbc")
        self.text.tag_configure("code", foreground="#000000")
        self.text.tag_configure("nocode", foreground="#808080")
        self.text.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        scroll.pack(side="right", fill="y", pady=(0, 4))
        self.set_info(None)

    def set_info(self, info) -> None:
        self.info = info
        self.shown = None
        self.texts = {}
        names = info.files if info else []
        self.files.configure(values=[self._short(f) for f in names])
        self.file_var.set("")
        if not info:
            self._show_message("no C line information: build the ROM with\n"
                               "  python compiler/src/cc build prog.c\n"
                               "(it writes prog.map next to prog.rom)")

    @staticmethod
    def _short(path: str) -> str:
        try:
            return os.path.relpath(path)
        except ValueError:
            return path

    def _pick_file(self, _event=None) -> None:
        self.follow.set(False)
        index = self.files.current()
        if index >= 0:
            self.show(self.info.files[index])

    def _show_message(self, text: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.configure(state="disabled")

    def _lines(self, path: str):
        if path not in self.texts:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    self.texts[path] = f.read().splitlines()
            except OSError:
                self.texts[path] = None
        return self.texts[path]

    def show(self, path: str) -> None:
        lines = self._lines(path)
        self.shown = path
        self.file_var.set(self._short(path))
        if lines is None:
            self._show_message(f"cannot read {path}")
            return
        with_code = set(self.info.lines_in(path))
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for n, line in enumerate(lines, 1):
            tag = "code" if n in with_code else "nocode"
            self.text.insert("end", f"{n:5d}  {line}\n", tag)
        self.text.configure(state="disabled")
        self.render()

    def toggle_breakpoint(self, event) -> None:
        if not self.info or not self.shown:
            return
        line = int(self.text.index(f"@{event.x},{event.y}").split(".")[0])
        addresses = self.info.addresses_of(self.shown, line)
        if not addresses:
            return                              # a line with no code
        marks = self.cpu.breakpoints
        if any(a in marks for a in addresses):
            marks.difference_update(addresses)
        else:
            marks.update(addresses)
        self.render()

    def render(self) -> None:
        """Highlight the current line and the lines with breakpoints."""
        if not self.info:
            return
        here = self.info.line_at(self.cpu.iar)
        if here and self.follow.get() and here[0] != self.shown:
            self.show(here[0])                  # calls render again
            return
        if not self.shown or self._lines(self.shown) is None:
            return
        self.text.tag_remove("current", "1.0", "end")
        self.text.tag_remove("breakpoint", "1.0", "end")
        for address in self.cpu.breakpoints:
            at = self.info.line_at(address)
            if at and at[0] == self.shown:
                self.text.tag_add("breakpoint", f"{at[1]}.0", f"{at[1]}.end")
        if here and here[0] == self.shown:
            self.text.tag_add("current", f"{here[1]}.0", f"{here[1]}.end")
            if self.follow.get():
                self.text.see(f"{here[1]}.0")


class SimulatorWindow(tk.Tk):
    def __init__(self, cpu: CPU, rom_path: str | None = None):
        super().__init__()
        self.cpu = cpu
        self.rom_path = rom_path
        self.info = DebugInfo.for_rom(rom_path)
        self.running = False
        self.cpu.bus.timer.pause()      # the timer only runs while the program does
        self._ticks = 0
        self._moved = False             # has anything run since the last start
        self._budget = 0.0              # fractional instructions carried over
        self._last_time = time.perf_counter()
        self._rate_mark = (self._last_time, 0)
        self._rate = 0.0
        self.speed = tk.StringVar(value="1 kHz")
        self.trace_on = tk.BooleanVar(value=True)

        self.title("Logic-gate CPU simulator")
        self.geometry("1250x740")
        self._build()
        self.refresh()
        self.after(20, self._tick)

    # -------------------------------------------------------------- layout
    def _build(self) -> None:
        # three columns with draggable sashes between them; the right column
        # is split again between the outputs and the trace
        columns = ttk.PanedWindow(self, orient="horizontal")
        columns.pack(fill="both", expand=True, padx=6, pady=6)

        left = ttk.Frame(columns)
        columns.add(left, weight=0)
        self._build_controls(left)
        self._build_registers(left)
        self._build_state(left)

        middle = ttk.Notebook(columns)
        columns.add(middle, weight=1)
        self.rom_pane = MemoryPane(middle, self.cpu, "rom")
        self.ram_pane = MemoryPane(middle, self.cpu, "ram")
        self.source_pane = SourcePane(middle, self.cpu)
        middle.add(self.rom_pane, text="ROM")
        middle.add(self.ram_pane, text="RAM")
        middle.add(self.source_pane, text="C source")
        self.source_pane.set_info(self.info)
        if self.info and self.info.lines:
            middle.select(self.source_pane)

        right = ttk.PanedWindow(columns, orient="vertical")
        columns.add(right, weight=1)
        outputs = ttk.Frame(right)
        right.add(outputs, weight=1)
        self._build_display(outputs)
        trace = ttk.Frame(right)
        right.add(trace, weight=0)
        self._build_trace(trace)

    def _build_controls(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="control")
        box.pack(fill="x")

        row1 = ttk.Frame(box)
        row1.pack(fill="x", padx=4, pady=2)
        ttk.Button(row1, text="load ROM", command=self.load_rom).pack(side="left")
        ttk.Button(row1, text="load RAM", command=self.load_ram).pack(side="left", padx=2)
        ttk.Button(row1, text="disk", command=self.load_disk).pack(side="left")
        ttk.Button(row1, text="reset", command=self.reset).pack(side="left", padx=2)

        row2 = ttk.Frame(box)
        row2.pack(fill="x", padx=4, pady=2)
        ttk.Button(row2, text="step", command=self.step).pack(side="left")
        self.run_button = ttk.Button(row2, text="run", command=self.toggle_run)
        self.run_button.pack(side="left", padx=2)
        ttk.Button(row2, text="resume", command=self.resume).pack(side="left")

        row2b = ttk.Frame(box)
        row2b.pack(fill="x", padx=4, pady=2)
        ttk.Label(row2b, text="C line:").pack(side="left")
        ttk.Button(row2b, text="into", width=5,
                   command=lambda: self.step_c("into")).pack(side="left", padx=2)
        ttk.Button(row2b, text="over", width=5,
                   command=lambda: self.step_c("over")).pack(side="left")
        ttk.Button(row2b, text="out", width=5,
                   command=lambda: self.step_c("out")).pack(side="left", padx=2)

        row3 = ttk.Frame(box)
        row3.pack(fill="x", padx=4, pady=2)
        ttk.Label(row3, text="speed").pack(side="left")
        combo = ttk.Combobox(row3, textvariable=self.speed, state="readonly",
                             width=8, values=[label for label, _ in SPEEDS])
        combo.pack(side="left", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._restart_clock())
        ttk.Checkbutton(row3, text="trace", variable=self.trace_on).pack(side="left")

    def _build_registers(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="registers (type a value, Enter)")
        box.pack(fill="x", pady=6)
        self.reg_entries = []
        for i in range(16):
            column = (i // 8) * 2
            ttk.Label(box, text=f"R{i}", font=MONO, width=3).grid(
                row=i % 8, column=column, sticky="w", padx=(6, 0), pady=1)
            entry = ttk.Entry(box, font=MONO, width=11, justify="right")
            entry.grid(row=i % 8, column=column + 1, padx=(0, 6), pady=1)
            entry.bind("<Return>", lambda _e, n=i: self.commit_register(n))
            entry.bind("<FocusOut>", lambda _e, n=i: self.commit_register(n))
            self.reg_entries.append(entry)

    def _build_state(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="state (editable)")
        box.pack(fill="x")

        grid = ttk.Frame(box)
        grid.pack(anchor="w", padx=6, pady=(4, 0))
        self.pointer_entries = {}
        for row, name in enumerate(("IAR", "ESP", "EBP")):
            ttk.Label(grid, text=name, font=MONO, width=4).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(grid, font=MONO, width=11, justify="right")
            entry.grid(row=row, column=1, pady=1)
            entry.bind("<Return>", lambda _e, n=name: self.commit_pointer(n))
            entry.bind("<FocusOut>", lambda _e, n=name: self.commit_pointer(n))
            self.pointer_entries[name] = entry

        flags = ttk.Frame(box)
        flags.pack(anchor="w", padx=6, pady=2)
        ttk.Label(flags, text="flags", font=MONO).pack(side="left")
        self.flag_vars = {}
        for name in ("C", "A", "N", "Z"):
            var = tk.BooleanVar(value=False)
            ttk.Checkbutton(flags, text=name, variable=var,
                            command=self.commit_flags).pack(side="left", padx=2)
            self.flag_vars[name] = var

        self.state_label = ttk.Label(box, font=MONO, justify="left", text="",
                                     width=STATE_CHARS, anchor="w")
        self.state_label.pack(anchor="w", padx=6, pady=4)

    # ------------------------------------------------------------ editing
    def commit_register(self, index: int) -> None:
        entry = self.reg_entries[index]
        try:
            self.cpu.regs[index] = parse_word(entry.get())
        except ValueError:
            pass                                    # bad text: put the old value back
        entry.delete(0, "end")
        entry.insert(0, f"0x{self.cpu.regs[index]:08X}")

    def commit_pointer(self, name: str) -> None:
        entry = self.pointer_entries[name]
        try:
            value = parse_word(entry.get())
            if name == "IAR":
                self.cpu.iar = value & config.ADDR_MASK
            elif name == "ESP":
                self.cpu.esp = value & config.STACK_MASK
            else:
                self.cpu.ebp = value & config.STACK_MASK
        except ValueError:
            pass
        self._show_pointer(name)

    def commit_flags(self) -> None:
        self.cpu.flags = alu.pack_flags(*(self.flag_vars[n].get() for n in ("C", "A", "N", "Z")))

    def _show_pointer(self, name: str) -> None:
        value = {"IAR": self.cpu.iar, "ESP": self.cpu.esp, "EBP": self.cpu.ebp}[name]
        width = config.ADDR_DIGITS if name == "IAR" else 4
        entry = self.pointer_entries[name]
        entry.delete(0, "end")
        entry.insert(0, f"0x{value:0{width}X}")

    def _build_display(self, parent) -> None:
        # the text display and the RGB screen share a notebook; the screen
        # tab comes forward the first time a program draws
        self.outputs = ttk.Notebook(parent)
        self.outputs.pack(fill="both", expand=True)
        box = ttk.Frame(self.outputs)
        self.outputs.add(box, text=f"display (0x{config.DISPLAY_ADDR:02X})")
        video = self.cpu.bus.video
        screen_box = ttk.Frame(self.outputs)
        self.outputs.add(screen_box, text=f"RGB screen (0x{config.VIDEO_ADDR:02X})")
        self.screen_tab = screen_box
        self.screen_zoom = max(1, 384 // max(video.width, video.height))
        self.screen_image = tk.PhotoImage(width=video.width, height=video.height)
        self.screen_big = self.screen_image.zoom(self.screen_zoom)
        # placed, not packed: the picture follows the tab's size (_fit_screen)
        # without its own size ever pushing the tab, and the window, around
        self.screen_label = tk.Label(screen_box, image=self.screen_big, background="#101010")
        self.screen_label.place(relx=0.5, rely=0.5, anchor="center")
        size = self.screen_zoom * max(video.width, video.height) + 8
        screen_box.configure(width=size, height=size)
        screen_box.bind("<Configure>", self._fit_screen)
        self._screen_shown = False
        self.display = tk.Text(box, font=MONO, height=16, wrap="char",
                               background="#101010", foreground="#c8ffc8",
                               insertbackground="#c8ffc8")
        self.display.pack(fill="both", expand=True, padx=4, pady=4)
        self.display.configure(state="disabled")

        hexbox = ttk.LabelFrame(parent, text=f"hex display (0x{config.HEX_DISPLAY_ADDR:02X})")
        hexbox.pack(fill="x")
        self.hex_label = tk.Label(hexbox, font=MONO, text="--------",
                                  background="#101010", foreground="#ff6050")
        self.hex_label.pack(fill="x", padx=4, pady=4)

        keys = ttk.LabelFrame(
            parent, text=f"keyboard (0x{config.KEYBOARD_ADDR:02X}) - click here and type")
        keys.pack(fill="x", pady=6)
        # Read-only: every key goes straight into the buffer (on_key), and the
        # field shows what is still waiting to be read, like Logisim's Keyboard.
        self.key_waiting = tk.StringVar(value="")
        self.key_entry = ttk.Entry(keys, textvariable=self.key_waiting,
                                   font=MONO, state="readonly")
        self.key_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        self.key_entry.bind("<KeyPress>", self.on_key)
        for paste in ("<<Paste>>", "<Control-v>", "<Control-V>"):
            self.key_entry.bind(paste, self.on_paste)    # more specific than <KeyPress>
        self.buffer_label = ttk.Label(keys, text="buffer 0", width=12)
        self.buffer_label.pack(side="left", padx=4)

    def _build_trace(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="last instructions")
        box.pack(fill="both", expand=True)
        self.trace = tk.Text(box, font=MONO, height=12, wrap="none")
        self.trace.pack(fill="both", expand=True, padx=4, pady=4)
        self.trace.configure(state="disabled")

    # ------------------------------------------------------------- actions
    def load_rom(self) -> None:
        path = filedialog.askopenfilename(title="ROM image")
        if path:
            self.rom_path = path
            self.info = DebugInfo.for_rom(path)
            self.source_pane.set_info(self.info)
            self._load(path, self.cpu.mem.load_rom)

    def load_ram(self) -> None:
        path = filedialog.askopenfilename(title="RAM image")
        if path:
            self._load(path, self.cpu.mem.load_ram)

    def load_disk(self) -> None:
        # a save dialog, so a new name can be typed: a missing disk is created
        path = filedialog.asksaveasfilename(title="disk image (created if missing)",
                                            confirmoverwrite=False)
        if not path:
            return
        try:
            self.cpu.bus.attach_disk(path)
        except (ValueError, OSError) as error:
            messagebox.showerror("disk failed", str(error))
            return
        self._log(f"disk {path}: {self.cpu.bus.disk.words} words")
        self.refresh(memory=False)

    def _load(self, path, loader) -> None:
        try:
            count = loader(load_image(path))
        except Exception as error:                     # noqa: BLE001
            messagebox.showerror("load failed", str(error))
            return
        self.set_running(False)
        self.cpu.reset(clear_ram=False)
        self._log(f"loaded {count} words from {path}")
        self.refresh()

    def reset(self) -> None:
        self.set_running(False)
        self.cpu.reset()
        self._clear_trace()
        self.refresh()

    def step(self) -> None:
        self.set_running(False)
        self._execute(1)
        self.refresh()

    def step_c(self, how: str) -> None:
        """Run to the next C line: into calls, over them, or out of the
        current function."""
        self.set_running(False)
        if not self.info or not self.info.lines:
            self._log("no C line information for this ROM (see the C source tab)")
            return
        before = self.cpu.instructions
        if how == "out":
            why = step_out(self.cpu, self.info)
        else:
            why = step_line(self.cpu, self.info, over=(how == "over"))
        ran = self.cpu.instructions - before
        where = self._where()
        if why == "limit":
            self._log(f"no new C line after {ran} instructions (waiting for a key?)")
        elif why == "breakpoint":
            self._log(f"breakpoint at 0x{self.cpu.iar:07X}  {where}")
        elif why == "halted":
            self._log(f"halted after {ran} instructions")
        else:
            self._log(f"{where}  ({ran} instructions)")
        self.refresh()

    def _where(self) -> str:
        """function and C line of the IAR, e.g. "main  hello.c:13"."""
        if not self.info:
            return ""
        name = self.info.function_at(self.cpu.iar) or "?"
        here = self.info.line_at(self.cpu.iar)
        return f"{name}  {os.path.basename(here[0])}:{here[1]}" if here else name

    def toggle_run(self) -> None:
        self.set_running(not self.running)

    def set_running(self, value: bool) -> None:
        """Single place that changes the run state, so the button always matches."""
        self.running = value
        if value:
            self.cpu.bus.timer.resume()
        else:
            self.cpu.bus.timer.pause()
        self._moved = False                 # never re-trigger the breakpoint we sit on
        self.run_button.configure(text="pause" if value else "run")
        self._restart_clock()

    def resume(self) -> None:
        self.cpu.resume()
        self.refresh()

    def on_key(self, event) -> str | None:
        """A key typed into the keyboard field goes into the buffer at once."""
        code = key_code(event.keysym, event.char)
        if code is None:
            return None                     # let Tk handle Tab, Ctrl+V, ...
        self.cpu.bus.keyboard.type(chr(code))
        self.refresh(memory=False)
        return "break"

    def on_paste(self, _event=None) -> str:
        """Pasted text is typed one key at a time; a line break is Enter."""
        try:
            text = self.clipboard_get()
        except tk.TclError:                 # clipboard empty or not text
            return "break"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        for char in text:
            code = key_code("Return" if char == "\n" else "", char)
            if code is not None:
                self.cpu.bus.keyboard.type(chr(code))
        self.refresh(memory=False)
        return "break"

    # ----------------------------------------------------------- main loop
    def _tick(self) -> None:
        try:
            self._run_tick()
        finally:
            # booked even when the tick failed: an error must not stop the
            # program for good (Tk prints it and the window carries on);
            # booked last, so the window gets 20 ms to redraw between ticks
            self.after(20, self._tick)

    def _run_tick(self) -> None:
        if self.running:
            hz = self.hz
            now = time.perf_counter()
            if hz == 0:                     # "max": run for MAX_SLICE seconds
                count = 0
                while self.running and time.perf_counter() - now < MAX_SLICE:
                    self._execute(10_000)
                self._last_time = now
            else:
                self._budget += hz * (now - self._last_time)
                self._last_time = now
                count = min(int(self._budget), MAX_PER_TICK)
                self._budget -= count
            if count:
                self._execute(count)
            self._ticks += 1
            slow = hz and hz <= 256
            self.refresh(memory=slow or self._ticks % 5 == 0)

    @property
    def hz(self) -> int:
        return SPEED_HZ.get(self.speed.get(), 1_000)

    def _restart_clock(self) -> None:
        """Drop any carried-over budget so a speed change takes effect now."""
        self._budget = 0.0
        self._last_time = time.perf_counter()
        self._rate_mark = (self._last_time, self.cpu.instructions)

    def _execute(self, count: int) -> None:
        log = self.trace_on.get() and count <= 200      # no logging at full speed
        if not log:
            if self._moved and self.cpu.iar in self.cpu.breakpoints:
                self.set_running(False)                 # stop BEFORE this word
                self._log(f"breakpoint at 0x{self.cpu.iar:07X}")
                return
            done = self.cpu.run(count, stop_at=self.cpu.breakpoints)
            if done:
                self._moved = True
            if self.cpu.halted or self.cpu.stopped:
                self.set_running(False)
            elif done < count:                          # stopped at a breakpoint
                self.set_running(False)
                self._log(f"breakpoint at 0x{self.cpu.iar:07X}")
            return
        for _ in range(count):
            if self._moved and self.cpu.iar in self.cpu.breakpoints:
                self.set_running(False)                 # stop BEFORE this word
                self._log(f"breakpoint at 0x{self.cpu.iar:07X}")
                break
            step = self.cpu.step()
            if step is None:                        # halted or stopped
                self.set_running(False)
                break
            self._moved = True
            if log:
                operand = "" if step.operand is None else f" 0x{step.operand:08X}"
                self._log(f"0x{step.address:07X}  {step.word:08X}{operand:<11s} "
                          f"{step.text:<18s} {step.note}")

    # ------------------------------------------------------------- drawing
    def _focused(self):
        """The widget with the keyboard focus, or None. While a combobox's
        list is open the focus is on a widget tkinter has no name for, and
        focus_get() raises KeyError ('popdown')."""
        try:
            return self.focus_get()
        except KeyError:
            return None

    def refresh(self, memory: bool = True) -> None:
        focused = self._focused()
        for i, entry in enumerate(self.reg_entries):
            if entry is focused:
                continue                            # do not fight the user typing
            entry.delete(0, "end")
            entry.insert(0, f"0x{self.cpu.regs[i]:08X}")
        for name in ("IAR", "ESP", "EBP"):
            if self.pointer_entries[name] is not focused:
                self._show_pointer(name)
        for name, var in self.flag_vars.items():
            var.set(self.cpu.flag(name))

        if self.cpu.stopped:
            status = f"STOPPED ({self.cpu.error})"
        elif self.cpu.halted:
            status = "HALTED - press resume"
        elif self.running:
            status = "running"
        else:
            status = "paused"
        lines = (
            f"bank  {'RAM' if self.cpu.iar & config.RAM_BIT else 'ROM'}",
            f"out   0x{self.cpu.bus.out_addr:X}   in 0x{self.cpu.bus.in_addr:X}",
            f"disk  {self._disk_text()}",
            f"in    {self._where()}",
            f"count {self.cpu.instructions}",
            f"rate  {self._measured_rate()}",
            status)
        # cut to the label's fixed width, so a long function name does not
        # widen the column (and shake the window) every refresh
        self.state_label.configure(text="\n".join(
            line if len(line) <= STATE_CHARS else line[:STATE_CHARS - 1] + "…"
            for line in lines))

        self.display.configure(state="normal")
        self.display.delete("1.0", "end")
        self.display.insert("1.0", self.cpu.bus.display.text)
        self.display.see("end")
        self.display.configure(state="disabled")
        hv = self.cpu.bus.hex_value
        self.hex_label.configure(text="--------" if hv is None else f"{hv:08X}")
        self._draw_screen()
        self.buffer_label.configure(text=f"buffer {len(self.cpu.bus.keyboard.buffer)}")
        self.key_waiting.set(buffer_text(self.cpu.bus.keyboard.buffer))

        if memory:
            for pane in (self.rom_pane, self.ram_pane):
                pane.follow_iar()
                pane.render()
            self.source_pane.render()

    def _fit_screen(self, event) -> None:
        """Zoom the RGB screen by the largest whole factor that fits its tab."""
        video = self.cpu.bus.video
        zoom = max(1, min((event.width - 8) // video.width,
                          (event.height - 8) // video.height))
        if zoom != self.screen_zoom:
            self.screen_zoom = zoom
            self.screen_big = self.screen_image.zoom(zoom)
            self.screen_label.configure(image=self.screen_big)

    def _draw_screen(self) -> None:
        video = self.cpu.bus.video
        if not (video.dirty or video.cleared):
            return
        if video.cleared or len(video.dirty) > 1000:
            # the whole image in one put: one {row} of colours per line
            names = ["#%02x%02x%02x" % video.rgb(c) for c in video.pixels]
            w = video.width
            self.screen_image.put(" ".join("{" + " ".join(names[y * w:(y + 1) * w]) + "}"
                                           for y in range(video.height)))
        else:
            for i in video.dirty:
                self.screen_image.put("#%02x%02x%02x" % video.rgb(video.pixels[i]),
                                      to=(i % video.width, i // video.width))
        video.dirty = set()
        video.cleared = False
        self.screen_big = self.screen_image.zoom(self.screen_zoom)
        self.screen_label.configure(image=self.screen_big)
        if video.used and not self._screen_shown:
            self._screen_shown = True
            self.outputs.select(self.screen_tab)

    def _disk_text(self) -> str:
        disk = self.cpu.bus.disk
        if disk is None:
            return "none"
        return f"{os.path.basename(disk.path)} at {disk.position}"

    def _measured_rate(self) -> str:
        """Instructions actually executed per second, averaged over ~0.5 s."""
        mark_time, mark_count = self._rate_mark
        now = time.perf_counter()
        if now - mark_time >= 0.5:
            self._rate = (self.cpu.instructions - mark_count) / (now - mark_time)
            self._rate_mark = (now, self.cpu.instructions)
        if not self.running:
            return "paused"
        if self._rate >= 1_000_000:
            return f"{self._rate / 1_000_000:.2f} MHz"
        if self._rate >= 1000:
            return f"{self._rate / 1000:.1f} kHz"
        return f"{self._rate:.0f} Hz"

    def _log(self, line: str) -> None:
        self.trace.configure(state="normal")
        self.trace.insert("end", line + "\n")
        if int(self.trace.index("end-1c").split(".")[0]) > 400:
            self.trace.delete("1.0", "200.0")
        self.trace.see("end")
        self.trace.configure(state="disabled")

    def _clear_trace(self) -> None:
        self.trace.configure(state="normal")
        self.trace.delete("1.0", "end")
        self.trace.configure(state="disabled")