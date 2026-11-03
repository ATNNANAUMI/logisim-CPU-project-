"""Machine snapshots: save the whole state of a simulated CPU and continue it later.

    python cpu_sim/src/main.py prog.rom --headless --steps N --save-state run.state
    python cpu_sim/src/main.py --load-state run.state [--headless --steps M] [--disk other.img]

A snapshot is a zip file:

    state.json   format 1: the CPU (registers, IAR, flags, ESP, EBP, the stack
                 limit, the interrupt bits, halted/stopped, the instruction
                 count), the devices (the selected device addresses, the text
                 display, the hex display, the keyboard buffer, the timer's
                 milliseconds and period, the interrupt controller, whether the
                 RGB screen was used, the disk's path, position, size and
                 modification time), the ROM's path and the words' SHA-1
    rom, ram     the banks in chunks of 64K words that are not all 0: per chunk
                 its number (4 bytes) and its zlib-compressed little-endian words
    video        the RGB screen's 65,536 pixels, zlib-compressed

Not saved: the disk's contents (only where it is: loading warns when the file
changed since, and another disk can be given instead), the Claude device's
conversation (it starts afresh, with a note) and the translated code (a cache:
it is made again as the program runs). The timer continues from its saved
milliseconds on the PC's clock of the moment of loading.
"""

import array
import hashlib
import io
import json
import os
import zipfile
import zlib

import config
import memory

FORMAT = 1
CHUNK = 1 << 16                         # words per chunk of a bank


def _bank_bytes(bank):
    words = array.array("I", bank)
    assert words.itemsize == 4
    return words.tobytes()


def _pack_bank(bank):
    """The chunks of a bank that are not all 0, compressed."""
    raw = _bank_bytes(bank)
    out = io.BytesIO()
    step = CHUNK * 4
    for i in range(0, len(raw), step):
        piece = raw[i:i + step]
        if piece.count(0) != len(piece):
            data = zlib.compress(piece, 1)
            out.write((i // step).to_bytes(4, "little") + len(data).to_bytes(4, "little") + data)
    return out.getvalue()


def _unpack_bank(data):
    """A new bank (16M words) holding the saved chunks, 0 elsewhere."""
    bank = [0] * config.BANK_WORDS
    at = 0
    while at < len(data):
        index = int.from_bytes(data[at:at + 4], "little")
        size = int.from_bytes(data[at + 4:at + 8], "little")
        piece = zlib.decompress(data[at + 8:at + 8 + size])
        words = array.array("I")
        words.frombytes(piece)
        bank[index * CHUNK:index * CHUNK + len(words)] = words.tolist()
        at += 8 + size
    return memory._unseen(bank)


def _disk_facts(path):
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def save(cpu, path, rom_path=None):
    """Write cpu's state to the snapshot file path."""
    bus = cpu.bus
    state = {
        "format": FORMAT,
        "cpu": {"regs": cpu.regs, "iar": cpu.iar, "flags": cpu.flags, "esp": cpu.esp,
                "ebp": cpu.ebp, "slimit": cpu.slimit, "ie": cpu.ie, "in_nmi": cpu.in_nmi,
                "inhibit": cpu.inhibit, "waiting": cpu.waiting, "nmi_pending": cpu.nmi_pending,
                "fault_pending": cpu.fault_pending, "halted": cpu.halted, "stopped": cpu.stopped,
                "error": cpu.error, "instructions": cpu.instructions},
        "bus": {"out_addr": bus.out_addr, "in_addr": bus.in_addr, "hex_value": bus.hex_value,
                "display": {"lines": bus.display.lines, "col": bus.display.col},
                "keyboard": list(bus.keyboard.buffer),
                "timer": {"ms": bus.timer.now_ms(), "period": bus.timer.period,
                          "to_tick": bus.timer.next_tick - bus.timer.now_ms()},
                "interrupts": {"pending": bus.interrupts.pending, "enable": bus.interrupts.enable},
                "video_used": bus.video.used},
        "rom": {"path": None if rom_path is None else os.path.abspath(rom_path),
                "sha1": hashlib.sha1(_bank_bytes(cpu.mem.rom)).hexdigest()},
        "disk": None,
    }
    if bus.disk is not None:
        bus.disk.map.flush()
        state["disk"] = {"path": os.path.abspath(bus.disk.path), "position": bus.disk.position,
                         **_disk_facts(bus.disk.path)}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("state.json", json.dumps(state, indent=1))
        z.writestr("rom", _pack_bank(cpu.mem.rom))
        z.writestr("ram", _pack_bank(cpu.mem.ram))
        pixels = array.array("H", bus.video.pixels).tobytes()
        z.writestr("video", zlib.compress(pixels, 1))


def load(cpu, path, disk=None):
    """Put the snapshot's state into cpu. disk: a disk image to attach
    instead of the saved one (None: the saved one, if it is still there).
    Returns the ROM's saved path and a list of warnings."""
    warnings = []
    with zipfile.ZipFile(path) as z:
        state = json.loads(z.read("state.json"))
        if state.get("format") != FORMAT:
            raise ValueError(f"{path}: snapshot format {state.get('format')}, this simulator reads {FORMAT}")
        rom, ram, video = z.read("rom"), z.read("ram"), z.read("video")
    cpu.mem.rom = _unpack_bank(rom)
    cpu.mem.ram = _unpack_bank(ram)
    cpu.forget_code()
    c = state["cpu"]
    cpu.regs = list(c["regs"])
    for name in ("iar", "flags", "esp", "ebp", "slimit", "ie", "in_nmi", "inhibit", "waiting",
                 "nmi_pending", "fault_pending", "halted", "stopped", "error", "instructions"):
        setattr(cpu, name, c[name])

    b, bus = state["bus"], cpu.bus
    saved_disk = state.get("disk")
    if disk is not None:
        bus.attach_disk(disk)
    elif saved_disk and os.path.exists(saved_disk["path"]):
        bus.attach_disk(saved_disk["path"])
        if _disk_facts(saved_disk["path"]) != {k: saved_disk[k] for k in ("size", "mtime_ns")}:
            warnings.append(f"the disk {saved_disk['path']} changed since the snapshot was saved")
    elif saved_disk:
        warnings.append(f"the disk {saved_disk['path']} is gone: no disk attached")
        bus.attach_disk(None)
    else:
        bus.attach_disk(None)
    if bus.disk is not None and saved_disk:
        bus.disk.position = saved_disk["position"]
    bus.in_addr = b["in_addr"]
    bus.out_address(b["out_addr"])
    bus.hex_value = b["hex_value"]
    bus.display.lines, bus.display.col = list(b["display"]["lines"]), b["display"]["col"]
    bus.keyboard.buffer.clear()
    bus.keyboard.buffer.extend(b["keyboard"])
    t = bus.timer
    now = t.clock()
    if t.frozen is not None:
        t.frozen = now
    t.start = now - b["timer"]["ms"] / 1000
    t.period = b["timer"]["period"]
    t.next_tick = b["timer"]["ms"] + b["timer"]["to_tick"]
    bus.interrupts.pending = b["interrupts"]["pending"]
    bus.interrupts.enable = b["interrupts"]["enable"]
    pixels = array.array("H")
    pixels.frombytes(zlib.decompress(video))
    bus.video.pixels = pixels.tolist()
    bus.video.dirty.clear()
    bus.video.cleared = True
    bus.video.used = b["video_used"]
    bus.claude.reset()
    if state["rom"]["sha1"] != hashlib.sha1(_bank_bytes(cpu.mem.rom)).hexdigest():
        warnings.append("the ROM words read back differently (a damaged snapshot?)")
    return state["rom"]["path"], warnings


def digest(cpu):
    """A hash of everything a snapshot keeps (the self-check compares runs with it)."""
    bus = cpu.bus
    h = hashlib.sha1()
    h.update(repr((cpu.regs, cpu.iar, cpu.flags, cpu.esp, cpu.ebp, cpu.slimit, cpu.ie,
                   cpu.in_nmi, cpu.inhibit, cpu.waiting, cpu.nmi_pending, cpu.fault_pending,
                   cpu.halted, cpu.stopped, cpu.instructions, bus.out_addr, bus.in_addr,
                   bus.hex_value, bus.display.text, list(bus.keyboard.buffer),
                   int(bus.timer.now_ms()), bus.timer.period, bus.interrupts.pending,
                   bus.interrupts.enable, bus.disk.position if bus.disk else None)).encode())
    h.update(_bank_bytes(cpu.mem.ram))
    h.update(array.array("H", bus.video.pixels).tobytes())
    return h.hexdigest()[:12]
