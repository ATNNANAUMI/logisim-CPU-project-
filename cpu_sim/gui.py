"""Tkinter front end: registers, ROM/RAM views, display, keyboard, controls."""

import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import alu as alu
import config as config
from cpu import CPU
from isa import decode, disassemble
from memory import load_image

PAGE_WORDS = 256
MONO = "TkFixedFont"
MAX_PER_TICK = 50_000          # keeps the window responsive at high speeds

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
        self.goto = ttk.Entry(bar, width=8)
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

        self.text = tk.Text(self, font=MONO, wrap="none", height=24, width=52)
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
        self.page = (addr & 0xFFFF) // PAGE_WORDS
        self.render()

    def follow_iar(self) -> None:
        if not self.follow.get():
            return
        iar = self.cpu.iar
        in_this_bank = (self.bank == "ram") == bool(iar & config.RAM_BIT)
        if in_this_bank:
            self.page = (iar & 0xFFFF) // PAGE_WORDS

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
            "edit memory", f"new value for 0x{addr:05X}\n(hex, decimal or 1.5f)",
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
                lines.append(f"{mark} 0x{addr:05X}  {word:08X}  {text}")
            else:
                lines.append(f"{mark} 0x{addr:05X}  {word:08X}  "
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
            text=f"0x{self.base | start:05X} - 0x{self.base | (end - 1):05X}")

    @staticmethod
    def _signed(word: int) -> int:
        return word - (1 << 32) if word & config.SIGN_BIT else word

    @staticmethod
    def _ascii(word: int) -> str:
        char = word & 0xFF
        return chr(char) if 32 <= char < 127 else "."


class SimulatorWindow(tk.Tk):
    def __init__(self, cpu: CPU, rom_path: str | None = None):
        super().__init__()
        self.cpu = cpu
        self.rom_path = rom_path
        self.running = False
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
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=6, pady=6)
        self._build_controls(left)
        self._build_registers(left)
        self._build_state(left)

        middle = ttk.Notebook(self)
        middle.pack(side="left", fill="both", expand=True, pady=6)
        self.rom_pane = MemoryPane(middle, self.cpu, "rom")
        self.ram_pane = MemoryPane(middle, self.cpu, "ram")
        middle.add(self.rom_pane, text="ROM")
        middle.add(self.ram_pane, text="RAM")

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self._build_display(right)
        self._build_trace(right)

    def _build_controls(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="control")
        box.pack(fill="x")

        row1 = ttk.Frame(box)
        row1.pack(fill="x", padx=4, pady=2)
        ttk.Button(row1, text="load ROM", command=self.load_rom).pack(side="left")
        ttk.Button(row1, text="load RAM", command=self.load_ram).pack(side="left", padx=2)
        ttk.Button(row1, text="reset", command=self.reset).pack(side="left")

        row2 = ttk.Frame(box)
        row2.pack(fill="x", padx=4, pady=2)
        ttk.Button(row2, text="step", command=self.step).pack(side="left")
        self.run_button = ttk.Button(row2, text="run", command=self.toggle_run)
        self.run_button.pack(side="left", padx=2)
        ttk.Button(row2, text="resume", command=self.resume).pack(side="left")

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

        self.state_label = ttk.Label(box, font=MONO, justify="left", text="")
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
        width = 5 if name == "IAR" else 4
        entry = self.pointer_entries[name]
        entry.delete(0, "end")
        entry.insert(0, f"0x{value:0{width}X}")

    def _build_display(self, parent) -> None:
        box = ttk.LabelFrame(parent, text=f"display (0x{config.DISPLAY_ADDR:02X})")
        box.pack(fill="both", expand=True)
        self.display = tk.Text(box, font=MONO, height=16, wrap="char",
                               background="#101010", foreground="#c8ffc8",
                               insertbackground="#c8ffc8")
        self.display.pack(fill="both", expand=True, padx=4, pady=4)
        self.display.configure(state="disabled")

        keys = ttk.LabelFrame(parent, text=f"keyboard (0x{config.KEYBOARD_ADDR:02X})")
        keys.pack(fill="x", pady=6)
        self.key_entry = ttk.Entry(keys)
        self.key_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        self.key_entry.bind("<Return>", lambda _e: self.send_keys())
        self.newline = tk.BooleanVar(value=True)
        ttk.Checkbutton(keys, text="+LF", variable=self.newline).pack(side="left")
        ttk.Button(keys, text="send", command=self.send_keys).pack(side="left", padx=4)
        self.buffer_label = ttk.Label(keys, text="buffer 0")
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
            self._load(path, self.cpu.mem.load_rom)
            self.rom_path = path

    def load_ram(self) -> None:
        path = filedialog.askopenfilename(title="RAM image")
        if path:
            self._load(path, self.cpu.mem.load_ram)

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

    def toggle_run(self) -> None:
        self.set_running(not self.running)

    def set_running(self, value: bool) -> None:
        """Single place that changes the run state, so the button always matches."""
        self.running = value
        self._moved = False                 # never re-trigger the breakpoint we sit on
        self.run_button.configure(text="pause" if value else "run")
        self._restart_clock()

    def resume(self) -> None:
        self.cpu.resume()
        self.refresh()

    def send_keys(self) -> None:
        text = self.key_entry.get()
        if self.newline.get():
            text += "\n"
        self.cpu.bus.keyboard.type(text)
        self.key_entry.delete(0, "end")
        self.refresh()

    # ----------------------------------------------------------- main loop
    def _tick(self) -> None:
        if self.running:
            hz = self.hz
            now = time.perf_counter()
            if hz == 0:
                count = MAX_PER_TICK
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
        self.after(20, self._tick)

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
        for _ in range(count):
            if self._moved and self.cpu.iar in self.cpu.breakpoints:
                self.set_running(False)                 # stop BEFORE this word
                self._log(f"breakpoint at 0x{self.cpu.iar:05X}")
                break
            step = self.cpu.step()
            if step is None:                        # halted or stopped
                self.set_running(False)
                break
            self._moved = True
            if log:
                operand = "" if step.operand is None else f" 0x{step.operand:08X}"
                self._log(f"0x{step.address:05X}  {step.word:08X}{operand:<11s} "
                          f"{step.text:<18s} {step.note}")

    # ------------------------------------------------------------- drawing
    def refresh(self, memory: bool = True) -> None:
        focused = self.focus_get()
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
        self.state_label.configure(text=(
            f"bank  {'RAM' if self.cpu.iar & config.RAM_BIT else 'ROM'}\n"
            f"out   0x{self.cpu.bus.out_addr:X}   in 0x{self.cpu.bus.in_addr:X}\n"
            f"count {self.cpu.instructions}\n"
            f"rate  {self._measured_rate()}\n"
            f"{status}"))

        self.display.configure(state="normal")
        self.display.delete("1.0", "end")
        self.display.insert("1.0", self.cpu.bus.display.text)
        self.display.see("end")
        self.display.configure(state="disabled")
        self.buffer_label.configure(text=f"buffer {len(self.cpu.bus.keyboard.buffer)}")

        if memory:
            for pane in (self.rom_pane, self.ram_pane):
                pane.follow_iar()
                pane.render()

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