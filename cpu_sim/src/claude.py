"""The Claude device at 0x9C (simulator only, Phase 8; TECHNICAL 1.7 and 11.5).

Claude does not run on the CPU: the CPU is a terminal. A program (Tynix's
`claude`, tynix/claude.c) sends the text typed on its keyboard here one char
at a time; this module, in the simulator's Python process on the PC, calls the
Claude API in a worker thread and hands the reply back one char at a time as
it streams in. The simulation never waits for the network.

    OUTDATA  a char      added to the line being sent
             0           send it: a message to Claude, or (a line starting
                         with /) a command for this device; while a tool runs
                         on the CPU, the tool's result
             0x18 (CAN)  a new conversation (the history is forgotten)
             0x03 (ETX)  stop the reply now (what came so far stays in the history)
             0x16 (SYN)  a program starts using the device: a turn left over
                         from one that was killed is dropped, unread chars too
    INDATA   0           nothing yet (as the keyboard)
             4 (EOT)     the turn is over
             2 (STX)     a tool for the CPU follows: a letter, then fields
                         split by 0x1F, then 3 (ETX). The CPU runs it and
                         answers with the result's chars and a 0.
                           r/R  timeout_s, command, input   (R: ask the user first)
                           w/W  path, content
             anything else  a char of the reply: printable ASCII and \\n only

The history of the conversation is kept here, not in the CPU's RAM: it
survives the program's end and is lost when the simulator closes. Tools that
touch the PC (reading the permitted files, writing where allowed, the
screenshot of the RGB screen) run here and never reach the CPU, which only
gets a line saying what Claude did. Everything Claude reads is sent to
Anthropic's API.

The real backend imports the `anthropic` package the first time a request is
made, so everything else stays standard library; the key comes from the
environment (ANTHROPIC_API_KEY, or an `ant auth login` profile), never from
the disk image or a ROM. The self-checks use FakeBackend.
"""

from __future__ import annotations

import collections
import json
import os
import queue
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]        # the project
TYNIX = ROOT / "tynix"
SYSTEM_FILE = TYNIX / "cpu_claude.md"             # the system prompt
ACCESS_FILE = TYNIX / "claude_access.conf"        # extra PC paths Claude may read / write
CLAUDE_DIR = TYNIX / "claude"                     # Claude's own folder on the PC (read and write)

STX, ETX, EOT, SYN, CAN, US = 0x02, 0x03, 0x04, 0x16, 0x18, 0x1F

# One table for the models /model accepts, their prices in dollars per
# million tokens (input, output) and, for a model with a second rate card
# for long prompts, (the prompt length it starts at, input, output). From
# the claude-api skill's table (cached 2026-10-06): prices drift, check them.
MODELS = {
    "claude-haiku-5-5": (0.10, 0.50, (100_000, 0.50, 2.50)),
    "claude-sonnet-5-5": (2.00, 10.00, None),
    "claude-opus-5-5": (4.00, 20.00, None),
    "claude-fable-5-1": (10.00, 50.00, None),
}
ALIASES = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5",
           "opus": "claude-opus-5-5", "fable": "claude-fable-5-1"}
CACHE_READ, CACHE_WRITE = 0.1, 1.25               # times the input price
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MAX_OUTPUT = 128_000                               # every model in MODELS

DEFAULTS = dict(model="claude-haiku-5-5", effort="low", max_tokens=100_000,
                timeout=30, tools=True, approve=False)
LONG_PROMPT = 100_000           # tokens: the warning (Haiku's price goes up 5x)
RESULT_CAP = 10_000             # chars of a tool's result kept (the CPU sends 8K at most)
READ_CAP = 100_000              # chars of a PC file Claude may read in one go
TOOL_ROUNDS = 40                # tool calls in one turn before the device stops it

# ---------------------------------------------------------------- characters

_PLAIN = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"', "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "--", "―": "--",
    "−": "-", "…": "...", " ": " ", " ": " ", " ": " ", "​": "",
    "•": "*", "·": "*", "→": "->", "←": "<-", "⇒": "=>",
    "≤": "<=", "≥": ">=", "≠": "!=", "×": "x", "÷": "/",
    "°": " deg", "©": "(c)", "®": "(R)", "™": "(TM)", "€": "EUR",
    "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "½": "1/2", "¼": "1/4",
}


def ascii_text(text: str, tabs: bool = False) -> str:
    """What the 8-bit display can show: printable ASCII and newlines. Letters
    with accents lose them (e for e-acute), curly quotes, dashes and the
    ellipsis become their plain forms, the rest becomes '?'. A tab becomes
    four spaces (kept when tabs: a file's content)."""
    out = []
    for ch in text:
        if " " <= ch <= "~" or ch == "\n":
            out.append(ch)
        elif ch == "\t":
            out.append("\t" if tabs else "    ")
        elif ch == "\r":
            continue
        elif ch in _PLAIN:
            out.append(_PLAIN[ch])
        else:
            base = "".join(c for c in unicodedata.normalize("NFKD", ch)
                           if not unicodedata.combining(c))
            if base and all(" " <= c <= "~" for c in base):
                out.append(base)
            elif unicodedata.category(ch).startswith(("C", "M")):
                continue                    # controls, stray marks, emoji modifiers
            else:
                out.append("?")
    return "".join(out)


# ---------------------------------------------------------------- the PC's files

class AccessError(Exception):
    pass


def _expand(text: str, base: Path) -> Path:
    p = Path(os.path.expanduser(text))
    return p if p.is_absolute() else base / p


class Access:
    """Which paths of the PC Claude may read and write: tynix/claude/ (both),
    and the lines of tynix/claude_access.conf, re-read on every request so it
    can be edited while the simulator runs:

        read  ~/Documents/specs/isa_notes.md     a file
        read  ../compiler/                       a folder and everything under it
        write ~/Documents/claude_out/            write implies read

    Relative paths in the file start at its folder (tynix/); a path Claude
    gives starts at tynix/claude/. Everything is compared after resolving
    symlinks, so neither `..` nor a link can lead outside. Nothing else is
    allowed, and nothing can run on the PC."""

    def __init__(self, folder: Path = CLAUDE_DIR, conf: Path = ACCESS_FILE):
        self.folder = Path(folder)
        self.conf = Path(conf)

    def rules(self) -> list[tuple[str, Path]]:
        rules = [("write", self.folder)]
        try:
            lines = self.conf.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            kind, _, path = line.partition(" ")
            if kind in ("read", "write") and path.strip():
                rules.append((kind, _expand(path.strip(), self.conf.parent)))
        return rules

    def resolve(self, text: str, write: bool = False) -> Path:
        """The real path for what Claude asked, or AccessError."""
        if not text or "\0" in text:
            raise AccessError("no path given")
        if ".." in Path(text).parts:
            raise AccessError(f"{text}: '..' is not allowed")
        if write:
            self.folder.mkdir(parents=True, exist_ok=True)
        path = Path(os.path.realpath(_expand(text, self.folder)))
        for kind, allowed in self.rules():
            if write and kind != "write":
                continue
            real = Path(os.path.realpath(allowed))
            if path == real or real in path.parents:
                return path
        raise AccessError(f"{text}: not allowed ({'write' if write else 'read'}); "
                          f"the permitted paths are in tynix/claude_access.conf")

    def listing(self) -> str:
        lines = ["Paths Claude may use on the PC:"]
        for kind, path in self.rules():
            lines.append(f"  {kind:5s} {path}")
        return "\n".join(lines)


def read_host_file(access: Access, path: str) -> str:
    p = access.resolve(path)
    if not p.is_file():
        raise AccessError(f"{path}: not a file")
    data = p.read_bytes()
    if b"\0" in data[:4096]:
        raise AccessError(f"{path}: a binary file ({len(data)} bytes)")
    text = data.decode("utf-8", errors="replace")
    if len(text) > READ_CAP:
        return text[:READ_CAP] + f"\n[... cut: {len(text)} chars, the first {READ_CAP} shown]"
    return text


def list_host_dir(access: Access, path: str) -> str:
    if not path:
        return access.listing()
    p = access.resolve(path)
    if not p.is_dir():
        raise AccessError(f"{path}: not a folder (relative paths start in tynix/claude/, "
                          f"'.' is that folder; use the absolute paths of the permitted list)")
    lines = []
    for entry in sorted(p.iterdir(), key=lambda e: e.name):
        try:
            lines.append(entry.name + "/" if entry.is_dir() else f"{entry.name}  {entry.stat().st_size}")
        except OSError:
            lines.append(entry.name + "  ?")
    return "\n".join(lines) or "(empty)"


def write_host_file(access: Access, path: str, content: str) -> str:
    p = access.resolve(path, write=True)
    if p.is_dir():
        raise AccessError(f"{path}: is a folder")
    p.parent.mkdir(parents=True, exist_ok=True)
    access.resolve(str(p), write=True)          # the folders made are still inside
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {p}"


# ---------------------------------------------------------------- tools

def _tool(name, description, properties, required):
    return {
        "name": name,
        "description": description,
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": properties,
                         "required": required, "additionalProperties": False},
    }


_S = {"type": "string"}
TOOLS = [
    _tool("run_command",
          "Run one Tynix shell command line on the CPU (a fresh `sh -c` in the current directory) "
          "and get its exit status and output (stdout; at most 8000 chars). `input`, if given, is "
          "the program's stdin (what getchar/fgets read), ended by EOF. Never run full-screen or "
          "interactive programs (edit, visual_file_manager, snake, game_of_life, guess).",
          {"command": dict(_S, description="one line, at most 255 chars"),
           "input": dict(_S, description="text for the program's stdin")}, ["command"]),
    _tool("write_file", "Write a text file on the CPU's disk (TFS1), replacing it.",
          {"path": dict(_S, description="a path on the CPU's disk"), "content": _S},
          ["path", "content"]),
    _tool("read_host_file", "Read a text file on the real PC (only the permitted paths).",
          {"path": dict(_S, description="relative paths start in Claude's folder tynix/claude/")},
          ["path"]),
    _tool("list_host_dir", "List a folder on the real PC (only the permitted paths); an empty "
          "path lists what is permitted.", {"path": _S}, ["path"]),
    _tool("write_host_file", "Write a text file on the real PC: only in Claude's folder "
          "tynix/claude/ and the paths permitted for writing.",
          {"path": _S, "content": _S}, ["path", "content"]),
    _tool("screenshot", "A picture of the CPU's 256x256 RGB screen as it is now (shown 2x).",
          {}, []),
]
SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}


def check_input(name: str, data) -> str | None:
    """What is wrong with a tool's input (None: nothing). With eager input
    streaming the API does not validate it, so it is checked here before
    anything runs."""
    schema = SCHEMAS.get(name)
    if schema is None:
        return f"no tool called {name}"
    if not isinstance(data, dict):
        return "the input is not an object"
    for key in schema["required"]:
        if key not in data:
            return f"missing {key}"
    for key, value in data.items():
        if key not in schema["properties"]:
            return f"unknown field {key}"
        if not isinstance(value, str):
            return f"{key} is not a string"
    return None


# ---------------------------------------------------------------- backends

def get(block, name, default=None):
    """A field of a content block: a dict (FakeBackend, our own) or an SDK object."""
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


@dataclass
class Reply:
    content: list                   # the content blocks, appended to the history as they are
    stop_reason: str
    usage: dict = field(default_factory=dict)
    stop_details: str = ""
    request_id: str = ""


class BackendError(Exception):
    pass


class AnthropicBackend:
    """The real API, through the `anthropic` SDK (imported on first use)."""

    def __init__(self):
        self.client = None

    def stream(self, request: dict, on_text, cancelled) -> Reply | None:
        """Stream one response; on_text(delta) for each piece of text. None
        when cancelled() said to stop; BackendError for anything failing."""
        try:
            import anthropic
        except ImportError:
            raise BackendError("the anthropic package is not installed (pip install anthropic)")
        try:
            if self.client is None:
                self.client = anthropic.Anthropic()
            with self.client.messages.stream(**request) as stream:
                for text in stream.text_stream:
                    if cancelled():
                        return None
                    on_text(text)
                message = stream.get_final_message()
        except anthropic.AuthenticationError:
            raise BackendError("no valid API key (set ANTHROPIC_API_KEY, or run `ant auth login`)")
        except anthropic.PermissionDeniedError as e:
            raise BackendError(f"not permitted: {e.message}")
        except anthropic.NotFoundError as e:
            raise BackendError(f"not found (the model?): {e.message}")
        except anthropic.RateLimitError:
            raise BackendError("rate limited: try again in a minute")
        except anthropic.BadRequestError as e:
            raise BackendError(f"bad request: {e.message}")
        except anthropic.APIStatusError as e:
            raise BackendError(f"API error {e.status_code}: {e.message}")
        except anthropic.APITimeoutError:
            raise BackendError("the request timed out")
        except anthropic.APIConnectionError:
            raise BackendError("no connection to the API")
        except anthropic.AnthropicError as e:
            raise BackendError(str(e))
        except TypeError as e:                      # the SDK found no credentials at all
            if "authentication" in str(e):
                raise BackendError("no API key on this PC (set ANTHROPIC_API_KEY, "
                                   "or run `ant auth login`)")
            raise BackendError(f"the SDK refused the request: {e}")
        except ValueError as e:                     # a tool input the SDK could not parse
            raise BackendError(f"a tool call arrived broken ({e}); ask again")
        u = message.usage
        usage = {k: getattr(u, k, 0) or 0 for k in
                 ("input_tokens", "output_tokens", "cache_read_input_tokens",
                  "cache_creation_input_tokens")}
        details = getattr(message, "stop_details", None)
        return Reply(content=list(message.content), stop_reason=message.stop_reason or "",
                     usage=usage, request_id=getattr(message, "_request_id", "") or "",
                     stop_details=(getattr(details, "category", None) or "") if details else "")


class FakeBackend:
    """For the self-checks: no network, no cost. Each item of `script` is one
    response, a function request -> (texts, content, stop_reason) or that
    triple itself; texts are the pieces streamed to on_text. A response that
    is an Exception is raised as a BackendError. requests keeps every request."""

    def __init__(self, script=(), usage=None):
        self.script = list(script)
        self.requests = []
        self.usage = usage or {"input_tokens": 1000, "output_tokens": 100,
                               "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        self.gate = None                # a threading.Event the second piece waits for (tests of stopping)

    def stream(self, request, on_text, cancelled):
        self.requests.append(json.loads(json.dumps(request, default=str)))
        if not self.script:
            raise BackendError("the fake backend has no more responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise BackendError(str(item))
        texts, content, stop = item(request) if callable(item) else item
        for i, text in enumerate(texts):
            if self.gate is not None and i == 1:        # wait to be let go, or stopped
                for _ in range(500):
                    if self.gate.is_set() or cancelled():
                        break
                    self.gate.wait(0.01)
            if cancelled():
                return None
            on_text(text)
        return Reply(content=list(content), stop_reason=stop, usage=dict(self.usage))


def text_reply(*texts):
    """FakeBackend: a plain answer streamed in these pieces."""
    return list(texts), [{"type": "text", "text": "".join(texts)}], "end_turn"


def tool_reply(name, data, text="", tool_id="toolu_1"):
    """FakeBackend: a response that calls one tool."""
    content = ([{"type": "text", "text": text}] if text else []) + \
        [{"type": "tool_use", "id": tool_id, "name": name, "input": data}]
    return [text] if text else [], content, "tool_use"


# ---------------------------------------------------------------- the device

class ClaudeDevice:
    """The device at config.CLAUDE_ADDR. write() is OUTDATA, read() INDATA;
    both are called by the simulation, which they never block."""

    def __init__(self, screenshot=None, backend=None, access: Access | None = None,
                 system_file: Path | str = SYSTEM_FILE):
        self.screenshot = screenshot            # () -> PNG bytes of the RGB screen
        self.backend = backend                  # AnthropicBackend made on first use
        self.access = access or Access()
        self.system_file = Path(system_file)
        self.settings = dict(DEFAULTS)
        self.out = collections.deque()          # chars for INDATA
        self.line: list[str] = []               # what OUTDATA has sent since the last 0
        self.lock = threading.Lock()
        self.results: queue.Queue = queue.Queue()
        self.gen = 0                            # a turn is abandoned by moving this on
        self.worker: threading.Thread | None = None
        self.waiting_tool = False
        self.state = "idle"                     # for the window: idle, answering, tool
        self.new_conversation()
        self.reset_usage()

    def configure(self, model: str | None = None, system_file: str | None = None) -> None:
        """--claude-model, --claude-system: ValueError for a model not in MODELS."""
        if model:
            name = ALIASES.get(model.lower(), model.lower())
            if name not in MODELS:
                raise ValueError(f"unknown Claude model {model}: one of "
                                 f"{', '.join(list(ALIASES) + list(MODELS))}")
            self.settings["model"] = name
        if system_file:
            self.system_file = Path(system_file)
            if not self.system_file.is_file():
                raise ValueError(f"{system_file}: no such file (--claude-system)")
            self.system = self.load_system()

    # ------------------------------------------------------------ COMM
    def read(self) -> int:
        try:
            return self.out.popleft()
        except IndexError:
            return 0

    def write(self, value: int) -> None:
        c = value & 0xFF
        if c == 0:
            text = "".join(self.line)
            self.line.clear()
            if self.waiting_tool:
                self.waiting_tool = False
                self.results.put(text)
            else:
                self.submit(text)
        elif c == CAN:
            self.abandon(quiet=True)
            self.new_conversation()
        elif c == ETX:
            self.abandon(quiet=False)
        elif c == SYN:
            self.abandon(quiet=True)
            self.line.clear()
        else:
            self.line.append(chr(c))

    def reset(self) -> None:
        """A CPU reset: the turn in progress ends, the conversation stays."""
        self.abandon(quiet=True)
        self.line.clear()

    # ------------------------------------------------------------ output
    def push(self, text: str, gen: int | None = None) -> None:
        with self.lock:
            if gen is None or gen == self.gen:
                self.out.extend(ord(c) for c in text)

    def push_end(self, text: str = "", gen: int | None = None) -> None:
        self.push(ascii_text(text) + chr(EOT), gen)

    # ------------------------------------------------------------ conversation
    def new_conversation(self) -> None:
        with self.lock:
            self.history: list[dict] = []
            self.partial: list[str] = []        # the reply's text so far
            self.pending: list[str] = []        # tool_use ids not answered yet
            self.warned_long = False
            self.system = self.load_system()

    def load_system(self) -> str:
        try:
            return self.system_file.read_text(encoding="utf-8")
        except OSError:
            return "You are Claude, talking through the text display of a small 32-bit CPU " \
                   "built from logic gates. Answer in plain ASCII, short lines, no markdown."

    def reset_usage(self) -> None:
        self.usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                      "dollars": 0.0}

    def abandon(self, quiet: bool) -> None:
        """Stop the turn in progress, if any: the worker's later output is
        dropped (gen), and the history is left valid (the partial reply kept,
        tool calls answered as stopped). quiet: also forget the unread chars
        and send no EOT (a new program, a new conversation, a reset)."""
        with self.lock:
            busy = self.worker is not None and self.worker.is_alive()
            self.gen += 1
            if busy:
                if self.pending:
                    self.history.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": i, "is_error": True,
                         "content": "stopped by the user before it ran"} for i in self.pending]})
                elif self.partial:
                    self.history.append({"role": "assistant", "content": [
                        {"type": "text", "text": "".join(self.partial) + " [stopped by the user]"}]})
                self.pending, self.partial = [], []
            if quiet:
                self.out.clear()
            self.worker = None
            self.state = "idle"
            if self.waiting_tool:
                self.waiting_tool = False
                self.results.put(None)
        if busy and not quiet:
            self.push_end("\n[stopped]\n")

    def submit(self, text: str) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.push_end("[claude is still answering]\n")
            return
        if text.startswith("/"):
            self.push_end(self.command(text))
            return
        if not text.strip():
            self.push_end()
            return
        gen = self.gen
        self.worker = threading.Thread(target=self.turn, args=(text, gen), daemon=True)
        self.state = "answering"
        self.worker.start()

    # ------------------------------------------------------------ one turn (worker thread)
    def request(self) -> dict:
        s = self.settings
        req = {
            "model": s["model"],
            "max_tokens": s["max_tokens"],
            "system": [{"type": "text", "text": self.system}],
            "messages": list(self.history),
            "tools": TOOLS,
            "output_config": {"effort": s["effort"]},
            "cache_control": {"type": "ephemeral"},
        }
        if not s["tools"]:
            req["tool_choice"] = {"type": "none"}   # the tools stay listed: the cache holds
        return req

    def turn(self, text: str, gen: int) -> None:
        try:
            self._turn(text, gen)
        except Exception as e:                      # a bug here must not leave the CPU waiting
            self.push_end(f"\n[claude device error: {e}]\n", gen)
        finally:
            with self.lock:
                if gen == self.gen:
                    self.state = "idle"

    def _turn(self, text: str, gen: int) -> None:
        with self.lock:
            if gen != self.gen:
                return
            self.history.append({"role": "user", "content": text})
        if self.backend is None:
            self.backend = AnthropicBackend()
        for _ in range(TOOL_ROUNDS):
            with self.lock:
                if gen != self.gen:
                    return
                req = self.request()
                self.partial = []

            def on_text(delta):
                with self.lock:
                    if gen != self.gen:
                        return
                    self.partial.append(delta)
                    self.out.extend(ord(c) for c in ascii_text(delta))

            try:
                reply = self.backend.stream(req, on_text, lambda: gen != self.gen)
            except BackendError as e:
                self.push_end(f"\n[claude: {e}]\n", gen)
                return
            if reply is None:
                return                              # stopped: abandon() did the rest
            with self.lock:
                if gen != self.gen:
                    return
                self.count(reply.usage)
                tools = [b for b in reply.content if get(b, "type") == "tool_use"]
                if reply.stop_reason == "refusal":
                    self.history.append({"role": "assistant", "content": [
                        {"type": "text", "text": "(declined)"}]})
                    end = f"\n[claude declined to answer{': ' + reply.stop_details if reply.stop_details else ''}]\n"
                    tools = []
                else:
                    self.history.append({"role": "assistant", "content": reply.content})
                    end = ""
                    if reply.stop_reason == "max_tokens":
                        end = f"\n[the reply was cut at max_tokens {self.settings['max_tokens']}: /max raises it]\n"
                    elif reply.stop_reason not in ("tool_use", "end_turn", "stop_sequence", "pause_turn"):
                        end = f"\n[stop: {reply.stop_reason}]\n"
                if tools and reply.stop_reason != "tool_use":
                    self.history.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": get(b, "id"), "is_error": True,
                         "content": f"not run: the response ended with {reply.stop_reason}"}
                        for b in tools]})
                    tools = []
                end += self.long_warning(reply.usage)
                if reply.stop_reason == "pause_turn":
                    continue
                if not tools:
                    self.partial = []
                    self.out.extend(ord(c) for c in ascii_text(end))
                    self.out.append(EOT)
                    return
                self.pending = [get(b, "id") for b in tools]
                self.partial = []
                self.state = "tool"
            results = []
            for b in tools:
                content, error = self.run_tool(get(b, "name"), get(b, "input"), gen)
                if gen != self.gen:
                    return
                result = {"type": "tool_result", "tool_use_id": get(b, "id"), "content": content}
                if error:
                    result["is_error"] = True
                results.append(result)
            with self.lock:
                if gen != self.gen:
                    return
                self.history.append({"role": "user", "content": results})
                self.pending = []
                self.state = "answering"
        self.push_end(f"\n[{TOOL_ROUNDS} tool calls in one turn: stopped there; say go on]\n", gen)

    def run_tool(self, name: str, data, gen: int):
        """(content for the tool_result, is_error)."""
        problem = check_input(name, data)
        if problem:
            return json.dumps({"INVALID_INPUT": problem, "input": data}, default=str), True
        try:
            if name == "run_command":
                command = data["command"]
                if "\n" in command or not command.strip() or len(command) > 255:
                    return "the command must be one non-empty line of at most 255 chars", True
                ask = "R" if self.settings["approve"] else "r"
                return self.cpu_tool(gen, ask, str(self.settings["timeout"]),
                                     ascii_text(command), ascii_text(data.get("input", ""), tabs=True))
            if name == "write_file":
                ask = "W" if self.settings["approve"] else "w"
                return self.cpu_tool(gen, ask, ascii_text(data["path"]),
                                     ascii_text(data["content"], tabs=True))
            if name == "read_host_file":
                self.push(f"\n[claude reads {ascii_text(data['path'])} on the PC]\n", gen)
                return read_host_file(self.access, data["path"]), False
            if name == "list_host_dir":
                self.push(f"\n[claude lists {ascii_text(data['path']) or 'the permitted paths'} on the PC]\n", gen)
                return list_host_dir(self.access, data["path"]), False
            if name == "write_host_file":
                self.push(f"\n[claude writes {ascii_text(data['path'])} on the PC]\n", gen)
                return write_host_file(self.access, data["path"], data["content"]), False
            if name == "screenshot":
                self.push("\n[claude looks at the RGB screen]\n", gen)
                if self.screenshot is None:
                    return "no screen here", True
                import base64
                png = base64.standard_b64encode(self.screenshot()).decode("ascii")
                return [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": png}}], False
        except (AccessError, OSError) as e:
            self.push(f"[refused: {ascii_text(str(e))}]\n", gen)
            return str(e), True
        return f"no tool called {name}", True

    def cpu_tool(self, gen: int, letter: str, *fields: str):
        """Send a tool to the CPU and wait for its answer (or the turn's end)."""
        frame = chr(STX) + letter + chr(US).join(fields) + chr(ETX)
        with self.lock:
            if gen != self.gen:
                return "stopped", True
            while not self.results.empty():         # an answer left from a turn that was stopped
                self.results.get_nowait()
            self.waiting_tool = True
            self.out.extend(ord(c) for c in frame)
        while True:
            try:
                result = self.results.get(timeout=0.2)
            except queue.Empty:
                if gen != self.gen:
                    return "stopped", True
                continue
            if result is None or gen != self.gen:
                return "stopped", True
            if len(result) > RESULT_CAP:
                result = result[:RESULT_CAP] + f"\n[... cut at {RESULT_CAP} chars]"
            return result, False

    # ------------------------------------------------------------ cost
    def price(self, usage: dict) -> float:
        p_in, p_out, long = MODELS.get(self.settings["model"], (0.0, 0.0, None))
        prompt = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                "cache_creation_input_tokens"))
        if long and prompt > long[0]:
            p_in, p_out = long[1], long[2]
        return (usage.get("input_tokens", 0) * p_in
                + usage.get("cache_read_input_tokens", 0) * p_in * CACHE_READ
                + usage.get("cache_creation_input_tokens", 0) * p_in * CACHE_WRITE
                + usage.get("output_tokens", 0) * p_out) / 1e6

    def count(self, usage: dict) -> None:
        self.usage["requests"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                  "cache_creation_input_tokens"):
            self.usage[k] += usage.get(k, 0)
        self.usage["dollars"] += self.price(usage)

    def long_warning(self, usage: dict) -> str:
        prompt = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                "cache_creation_input_tokens"))
        if prompt > LONG_PROMPT and not self.warned_long:
            self.warned_long = True
            return (f"\n[the conversation is {prompt} tokens long: the whole of it is sent "
                    f"again every turn, and past {LONG_PROMPT} tokens it costs more. "
                    f"/clear starts over]\n")
        return ""

    # ------------------------------------------------------------ slash commands
    def command(self, line: str) -> str:
        """A line starting with '/': handled here, never sent to Claude."""
        words = line.split()
        name, args = words[0].lower(), words[1:]
        s = self.settings
        arg = args[0] if args else ""
        if name == "/help":
            return ("/model [NAME]       the model (haiku, sonnet, opus, fable or an id)\n"
                    "/effort [LEVEL]     low medium high xhigh max\n"
                    "/max [N]            max_tokens of a reply\n"
                    "/clear              a new conversation (the history is forgotten)\n"
                    "/usage              tokens and dollars since the simulator started\n"
                    "/tools [on|off]     let Claude use its tools\n"
                    "/timeout [S]        seconds a command may run on the CPU\n"
                    "/approve [on|off]   ask y/n before each command or file written\n"
                    "/reload             read tynix/cpu_claude.md again\n"
                    "/access             the PC paths Claude may use\n"
                    "/help               this list\n")
        if name == "/model":
            if not arg:
                return (f"model {s['model']}\n" + "".join(
                    f"  {m}  ${p[0]:.2f} / ${p[1]:.2f} per M tokens in / out\n"
                    for m, p in MODELS.items()))
            model = ALIASES.get(arg.lower(), arg.lower())
            if model not in MODELS:
                return f"unknown model {arg}: {', '.join(ALIASES)} or {', '.join(MODELS)}\n"
            s["model"] = model
            return f"model {model} (the next turn; the cache starts again)\n"
        if name == "/effort":
            if not arg:
                return f"effort {s['effort']}\n"
            if arg.lower() not in EFFORTS:
                return f"effort: one of {' '.join(EFFORTS)}\n"
            s["effort"] = arg.lower()
            return f"effort {s['effort']}\n"
        if name == "/max":
            if not arg:
                return f"max_tokens {s['max_tokens']}\n"
            if not arg.isdigit() or not 1 <= int(arg) <= MAX_OUTPUT:
                return f"max: a number from 1 to {MAX_OUTPUT}\n"
            s["max_tokens"] = int(arg)
            return f"max_tokens {s['max_tokens']}\n"
        if name == "/clear":
            self.new_conversation()
            return "new conversation\n"
        if name == "/usage":
            u = self.usage
            return (f"{u['requests']} requests, {u['input_tokens']} input tokens "
                    f"(+{u['cache_read_input_tokens']} read from the cache, "
                    f"{u['cache_creation_input_tokens']} written to it), "
                    f"{u['output_tokens']} output: about ${u['dollars']:.4f}\n"
                    f"this conversation: {len(self.history)} messages\n")
        if name in ("/tools", "/approve"):
            key = name[1:]
            if arg.lower() in ("on", "off"):
                s[key] = arg.lower() == "on"
            elif arg:
                return f"{name} on|off\n"
            return f"{key} {'on' if s[key] else 'off'}\n"
        if name == "/timeout":
            if not arg:
                return f"timeout {s['timeout']} s\n"
            if not arg.isdigit() or not 1 <= int(arg) <= 3600:
                return "timeout: seconds, 1 to 3600\n"
            s["timeout"] = int(arg)
            return f"timeout {s['timeout']} s\n"
        if name == "/reload":
            with self.lock:
                self.system = self.load_system()
            return f"read {self.system_file.name}: {len(self.system)} chars\n"
        if name == "/access":
            return ascii_text(self.access.listing()) + "\n"
        return f"unknown command {name}: /help lists them\n"

    def status(self) -> str:
        """One short line for the window."""
        return f"{self.state} ${self.usage['dollars']:.3f}"
