# Design Document

## Feature: trap-core

---

## Overview

`trap-core` implements the fake SSH server ("The Trap") and its interactive shell simulator ("The Ghost Shell") for Haunted Honeypot. It accepts inbound SSH connections, authenticates via a configurable weak-credential list, and presents a believable decommissioned-server environment — all without executing any attacker input or making unsanctioned outbound calls.

Every login attempt, command, and response is persisted as structured events in a per-session JSON Lines file (`{LOG_DIR}/{session_id}.jsonl`). This file is the handoff point to the Brain; the trap runtime and the Brain share no live database path.

The implementation is pure Python 3.12 with `asyncssh` and `aiofiles`. All processing is async; no blocking calls appear on the event loop. Type hints are complete; the package must pass `mypy --strict`. `bandit` must report no high-severity findings.

### Goals

- Capture real attacker behaviour (credentials tried, commands issued, download URLs) without executing anything.
- Remain convincing long enough for the attacker to reveal intent.
- Hand off structured event data to the Brain with zero data loss.
- Be provably safe: property-based tests verify robustness invariants for arbitrary input.

### Non-goals (this feature)

- LLM-powered shell responses (a later spec provides a real LLM backend).
- Brain ingestion, ATT&CK mapping, or the dashboard.
- Protocols other than SSH.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  trap/                                                      │
│                                                             │
│  config.py          – env-var loader, typed Config object   │
│  server.py          – asyncssh SSH server, auth handler     │
│  auth/                                                      │
│    tracker.py       – rolling-window attempt counter        │
│  ghost/                                                     │
│    shell.py         – per-session coroutine, prompt loop    │
│    filesystem.py    – in-memory FakeNode tree, per-session  │
│    dispatcher.py    – command registry, chain tokeniser     │
│    commands/        – one module per command group          │
│      navigation.py  – pwd, cd, ls                           │
│      files.py       – cat, touch, rm, mkdir, chmod         │
│      info.py        – whoami, id, uname, hostname, echo     │
│      history.py     – history                               │
│      download.py    – wget, curl                            │
│      exit_.py       – exit                                  │
│    llm.py           – LLM_Interface ABC + ScriptedFallback  │
│    logger.py        – async event writer (aiofiles)         │
│  models.py          – Session, Event, FakeNode, SessionContext│
│  ghost/fs_template.yaml – filesystem seed data             │
└─────────────────────────────────────────────────────────────┘
```

### Request flow

```
Attacker TCP → asyncssh server.py
                ↓  connection_made → open EventLogger → session_start Event
                ↓  password_auth_requested (credential set + attempt tracker)
                ↓  login_attempt Event → logger
                ↓  (if rejected, on connection_lost) → session_end("disconnect") → close EventLogger
                ↓  (if accepted) shell.py session coroutine (EventLogger handed over)
                      ↓  MOTD + prompt loop
                      ↓  dispatcher.py (chain tokeniser → handler registry)
                      ↓  command handler (filesystem.py / commands/)
                      ↓  command + response Events → logger
                      ↓  output returned to attacker
                ↓  session_end Event → logger → flush + close
```

### Concurrency model

- The `asyncssh` server runs entirely on a single asyncio event loop.
- Each SSH session is a lightweight asyncio coroutine. 50+ concurrent sessions are supported without threads.
- `aiofiles` is used for all file I/O so log writes never block the loop.
- The attempt tracker uses an in-memory dict; it is only accessed from the event loop (no locks needed).

---

## Components and Interfaces

### `trap/config.py` — Config loader

Reads all environment variables at startup, validates them, and returns a frozen `Config` dataclass. Any missing required variable or invalid value causes an immediate logged error and `sys.exit(1)`.

```python
@dataclasses.dataclass(frozen=True)
class Config:
    trap_port: int                    # TRAP_PORT, default 2222
    host_key_path: Path               # TRAP_HOST_KEY_PATH, required
    credential_file: Path             # TRAP_CREDENTIAL_FILE, required
    log_dir: Path                     # TRAP_LOG_DIR, required
    idle_timeout_seconds: int         # TRAP_IDLE_TIMEOUT_SECONDS, default 300
    max_session_seconds: int          # TRAP_MAX_SESSION_SECONDS, default 1800
    max_input_line: int               # hard-coded 4096
    accept_after_attempts: int | None # TRAP_ACCEPT_AFTER_ATTEMPTS, optional
    llm_backend: str                  # TRAP_LLM_BACKEND, default "scripted"
    llm_api_url: str | None           # TRAP_LLM_API_URL, optional

def load_config() -> Config: ...
```

Validation rules:
- `TRAP_PORT` must be an integer in `[1, 65535]`.
- `TRAP_HOST_KEY_PATH` and `TRAP_CREDENTIAL_FILE` must be non-empty strings; parent directory of the key path must be writable.
- `TRAP_LOG_DIR` must be a non-empty string; directory is created if absent.
- `TRAP_IDLE_TIMEOUT_SECONDS` and `TRAP_MAX_SESSION_SECONDS` must be positive integers.
- `TRAP_ACCEPT_AFTER_ATTEMPTS`, when present, must be a positive integer.

### `trap/server.py` — SSH server

Wraps `asyncssh.create_server`. Owns host key lifecycle, the password-auth handler, and the `EventLogger` lifecycle.

Key responsibilities:
- On startup: load or generate Ed25519 host key via `asyncssh.generate_private_key` / `asyncssh.read_private_key`.
- Register `TrapServer` (subclass of `asyncssh.SSHServer`) which overrides `connection_made`, `password_auth_requested`, and `connection_lost`.
- `connection_made`: assigns a `session_id`, opens the `EventLogger`, and writes a `session_start` Event.
- Auth handler checks `(username, password) in creds` where `creds: set[tuple[str, str]]`, consults the attempt tracker, records a `login_attempt` event, and returns `True`/`False`.
- On accepted auth, hands the already-open `EventLogger` to `run_shell()`; sets `self._shell_took_over = True` so `connection_lost` does not write a duplicate `session_end`.
- On connection close without successful auth: `connection_lost` writes a `session_end` Event with `reason="disconnect"` and closes the `EventLogger`.

```python
class TrapServer(asyncssh.SSHServer):
    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None: ...
    def password_auth_requested(self, username: str, password: str) -> bool: ...
    def connection_lost(self, exc: Exception | None) -> None: ...

async def start_server(config: Config) -> None: ...
```

### `trap/auth/tracker.py` — Attempt tracker

Tracks per-IP authentication attempt counts within a rolling one-hour window. Pure in-memory structure; no external storage.

**Data structure:**
- An `OrderedDict[str, deque[datetime]]` mapping each source IP to a deque of UTC timestamps of authentication attempts from that IP.
- The `OrderedDict` insertion/access order is used to track recency: on every access to an IP's entry, that IP is moved to the end (most-recently-seen).

**Memory caps (both enforced on every `record_attempt` call):**
1. **Per-IP timestamp cap:** Each IP's deque holds at most `n + 1` timestamps, where `n` is the configured `TRAP_ACCEPT_AFTER_ATTEMPTS` threshold (or a safe default of 101 when the threshold is not configured). If the deque is already at capacity, the oldest timestamp is discarded before appending the new one.
2. **IP count cap:** The `OrderedDict` holds at most 10,000 IPs. When a new IP would exceed this limit, the least-recently-seen IP (the first entry in the `OrderedDict`) is evicted before inserting the new one.

**Pruning:**
- On every call to `record_attempt(src_ip)` and `should_accept(src_ip, n)`, timestamps older than 1 hour from the current UTC time are pruned from the left of that IP's deque before any other logic.
- If pruning empties an IP's deque, the IP key is removed from the `OrderedDict`.

```python
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone

MAX_TRACKED_IPS: int = 10_000

class AttemptTracker:
    def __init__(self, max_attempts_per_ip: int = 101) -> None:
        self._window: OrderedDict[str, deque[datetime]] = OrderedDict()
        self._max_per_ip: int = max_attempts_per_ip

    def record_attempt(self, src_ip: str) -> None:
        """Record one attempt from src_ip; enforces both memory caps."""

    def should_accept(self, src_ip: str, n: int) -> bool:
        """Return True if attempt count from src_ip within the last hour >= n."""

    def _prune_ip(self, src_ip: str) -> None:
        """Remove timestamps older than 1 hour for src_ip; remove key if deque empty."""

    def _move_to_end(self, src_ip: str) -> None:
        """Mark src_ip as most-recently-seen in the OrderedDict."""
```

### `trap/ghost/shell.py` — Ghost Shell session

Per-connection asyncio coroutine. Manages prompt loop, session limits, and event logging lifecycle.

```python
async def run_shell(
    process: asyncssh.SSHServerProcess,
    config: Config,
    session: Session,
    fs: FakeFilesystem,
    dispatcher: Dispatcher,
    logger: EventLogger,
) -> None: ...
```

Sequence within `run_shell`:
1. Send MOTD.
2. Enter prompt loop:
   - Send prompt string (`[user@records-srv-09 ~]#`).
   - `asyncio.wait_for(process.stdin.readline(), timeout=idle_timeout)` — raises `asyncio.TimeoutError` on idle.
   - Truncate input at `max_input_line` chars; if over-length, send `bash: line too long` and continue.
   - Dispatch command, collect output.
   - Write `command` + `response` events.
   - Send output.
3. On clean exit (Entity ran `exit`): write `session_end` with `reason="exit"`.
4. On `asyncio.TimeoutError` (idle): write `session_end` with `reason="idle_timeout"`.
5. On max-duration exceeded (outer `asyncio.timeout` wrapping the loop): write `session_end` with `reason="max_duration"`.
6. On SSH disconnect: write `session_end` with `reason="disconnect"`.

Max duration is enforced by wrapping the entire prompt loop in `asyncio.timeout(config.max_session_seconds)`.

### `trap/ghost/filesystem.py` — Fake Filesystem

An in-memory tree of `FakeNode` objects. Seeded from `fs_template.yaml` via deep copy per session, ensuring complete isolation between concurrent sessions.

> **YAML loading safety:** `fs_template.yaml` MUST be loaded with `yaml.safe_load` only. `yaml.load` (without an explicit Loader argument) is forbidden anywhere in `trap/`.

```python
@dataclasses.dataclass
class FakeNode:
    name: str
    is_dir: bool
    content: str          # empty string for directories
    permissions: str      # e.g. "-rw-r--r--" or "drwxr-xr-x"
    owner: str            # e.g. "root"
    size: int             # bytes (for display in ls -la)
    mtime: str            # static display string, e.g. "Jan 15  2009"
    children: dict[str, "FakeNode"] | None  # None for files, dict for dirs

class FakeFilesystem:
    def __init__(self, template: FakeNode) -> None:
        self._root: FakeNode = copy.deepcopy(template)
        self._cwd: list[str] = []   # path components from root

    def cwd_path(self) -> str: ...
    def resolve(self, path: str) -> FakeNode | None: ...
    def mkdir(self, path: str) -> None: ...
    def touch(self, path: str) -> None: ...
    def rm(self, path: str, recursive: bool = False) -> None: ...
    def cat(self, path: str) -> str: ...
    def ls(self, path: str | None = None) -> list[FakeNode]: ...
    def chmod(self, path: str, mode: str) -> None: ...
    def cd(self, path: str) -> None: ...
    def create_file(self, path: str, content: str = "") -> None: ...
```

Path resolution handles absolute paths (starting with `/`) and relative paths. `..` and `.` are supported. The `~` prefix in prompts is computed by `cwd_path()` comparing the current path against the authenticated user's home directory.

### `trap/ghost/dispatcher.py` — Command dispatcher and chain tokeniser

The dispatcher holds a registry mapping command names to handler callables. It also contains the chain tokeniser for `;`, `&&`, and `|`.

```python
HandlerFn = Callable[[list[str], SessionContext], Awaitable[CommandResult]]

@dataclasses.dataclass
class CommandResult:
    output: str
    is_error: bool   # True if the response would go to stderr (used by &&)

class Dispatcher:
    def register(self, name: str, handler: HandlerFn) -> None: ...
    async def dispatch(self, raw_input: str, ctx: SessionContext) -> str: ...
    async def _dispatch_single(self, tokens: list[str], ctx: SessionContext) -> CommandResult: ...
    def _tokenise_chain(self, raw: str) -> list[tuple[str, list[str]]]: ...
        # returns list of (operator, tokens) where operator is ";", "&&", "|", or "" for the first
```

Chain tokenisation rules (pure Python, no subprocess):
- Split on `&&` first, then `;`, handling them as different precedence levels.
- Pipe (`|`) is detected within a single segment and treated as best-effort: left output is passed as the last argument to the right command handler.
- Tokenisation is done with a simple state machine that respects single- and double-quoted strings (no nested quotes required).
- If a handler raises an exception, the dispatcher catches it, logs it, and continues with remaining tokens in the chain.

`_dispatch_single` path-execution check: **before** looking up the command in the handler registry, if `tokens[0]` starts with `./` or `/`:
- If the basename of the path is in `ctx.downloaded_files`: return `CommandResult(output="Segmentation fault (core dumped)", is_error=True)`.
- Otherwise: return `CommandResult(output=f"bash: {tokens[0]}: No such file or directory", is_error=True)`.

### `trap/ghost/commands/` — Command handlers

Each module is a collection of pure async functions registered with the dispatcher at startup. All handlers receive `(args: list[str], ctx: SessionContext)` and return `CommandResult`.

| Module | Commands |
|---|---|
| `navigation.py` | `pwd`, `cd`, `ls` |
| `files.py` | `cat`, `touch`, `rm`, `mkdir`, `chmod` |
| `info.py` | `whoami`, `id`, `uname`, `hostname`, `echo` |
| `history.py` | `history` |
| `download.py` | `wget`, `curl` |
| `exit_.py` | `exit` |

All handlers are small, pure functions. They call methods on `ctx.fs` (the `FakeFilesystem`) and return a string. No handler touches the real filesystem or makes network calls.

`exit` signals the shell loop to close by raising a sentinel exception `SessionExitRequested` (caught by `shell.py`).

`download.py` after creating the fake file in the Fake Filesystem, also adds the basename to `ctx.downloaded_files` so the dispatcher can detect later execution attempts.

### `trap/ghost/llm.py` — LLM Interface

```python
import abc

class LLMInterface(abc.ABC):
    @abc.abstractmethod
    async def respond(
        self, session_context: SessionContext, command: str
    ) -> str: ...

class ScriptedFallback(LLMInterface):
    async def respond(
        self, session_context: SessionContext, command: str
    ) -> str:
        cmd = command.split()[0] if command.split() else command
        return f"bash: {cmd}: command not found"
```

The dispatcher calls `llm.respond()` for any command not found in its registry. If `respond()` raises, the dispatcher catches the exception, logs it, and returns the `bash: <cmd>: command not found` fallback without closing the session.

### `trap/ghost/logger.py` — Event logger

```python
class EventLogger:
    def __init__(self, session_id: str, log_dir: Path) -> None: ...
    async def __aenter__(self) -> "EventLogger": ...
    async def __aexit__(self, *args: object) -> None: ...  # flush + close

    async def write(self, event: Event) -> None: ...
```

Implementation uses `aiofiles.open` in append mode. Each call to `write()` serialises the `Event` dataclass to JSON using `dataclasses.asdict`, appends a newline, and calls `await f.flush()`. The file is not closed between writes; it is closed in `__aexit__`.

If `write()` raises an `OSError`, it logs to the process logger (`logging` module), re-raises for the shell loop to decide whether to continue or close the session (per Req 2.5: login_attempt errors are non-fatal; per Req 9.5: general log failures close the session).

---

## Data Models

All models live in `trap/models.py`.

### `Session`

```python
@dataclasses.dataclass
class Session:
    session_id: str          # uuid4 hex
    src_ip: str
    src_port: int
    username: str
    password: str
    client_version: str
    started_at: datetime     # UTC
    ended_at: datetime | None = None
```

### `Event`

```python
import typing

EventKind = typing.Literal[
    "login_attempt",
    "command",
    "response",
    "download_attempt",
    "session_start",
    "session_end",
]

SessionEndReason = typing.Literal[
    "exit", "idle_timeout", "max_duration", "disconnect", "log_error"
]

GeneratedBy = typing.Literal["scripted", "llm"]

@dataclasses.dataclass
class Event:
    session_id: str
    timestamp: str           # ISO-8601 UTC, e.g. "2024-01-15T10:23:45.123456Z"
    kind: EventKind
    payload: dict[str, object]
    generated_by: GeneratedBy
```

Payload schemas by kind:

| Kind | Required payload fields |
|---|---|
| `session_start` | `src_ip`, `src_port`, `client_version` |
| `login_attempt` | `src_ip`, `src_port`, `username`, `password`, `client_version`, `success` (bool) |
| `command` | `command` (str) |
| `response` | `output` (str) |
| `download_attempt` | `command` (str), `url` (str) |
| `session_end` | `reason` (SessionEndReason) |

### `FakeNode`

Defined in `trap/ghost/filesystem.py` (see Components section above).

### `SessionContext`

Passed to every command handler and the LLM interface. Encapsulates all mutable per-session state.

```python
@dataclasses.dataclass
class SessionContext:
    session: Session
    fs: FakeFilesystem
    history: list[str]       # commands issued this session, in order
    downloaded_files: set[str]   # basenames of files created by wget/curl
    config: Config
```

---

## Data Models — Fake Filesystem Seed

`trap/ghost/fs_template.yaml` defines the initial filesystem state loaded once at startup and deep-copied per session. Example structure:

```yaml
root:
  type: dir
  permissions: "drwxr-xr-x"
  owner: root
  mtime: "Jan 15  2009"
  children:
    etc:
      type: dir
      permissions: "drwxr-xr-x"
      owner: root
      mtime: "Jan 15  2009"
      children:
        hostname:
          type: file
          permissions: "-rw-r--r--"
          owner: root
          content: "records-srv-09\n"
          mtime: "Jan 15  2009"
    root:
      type: dir
      permissions: "drwx------"
      owner: root
      mtime: "Mar  3  2011"
      children: {}
    home:
      type: dir
      permissions: "drwxr-xr-x"
      owner: root
      mtime: "Jan 15  2009"
      children:
        caretaker:
          type: dir
          permissions: "drwxr-xr-x"
          owner: caretaker
          mtime: "Oct 31  2013"
          children:
            last_words.txt:
              type: file
              permissions: "-rw-r--r--"
              owner: caretaker
              mtime: "Oct 31  2013"
              content: |
                if anyone finds this — the vault has been locked since october.
                i don't know why the records keep changing. i haven't touched them.
                -H
    vault:
      type: dir
      permissions: "drwx------"
      owner: root
      mtime: "Oct 31  2013"
      children: {}
    var:
      type: dir
      permissions: "drwxr-xr-x"
      owner: root
      mtime: "Jan 15  2009"
      children:
        log:
          type: dir
          permissions: "drwxr-xr-x"
          owner: root
          mtime: "Jan 15  2009"
          children: {}
    tmp:
      type: dir
      permissions: "drwxrwxrwt"
      owner: root
      mtime: "Jan 15  2009"
      children: {}
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Ghost Shell robustness — arbitrary input never raises

*For any* string of up to 4096 characters, dispatching it through the Ghost Shell command dispatcher SHALL return a string result without raising an unhandled exception.

**Validates: Requirements 10.4, 11.1**

---

### Property 2: No-execution invariant — forbidden APIs never invoked

*For any* string input dispatched through the Ghost Shell, the execution path SHALL NOT invoke `subprocess`, `os.system`, `os.popen`, `pty`, `eval`, or `exec`.

**Validates: Requirements 10.1, 11.4, 8.5**

---

### Property 3: Filesystem isolation — sessions are independent

*For any* two concurrent sessions and any sequence of filesystem mutations applied to the first session, the second session's filesystem state SHALL remain unchanged.

**Validates: Requirements 4.5**

---

### Property 4: Credential authentication round-trip

*For any* username/password pair present in the credential set (a set of `(username, password)` tuples), the auth handler SHALL accept it (`(username, password) in credential_set` is `True`); *for any* username/password pair absent from the credential set (and where the attempt-count threshold is not met), the auth handler SHALL reject it.

**Validates: Requirements 2.1, 2.2**

---

### Property 5: Login attempt event completeness

*For any* authentication attempt (accepted or rejected), a `login_attempt` Event SHALL be written to the Session_Log containing `session_id`, `src_ip`, `src_port`, `username`, `password`, `client_version`, `timestamp`, and `success`.

**Validates: Requirements 2.3**

---

### Property 6: Credential list parse round-trip

*For any* list of `username:password` pairs serialised in the credential file format, parsing the file SHALL recover all pairs exactly, with no additions or omissions.

**Validates: Requirements 1.4**

---

### Property 7: Config validation rejects invalid values

*For any* environment variable value that violates its validation rule (e.g. non-integer port, port out of range, empty required path), `load_config()` SHALL raise a configuration error and exit rather than returning a `Config` object.

**Validates: Requirements 1.6**

---

### Property 8: mkdir → ls round-trip

*For any* valid directory name in any existing directory of the Fake Filesystem, after a successful `mkdir` the parent directory's `ls` output SHALL contain that name.

**Validates: Requirements 5.10, 11.2**

---

### Property 9: rm → cat round-trip

*For any* existing file in the Fake Filesystem, after a successful `rm` a subsequent `cat` of that path SHALL return an error string and SHALL NOT return the file's previous contents.

**Validates: Requirements 5.12, 11.3**

---

### Property 10: Filesystem command correctness — pwd, cd, cat, touch, chmod

*For any* valid path in the Fake Filesystem:
- `pwd` returns the current working directory path as a string.
- `cd <path>` to an existing directory changes the cwd; `cd` to a non-existent path returns an error without changing cwd.
- `cat <file>` returns the exact byte-for-byte content of the file.
- `touch <name>` in any directory creates that file if absent (subsequent `cat` returns empty string, not error).
- `chmod <mode> <path>` updates the node's permissions string; `ls -la` reflects the new mode.

**Validates: Requirements 5.1, 5.2, 5.4, 5.11, 5.14**

---

### Property 11: Prompt format correctness

*For any* authenticated username and any current working directory path, the rendered prompt SHALL match the format `[username@records-srv-09 <display_cwd>]#` (root) or `[username@records-srv-09 <display_cwd>]$` (non-root), with the user's home directory prefix replaced by `~`.

**Validates: Requirements 4.3**

---

### Property 12: echo is identity on its arguments

*For any* list of argument tokens, `echo` SHALL return those tokens joined by a single space with no shell variable expansion, as a single output line.

**Validates: Requirements 5.9**

---

### Property 13: ScriptedFallback command-not-found format

*For any* command string passed to `ScriptedFallback.respond()`, the returned string SHALL be `bash: <first_token>: command not found`, where `<first_token>` is the first whitespace-delimited token of the command.

**Validates: Requirements 7.3**

---

### Property 14: LLM exception fallback — session stays open

*For any* exception type raised by `LLMInterface.respond()`, the Ghost Shell SHALL return the `bash: <cmd>: command not found` fallback output, log the exception, and leave the session open.

**Validates: Requirements 7.5**

---

### Property 15: Semicolon chain — all tokens execute

*For any* sequence of commands joined by `;`, all commands SHALL be executed in order and their outputs concatenated in the result.

**Validates: Requirements 8.1**

---

### Property 16: `&&` operator — right executes only on left success

*For any* pair of commands joined by `&&`, the right command SHALL execute if and only if the left command produces a non-error result; if the left command is an error, only the left output is returned.

**Validates: Requirements 8.2**

---

### Property 17: Chain exception isolation

*For any* chain of commands where one token raises an exception, the remaining tokens in the chain SHALL still execute (exception is logged, not propagated).

**Validates: Requirements 8.4**

---

### Property 18: Session_Log validity — JSON Lines round-trip

*For any* sequence of commands dispatched in a session, every line written to the Session_Log SHALL be a valid JSON object with the required `Event` fields (`session_id`, `timestamp`, `kind`, `payload`, `generated_by`), and serialising then deserialising each Event SHALL produce an equivalent object.

**Validates: Requirements 9.2, 11.5, 11.6**

---

### Property 19: Download simulation — no real network, fake file created

*For any* URL string passed to `wget` or `curl`:
- A `download_attempt` Event SHALL be recorded with the full command and the parsed URL.
- The output returned to the Entity SHALL be a non-empty string (plausible progress/stats).
- No outbound network request SHALL be made.
- A fake empty file named after the last path segment of the URL SHALL be created in the Fake Filesystem's current working directory.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.6**

---

### Property 20: Attempt-counter threshold acceptance

*For any* source IP and positive integer N configured as `TRAP_ACCEPT_AFTER_ATTEMPTS`, after N or more authentication attempts from that IP within a one-hour window, any password SHALL be accepted regardless of the credential list.

**Validates: Requirements 2.7**

---

### Property 21: Oversized input — discarded, session stays open

*For any* input string exceeding 4096 characters, the Ghost Shell SHALL return `bash: line too long`, discard the input, and leave the session open (not close it).

**Validates: Requirements 3.5**

---

### Property 22: AttemptTracker memory is bounded

*For any* sequence of `record_attempt` calls with any combination of source IPs and timestamps, the `AttemptTracker` internal state SHALL satisfy:
- The number of tracked IPs SHALL never exceed 10,000.
- The number of timestamps stored per IP SHALL never exceed `max_attempts_per_ip` (`n + 1`).
- Total memory consumed by the tracker SHALL therefore be O(10,000 × (n + 1)) regardless of input volume.

**Validates: Requirements 2.7**

---

### Property 23: Executing a downloaded file returns segfault; executing an unknown path returns command-not-found

*For any* filename previously created by a simulated `wget` or `curl` command, attempting to execute `./<filename>` or the absolute path SHALL return `Segmentation fault (core dumped)`.

*For any* path token starting with `./` or `/` that was NOT created by a download, the dispatcher SHALL return `bash: <path>: No such file or directory`.

**Validates: Requirements 6.5**

---

## Error Handling

### Startup errors

- Invalid or missing environment variables: log descriptive message to stderr, `sys.exit(1)`. Never start listening with a partial config.
- Host key directory not writable: same as above.

### Runtime errors

| Situation | Behaviour |
|---|---|
| `login_attempt` log write fails | Log to process logger; continue accepting connections (Req 2.5) |
| Session log cannot be created | Close the session with SSH error; write reason to process log (Req 9.5) |
| Session log write fails mid-session | Close session with `reason="log_error"`; write to process log |
| LLM interface raises | Return `bash: <cmd>: command not found`; log exception; keep session open |
| Command handler raises unexpectedly | Same as LLM exception: fallback output, log, keep session open |
| Idle timeout | Write `session_end` with `reason="idle_timeout"`; close SSH channel |
| Max duration | Write `session_end` with `reason="max_duration"`; close SSH channel |
| Input over `max_input_line` | Send `bash: line too long`; discard input; continue loop |
| SSH client disconnects | Write `session_end` with `reason="disconnect"` |

### Cascading failure guard

The outermost session coroutine (`run_shell`) wraps the entire prompt loop in a broad `try/except Exception`. Any uncaught exception causes the session to close with `reason="disconnect"` and the exception to be logged, rather than crashing the server.

---

## Testing Strategy

### Unit tests (`tests/test_unit_*.py`)

Focus on specific examples, edge cases, and error conditions. Written with `pytest`.

- `test_unit_config.py`: valid/invalid env var combinations, default values.
- `test_unit_filesystem.py`: path resolution, mkdir/rm/touch/chmod with concrete inputs, `..` traversal, absolute paths.
- `test_unit_dispatcher.py`: semicolon chains, `&&` success/failure, pipe passthrough, unknown commands, exception isolation.
- `test_unit_commands.py`: each command handler with representative inputs.
- `test_unit_logger.py`: event serialisation, flush behaviour, file-write error handling.
- `test_unit_tracker.py`: attempt counting, window expiry, threshold acceptance.
- `test_unit_llm.py`: `ScriptedFallback` output, exception propagation from a mock LLM.

Avoid duplicating coverage already provided by property tests. Unit tests target concrete edge cases: `cd ..` from root, `rm -rf /`, `echo` with no args, `wget` with a bare domain URL, `cat` of a directory node.

### Property tests (`tests/test_properties.py`)

Written with `pytest` + `hypothesis`. Each test runs a minimum of 100 trials.

Each test is tagged with a comment referencing the design property it validates:
```python
# Feature: trap-core, Property 1: Ghost Shell robustness — arbitrary input never raises
```

Property test inventory (maps directly to Correctness Properties above):

| Test function | Property | Hypothesis strategy |
|---|---|---|
| `test_dispatch_never_raises` | P1 | `st.text(max_size=4096)` |
| `test_no_forbidden_api_invoked` | P2 | `st.text(max_size=4096)` |
| `test_filesystem_session_isolation` | P3 | `st.lists(st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=32), min_size=1, max_size=5)` |
| `test_credential_auth_roundtrip` | P4 | `st.lists(st.tuples(st.text(min_size=1, max_size=32), st.text(min_size=1, max_size=64)))` |
| `test_login_attempt_event_fields` | P5 | `st.tuples(st.ip_addresses(), st.integers(1024, 65535), st.text(min_size=1), st.text())` |
| `test_credential_file_parse_roundtrip` | P6 | `st.lists(st.tuples(st.text(min_size=1, max_size=32), st.text(min_size=1, max_size=64)))` |
| `test_config_rejects_invalid_port` | P7 | `st.one_of(st.text(), st.integers(max_value=0), st.integers(min_value=65536))` |
| `test_mkdir_ls_roundtrip` | P8 | `st.text(alphabet=st.characters(whitelist_categories=("L","N")), min_size=1, max_size=64)` |
| `test_rm_cat_roundtrip` | P9 | `st.text(alphabet=st.characters(whitelist_categories=("L","N")), min_size=1, max_size=64)` |
| `test_filesystem_command_correctness` | P10 | `st.text(min_size=1, max_size=64)` for paths and content |
| `test_prompt_format` | P11 | `st.text(min_size=1, max_size=32)` for usernames, `st.lists(st.text(min_size=1))` for cwd components |
| `test_echo_identity` | P12 | `st.lists(st.text(max_size=128), max_size=20)` |
| `test_scripted_fallback_format` | P13 | `st.text(min_size=1, max_size=256)` |
| `test_llm_exception_fallback` | P14 | `st.text(min_size=1)`, `st.from_type(Exception)` |
| `test_semicolon_chain_all_execute` | P15 | `st.lists(st.sampled_from(["pwd", "whoami", "hostname"]), min_size=2, max_size=5)` |
| `test_and_chain_conditional` | P16 | pairs of commands, one valid, one causing error |
| `test_chain_exception_isolation` | P17 | lists of commands including one that raises |
| `test_session_log_json_lines_roundtrip` | P18 | `st.lists(st.text(max_size=256), min_size=1, max_size=20)` |
| `test_download_simulation` | P19 | `st.from_regex(r'https?://[a-z0-9./\-]+\.[a-z]{2,}/[a-z0-9.\-]+')` |
| `test_attempt_counter_threshold` | P20 | `st.ip_addresses()`, `st.integers(min_value=1, max_value=10)` |
| `test_oversized_input_discarded` | P21 | `st.text(min_size=4097, max_size=8192)` |
| `test_attempt_tracker_memory_bounded` | P22 | `st.lists(st.ip_addresses(), min_size=1, max_size=50_000)` with `max_attempts_per_ip=5` |
| `test_downloaded_file_execution` | P23 | `st.from_regex(r'[a-z][a-z0-9_\-]{0,31}\.[a-z]{1,4}')` for filenames; verify segfault after download, command-not-found for unknown paths |

### Static analysis

Run in CI before tests:

```bash
ruff check trap/ tests/
bandit -r trap/ -ll   # fail on high-severity only
mypy --strict trap/
```

The `bandit` check is a hard gate; any high-severity finding blocks the merge. The no-execution invariant (Property 2) is verified both dynamically (P2 property test using `unittest.mock.patch`) and statically (bandit rule `B603`, `B602`, `B605`). `yaml.safe_load` is the only permitted YAML loader; `yaml.load` is banned and caught by `bandit` rule `B506`.

### Integration smoke test

`tests/test_integration.py` spins up a real `asyncssh` server on a random port and connects a test SSH client. Verifies:

- MOTD is received.
- `pwd` returns `/root` for a root login.
- `whoami` returns the authenticated username.
- The session log file is created with at least `session_start` and one `command` event.
- The server closes cleanly.

---

## Docker Configuration

```dockerfile
# trap/Dockerfile (sketch)
FROM python:3.12-slim
RUN useradd --uid 1001 --no-create-home trapuser
WORKDIR /app
COPY --chown=trapuser:trapuser . .
RUN pip install --no-cache-dir -r requirements.txt
USER trapuser
ENTRYPOINT ["python", "-m", "trap"]
```

`docker-compose.yml` service fragment:

```yaml
trap:
  build: ./trap
  read_only: true
  tmpfs:
    - /tmp
  volumes:
    - trap_keys:/app/keys         # host key persistence
    - trap_logs:/app/logs         # session logs
    - ./trap/credentials.txt:/app/credentials.txt:ro
  cap_drop:
    - ALL
  security_opt:
    - no-new-privileges:true
  mem_limit: 256m
  cpus: "0.5"
  environment:
    TRAP_PORT: "2222"
    TRAP_HOST_KEY_PATH: "/app/keys/host_ed25519"
    TRAP_CREDENTIAL_FILE: "/app/credentials.txt"
    TRAP_LOG_DIR: "/app/logs"
  ports:
    - "2222:2222"
```

The root filesystem is read-only (`read_only: true`). The only writable paths are the two named volumes (keys, logs) and a `/tmp` tmpfs. The trap container has no outbound network access except to `TRAP_LLM_API_URL` (which is empty in the scripted-fallback phase, so there is zero outbound traffic).
