# Implementation Plan: trap-core

## Overview

Implement the fake SSH server ("The Trap") and interactive shell simulator ("The Ghost Shell") for Haunted Honeypot. The implementation is pure Python 3.12 using `asyncssh` and `aiofiles`. Tasks are ordered foundation-first: scaffold and data models come first, then stateless leaf modules (filesystem, logger, LLM, commands), then the dispatcher and tracker that assemble those leaves, then the SSH server and Ghost Shell session that tie everything together, and finally tests and static-analysis gates.

## Tasks

- [ ] 1. Project scaffold and tooling
  - Create the full directory tree: `trap/`, `trap/auth/`, `trap/ghost/`, `trap/ghost/commands/`, `tests/`
  - Add `__init__.py` to every package directory
  - Write `pyproject.toml` with: `[project]` metadata, `[project.dependencies]` pinning `asyncssh`, `aiofiles`, `pyyaml`, `hypothesis`, `pytest`, `pytest-asyncio`; `[tool.ruff]` section targeting Python 3.12; `[tool.mypy]` with `strict = true`; `[tool.bandit]` with `targets = ["trap/"]`; `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`
  - Write `trap/Dockerfile` using the sketch from the design (python:3.12-slim, non-root `trapuser`, read-only root, pip install)
  - Write the `docker-compose.yml` service fragment for the `trap` service (read_only, tmpfs, named volumes, cap_drop ALL, mem_limit, ports)
  - _Requirements: 1.5, 10.5_

- [ ] 2. Data models (`trap/models.py`)
  - [ ] 2.1 Implement `Session`, `Event`, `SessionContext` dataclasses
    - Define `EventKind` Literal type alias for all 6 kinds: `login_attempt`, `command`, `response`, `download_attempt`, `session_start`, `session_end`
    - Define `SessionEndReason` Literal type alias: `exit`, `idle_timeout`, `max_duration`, `disconnect`, `log_error`
    - Define `GeneratedBy` Literal type alias: `scripted`, `llm`
    - Implement `Session` dataclass with all fields from the design (`session_id`, `src_ip`, `src_port`, `username`, `password`, `client_version`, `started_at`, `ended_at`)
    - Implement `Event` dataclass with `session_id`, `timestamp`, `kind`, `payload`, `generated_by`
    - Implement `SessionContext` dataclass with `session`, `fs` (typed as `FakeFilesystem` using `TYPE_CHECKING`), `history`, `config` (typed as `Config` using `TYPE_CHECKING`)
    - All fields must have complete type hints; file must pass `mypy --strict`
    - _Requirements: 9.2, 2.3_

  - [ ]* 2.2 Write unit tests for data models
    - Verify `Event` serialises to dict via `dataclasses.asdict` and all required fields are present
    - Verify `Session` `ended_at` defaults to `None`
    - _Requirements: 9.2_

- [ ] 3. Config loader (`trap/config.py`)
  - [ ] 3.1 Implement `Config` dataclass and `load_config()` function
    - Implement frozen `Config` dataclass matching the design spec (all 10 fields with correct types and defaults)
    - Implement `load_config()`: reads env vars, applies defaults, validates each rule from the design (port range, non-empty paths, positive integers, optional `TRAP_ACCEPT_AFTER_ATTEMPTS`)
    - On any validation failure: log a descriptive message to stderr and call `sys.exit(1)`
    - Hard-code `max_input_line = 4096` (not read from env)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_

  - [ ]* 3.2 Write unit tests for config loader (`tests/test_unit_config.py`)
    - Test all valid env-var combinations including defaults
    - Test each invalid case: non-integer port, port 0, port 66000, empty `TRAP_HOST_KEY_PATH`, empty `TRAP_CREDENTIAL_FILE`, non-integer timeout, non-positive integer timeout
    - Use `pytest.raises(SystemExit)` for failure cases
    - _Requirements: 1.6_

  - [ ]* 3.3 Write property test for config validation (Property 7)
    - **Property 7: Config validation rejects invalid values**
    - **Validates: Requirements 1.6**
    - Strategy: `st.one_of(st.text(), st.integers(max_value=0), st.integers(min_value=65536))` for port; verify `sys.exit(1)` is called
    - _Requirements: 1.6_

- [ ] 4. Fake Filesystem (`trap/ghost/filesystem.py` + `trap/ghost/fs_template.yaml`)
  - [ ] 4.1 Implement `FakeNode` dataclass and `FakeFilesystem` class
    - Implement `FakeNode` dataclass exactly as designed (`name`, `is_dir`, `content`, `permissions`, `owner`, `size`, `mtime`, `children`)
    - Implement `FakeFilesystem.__init__` that deep-copies the template root and initialises `_cwd = []`
    - Implement `cwd_path()` returning the absolute path string (e.g. `/root`)
    - Implement `resolve(path)` handling absolute paths, relative paths, `..`, `.`
    - Implement `cd(path)`: changes `_cwd`; raises `FileNotFoundError` (or custom error) for non-existent or non-directory paths
    - Implement `ls(path)`: returns list of child `FakeNode` objects; defaults to current directory
    - Implement `cat(path)`: returns file contents string; raises for missing or directory nodes
    - Implement `mkdir(path)`: creates directory node; raises if already exists
    - Implement `touch(path)`: creates empty file if absent, no-op if present
    - Implement `rm(path, recursive)`: removes node; raises for missing paths
    - Implement `chmod(path, mode)`: updates `permissions` field on the node
    - Implement `create_file(path, content)`: creates file with given content
    - Use `yaml.safe_load` (never `yaml.load`) for template loading; raise on unsafe loader
    - _Requirements: 4.4, 4.5, 5.1, 5.2, 5.3, 5.10, 5.11, 5.12, 5.14, 10.2_

  - [ ] 4.2 Write the filesystem template (`trap/ghost/fs_template.yaml`)
    - Define the full "records-srv-09" tree as shown in the design data model section
    - Must include: `/etc/hostname` (content: `records-srv-09\n`), `/root/` (empty dir), `/home/caretaker/last_words.txt` (lore content as shown), `/vault/` (empty dir), `/var/log/`, `/tmp/`
    - All nodes must have `type`, `permissions`, `owner`, `mtime`, `content` (for files) or `children` (for dirs) fields
    - _Requirements: 4.4, 4.2_

  - [ ]* 4.3 Write unit tests for filesystem (`tests/test_unit_filesystem.py`)
    - Test path resolution: absolute paths, relative paths, `..` traversal, `..` from root (stays at root), `.`
    - Test `cd` to existing dir, `cd` to non-existent path (error, cwd unchanged), `cd ..` from root
    - Test `mkdir` success, `mkdir` on existing path (error)
    - Test `touch` creates file, `touch` on existing file (no-op)
    - Test `rm` file success, `rm -rf` dir success, `rm` non-existent (error)
    - Test `cat` file contents, `cat` directory (error), `cat` non-existent (error)
    - Test `chmod` updates permissions, `chmod` non-existent (error)
    - Test `create_file` with content
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.10, 5.11, 5.12, 5.14_

  - [ ]* 4.4 Write property tests for filesystem (Properties 3, 8, 9, 10)
    - **Property 3: Filesystem isolation — sessions are independent**
    - **Property 8: mkdir → ls round-trip**
    - **Property 9: rm → cat round-trip**
    - **Property 10: Filesystem command correctness — pwd, cd, cat, touch, chmod**
    - **Validates: Requirements 4.5, 5.1, 5.2, 5.4, 5.10, 5.11, 5.12, 5.14**
    - _Requirements: 11.2, 11.3_

- [ ] 5. Event logger (`trap/ghost/logger.py`)
  - [ ] 5.1 Implement `EventLogger` async context manager
    - Open the session log file in append mode using `aiofiles.open` inside `__aenter__`
    - Implement `write(event)`: serialise via `dataclasses.asdict`, append JSON + newline, call `await f.flush()`
    - Implement `__aexit__`: flush and close the file handle
    - On `OSError` in `write()`: log to the process logger (`logging` module) and re-raise (caller decides severity)
    - Ensure the `LOG_DIR` path is created if it does not exist (using `aiofiles.os.makedirs` or `pathlib.Path.mkdir`)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 5.2 Write unit tests for event logger (`tests/test_unit_logger.py`)
    - Test that `write()` appends a valid JSON line to the file
    - Test that `write()` calls flush after each write
    - Test that `write()` re-raises `OSError`
    - Test that `__aexit__` closes the file
    - Use `tmp_path` pytest fixture for the log directory
    - _Requirements: 9.1, 9.2, 9.4, 9.5_

  - [ ]* 5.3 Write property test for session log JSON Lines round-trip (Property 18)
    - **Property 18: Session_Log validity — JSON Lines round-trip**
    - **Validates: Requirements 9.2, 11.5, 11.6**
    - Strategy: `st.lists(st.text(max_size=256), min_size=1, max_size=20)` for command strings; write events, read file, parse each line as JSON, verify all required fields present
    - _Requirements: 11.5, 11.6_

- [ ] 6. LLM interface (`trap/ghost/llm.py`)
  - [ ] 6.1 Implement `LLMInterface` ABC and `ScriptedFallback`
    - Define abstract base class `LLMInterface` with `async def respond(self, session_context: SessionContext, command: str) -> str`
    - Implement `ScriptedFallback.respond()`: split command on whitespace, return `f"bash: {cmd}: command not found"` where `cmd` is the first token (or the whole string if no whitespace)
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 6.2 Write unit tests for LLM interface (`tests/test_unit_llm.py`)
    - Test `ScriptedFallback` with multi-word command returns correct first-token format
    - Test `ScriptedFallback` with empty-ish command (single token)
    - Test dispatcher calls `llm.respond()` when command not in registry
    - Test dispatcher returns fallback and logs when `llm.respond()` raises any exception
    - _Requirements: 7.3, 7.5_

  - [ ]* 6.3 Write property tests for ScriptedFallback and LLM exception handling (Properties 13, 14)
    - **Property 13: ScriptedFallback command-not-found format**
    - **Property 14: LLM exception fallback — session stays open**
    - **Validates: Requirements 7.3, 7.5**
    - Strategy for P13: `st.text(min_size=1, max_size=256)`; verify format `bash: <first_token>: command not found`
    - Strategy for P14: `st.text(min_size=1)` + mock LLM that raises; verify fallback returned and session not closed
    - _Requirements: 7.3, 7.5_

- [ ] 7. Command handlers — navigation and info (`trap/ghost/commands/navigation.py`, `trap/ghost/commands/info.py`)
  - [ ] 7.1 Implement navigation commands (`pwd`, `cd`, `ls`)
    - `pwd`: calls `ctx.fs.cwd_path()`, returns it as output string
    - `cd <path>`: calls `ctx.fs.cd(path)`; on error returns `bash: cd: <path>: No such file or directory`; `cd` with no args changes to the authenticated user's home directory
    - `ls [path] [-la]`: calls `ctx.fs.ls(path)`; plain `ls` returns space-separated names; `ls -la` returns formatted table with permissions, owner, size, mtime columns
    - All handlers return `CommandResult(output=..., is_error=False/True)`
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 7.2 Implement info commands (`whoami`, `id`, `uname`, `hostname`, `echo`)
    - `whoami`: returns `ctx.session.username`
    - `id`: returns `uid=0(root) gid=0(root) groups=0(root)` for root; non-root equivalent otherwise
    - `uname -a`: returns the 2009-era kernel version string from the design (`Linux records-srv-09 2.6.18-92.el5 #1 SMP ...`)
    - `hostname`: returns `records-srv-09`
    - `echo <args>`: joins args with single space; no variable expansion (`$PATH` returned literally)
    - _Requirements: 5.5, 5.6, 5.7, 5.8, 5.9_

  - [ ]* 7.3 Write unit tests for navigation and info commands (`tests/test_unit_commands.py` — navigation/info section)
    - Test each command with representative inputs
    - Test `cd` to non-existent path returns error without changing cwd
    - Test `ls -la` output includes all required columns
    - Test `echo` with no args, single arg, multiple args, `$PATH` literal
    - Test `id` for root vs non-root username
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6, 5.7, 5.8, 5.9_

  - [ ]* 7.4 Write property tests for echo identity and prompt format (Properties 11, 12)
    - **Property 11: Prompt format correctness**
    - **Property 12: echo is identity on its arguments**
    - **Validates: Requirements 4.3, 5.9**
    - Strategy for P11: `st.text(min_size=1, max_size=32)` for usernames, `st.lists(st.text(min_size=1))` for cwd components
    - Strategy for P12: `st.lists(st.text(max_size=128), max_size=20)`
    - _Requirements: 4.3, 5.9_

- [ ] 8. Command handlers — files, history, download, exit (`trap/ghost/commands/files.py`, `trap/ghost/commands/history.py`, `trap/ghost/commands/download.py`, `trap/ghost/commands/exit_.py`)
  - [ ] 8.1 Implement file commands (`cat`, `touch`, `rm`, `mkdir`, `chmod`)
    - `cat <file>`: calls `ctx.fs.cat(path)`; on error returns `cat: <file>: No such file or directory`
    - `touch <file>`: calls `ctx.fs.touch(path)`, returns empty string
    - `rm [-rf] <path>`: calls `ctx.fs.rm(path, recursive="-rf" in args)`; on error returns `rm: cannot remove '<path>': No such file or directory`
    - `mkdir <path>`: calls `ctx.fs.mkdir(path)`; on collision returns `mkdir: cannot create directory '<path>': File exists`
    - `chmod <mode> <path>`: calls `ctx.fs.chmod(path, mode)`; on error returns `chmod: cannot access '<path>': No such file or directory`
    - _Requirements: 5.4, 5.10, 5.11, 5.12, 5.14_

  - [ ] 8.2 Implement history command (`trap/ghost/commands/history.py`)
    - `history`: formats `ctx.history` as a numbered list (1-indexed), one entry per line, e.g. `    1  pwd`
    - _Requirements: 5.13_

  - [ ] 8.3 Implement download simulation (`trap/ghost/commands/download.py`)
    - `wget <url>`: log `download_attempt` event via `ctx`; print plausible progress output (percentage, speed, file size); create a fake empty file in `ctx.fs` cwd named after the last URL path segment; make NO outbound network request
    - `curl <url>`: same as wget but with curl-style transfer statistics output
    - If the entity later runs `./<downloaded_filename>`, return `Segmentation fault (core dumped)`
    - Parse the first URL argument from args; record the full command string and parsed URL in the event payload
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ] 8.4 Implement exit command (`trap/ghost/commands/exit_.py`)
    - Define sentinel exception `SessionExitRequested`
    - `exit` handler raises `SessionExitRequested`; `shell.py` catches this to cleanly close the session
    - _Requirements: 5.15_

  - [ ]* 8.5 Write unit tests for file, history, download, exit commands (`tests/test_unit_commands.py` — files/download/exit section)
    - Test `cat` success and missing file
    - Test `touch` creates file, `touch` existing file no-op
    - Test `rm` file and `rm -rf` directory; `rm` non-existent error
    - Test `mkdir` success and collision error
    - Test `chmod` success and missing path error
    - Test `history` with 0, 1, and N entries
    - Test `wget`/`curl` creates fake file in cwd, records download_attempt event, returns non-empty output
    - Test exit raises `SessionExitRequested`
    - _Requirements: 5.4, 5.10, 5.11, 5.12, 5.13, 5.14, 5.15, 6.1, 6.2, 6.3, 6.4_

  - [ ]* 8.6 Write property tests for download simulation (Property 19)
    - **Property 19: Download simulation — no real network, fake file created**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.6**
    - Strategy: `st.from_regex(r'https?://[a-z0-9./\-]+\.[a-z]{2,}/[a-z0-9.\-]+')`; verify download_attempt event recorded, output non-empty, no network call made, fake file exists in cwd
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_

- [ ] 9. Command dispatcher (`trap/ghost/dispatcher.py`)
  - [ ] 9.1 Implement `CommandResult` dataclass and `Dispatcher` class
    - Implement `CommandResult` dataclass with `output: str` and `is_error: bool`
    - Implement `Dispatcher.register(name, handler)` to populate the handler registry
    - Implement `Dispatcher._tokenise_chain(raw)`: state-machine parser respecting single- and double-quoted strings; splits on `&&`, `;`, `|`; returns `list[tuple[str, list[str]]]` of `(operator, tokens)`
    - Implement `Dispatcher._dispatch_single(tokens, ctx)`: look up handler by `tokens[0]`; if not found call `llm.respond()`; catch all handler exceptions, log them, return fallback `CommandResult`
    - Implement `Dispatcher.dispatch(raw_input, ctx)`: call `_tokenise_chain`; iterate tokens applying `&&` (stop on error), `;` (always continue), `|` (pass left output to right); concatenate output strings
    - Register all command handlers from `trap/ghost/commands/` at startup
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 7.1_

  - [ ]* 9.2 Write unit tests for dispatcher (`tests/test_unit_dispatcher.py`)
    - Test semicolon chain: all commands execute and outputs concatenate
    - Test `&&` chain: right executes on left success; right skipped on left error
    - Test pipe: left output passed as argument to right
    - Test unknown command falls through to LLM
    - Test exception in one chain token is isolated; remaining tokens still execute
    - Test quoted strings are tokenised correctly (space inside quotes is not a separator)
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 9.3 Write property tests for dispatcher chains and robustness (Properties 1, 2, 15, 16, 17)
    - **Property 1: Ghost Shell robustness — arbitrary input never raises**
    - **Property 2: No-execution invariant — forbidden APIs never invoked**
    - **Property 15: Semicolon chain — all tokens execute**
    - **Property 16: `&&` operator — right executes only on left success**
    - **Property 17: Chain exception isolation**
    - **Validates: Requirements 10.4, 11.1, 10.1, 11.4, 8.5, 8.1, 8.2, 8.4**
    - Strategy for P1: `st.text(max_size=4096)`; call `dispatcher.dispatch()`, assert no exception raised and result is a string
    - Strategy for P2: `st.text(max_size=4096)` with `unittest.mock.patch` on forbidden API names; assert none called
    - Strategy for P15: `st.lists(st.sampled_from(["pwd", "whoami", "hostname"]), min_size=2, max_size=5)`; join with `;`
    - Strategy for P16: pairs of commands, one valid, one producing error
    - Strategy for P17: lists of commands including one that raises
    - _Requirements: 10.1, 10.4, 11.1, 11.4, 8.1, 8.2, 8.4_

- [ ] 10. Attempt tracker (`trap/auth/tracker.py`)
  - [ ] 10.1 Implement `AttemptTracker`
    - Implement `AttemptTracker.__init__(max_attempts_per_ip)` initialising the `OrderedDict[str, deque[datetime]]`; set `_max_per_ip = max_attempts_per_ip` (default 101)
    - Implement `_prune_ip(src_ip)`: remove timestamps older than 1 hour from left of deque; remove key if deque becomes empty
    - Implement `_move_to_end(src_ip)`: call `self._window.move_to_end(src_ip)`
    - Implement `record_attempt(src_ip)`: prune first; if new IP and dict at 10,000, evict first key; if IP's deque at `_max_per_ip`, pop left; append current UTC timestamp; move IP to end
    - Implement `should_accept(src_ip, n)`: prune first; return `len(self._window.get(src_ip, deque())) >= n`
    - _Requirements: 2.7_

  - [ ]* 10.2 Write unit tests for attempt tracker (`tests/test_unit_tracker.py`)
    - Test `should_accept` returns False before N attempts, True at N attempts
    - Test timestamps older than 1 hour are pruned
    - Test per-IP timestamp cap: deque never exceeds `_max_per_ip`
    - Test IP count cap: dict never exceeds 10,000 entries; LRU IP is evicted
    - Test `record_attempt` and `should_accept` called concurrently from the same event loop (asyncio)
    - _Requirements: 2.7_

  - [ ]* 10.3 Write property tests for attempt tracker (Properties 20, 22)
    - **Property 20: Attempt-counter threshold acceptance**
    - **Property 22: AttemptTracker memory is bounded**
    - **Validates: Requirements 2.7**
    - Strategy for P20: `st.ip_addresses()`, `st.integers(min_value=1, max_value=10)`; record N attempts, assert accepted
    - Strategy for P22: `st.lists(st.ip_addresses(), min_size=1, max_size=50_000)` with `max_attempts_per_ip=5`; assert IP count ≤ 10,000 and per-IP deque length ≤ 5
    - _Requirements: 2.7_

- [ ] 11. Default credential file (`trap/credentials_default.txt`)
  - Write approximately 30 `username:password` pairs, one per line
  - Include all combinations required by Req 2.6: usernames `root`, `admin`, `ubuntu`, `pi`, `user`; passwords `123456`, `password`, `admin`, `root`, `12345678`, `qwerty`; plus pairs `root:root`, `admin:admin`, `pi:raspberry`, `ubuntu:ubuntu`, `user:user`
  - _Requirements: 2.6_

  - [ ]* 11.1 Write property test for credential list parse round-trip (Property 6)
    - **Property 6: Credential list parse round-trip**
    - **Validates: Requirements 1.4**
    - Strategy: `st.lists(st.tuples(st.text(min_size=1, max_size=32), st.text(min_size=1, max_size=64)))`; serialise to credential file format, parse back, assert all pairs recovered exactly
    - _Requirements: 1.4_

- [ ] 12. SSH server (`trap/server.py`)
  - [ ] 12.1 Implement `TrapServer` and `start_server()`
    - Implement `start_server(config)`: call `asyncssh.create_server` on `config.trap_port`, passing the loaded/generated Ed25519 host key
    - Implement host key lifecycle: if file at `config.host_key_path` exists, call `asyncssh.read_private_key`; otherwise call `asyncssh.generate_private_key("ssh-ed25519")` and write to path
    - Implement `TrapServer(asyncssh.SSHServer)` overriding `password_auth_requested(username, password)`:
      - Call `tracker.record_attempt(src_ip)` (extract via `self._conn.get_extra_info("peername")`)
      - Check `creds.get(username) == password` (credential dict loaded at startup)
      - If `config.accept_after_attempts` is set, also accept when `tracker.should_accept(src_ip, n)` is True
      - Write a `login_attempt` Event via `EventLogger`; if the write fails, log to process logger and continue (non-fatal per Req 2.5)
      - Return `True` (accept) or `False` (reject)
    - On accept, hand off to `GhostShellSession` (wired in task 13)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.7_

  - [ ]* 12.2 Write property tests for credential auth round-trip (Properties 4, 5)
    - **Property 4: Credential authentication round-trip**
    - **Property 5: Login attempt event completeness**
    - **Validates: Requirements 2.1, 2.2, 2.3**
    - Strategy for P4: `st.lists(st.tuples(st.text(min_size=1, max_size=32), st.text(min_size=1, max_size=64)))`; build cred dict, assert accept for known pairs and reject for absent pairs
    - Strategy for P5: `st.tuples(st.ip_addresses(), st.integers(1024, 65535), st.text(min_size=1), st.text())`; verify all 8 required fields in the logged event
    - _Requirements: 2.1, 2.2, 2.3_

- [ ] 13. Ghost Shell session (`trap/ghost/shell.py`)
  - [ ] 13.1 Implement `run_shell()` coroutine and MOTD
    - Compose the MOTD string: include `records-srv-09`, the decommissioned municipal records purpose, and the lore hint about the missing caretaker (e.g. "Caretaker H. last login: Oct 31 2013")
    - Write `session_start` event via `logger.write()`
    - Send MOTD to `process.stdout`
    - Enter the prompt loop: compute and send the prompt string matching the format `[username@records-srv-09 <display_cwd>]#` (root) or `$` (non-root); substitute `~` for the user's home directory prefix
    - Read a line with `asyncio.wait_for(process.stdin.readline(), timeout=config.idle_timeout_seconds)`
    - If input exceeds `config.max_input_line` characters, send `bash: line too long` and continue (do not write a command event)
    - Call `dispatcher.dispatch(line, ctx)`, append command to `ctx.history`, write `command` and `response` events, send output to `process.stdout`
    - Catch `SessionExitRequested`: write `session_end(reason="exit")`, close channel
    - Catch `asyncio.TimeoutError` (idle): write `session_end(reason="idle_timeout")`, close channel
    - Wrap entire loop in `asyncio.timeout(config.max_session_seconds)`: on `TimeoutError` write `session_end(reason="max_duration")`, close channel
    - Catch SSH disconnect: write `session_end(reason="disconnect")`
    - Outermost broad `try/except Exception`: write `session_end(reason="disconnect")`, log exception, do not crash server
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3, 9.3, 9.4_

  - [ ]* 13.2 Write property tests for oversized input handling (Property 21)
    - **Property 21: Oversized input — discarded, session stays open**
    - **Validates: Requirements 3.5**
    - Strategy: `st.text(min_size=4097, max_size=8192)`; assert `bash: line too long` returned and session coroutine does not exit
    - _Requirements: 3.5_

- [ ] 14. Entry point (`trap/__main__.py`)
  - Implement the module entry point that wires all components together and starts the asyncio event loop
  - Call `load_config()` to get the `Config` object; exit on failure (config handles this)
  - Load the credential file specified by `config.credential_file`; parse into a `dict[str, str]`
  - Load `fs_template.yaml` using `yaml.safe_load` and build the root `FakeNode` template
  - Instantiate `AttemptTracker(max_attempts_per_ip=config.accept_after_attempts or 101)`
  - Instantiate `ScriptedFallback` (or the backend selected by `TRAP_LLM_BACKEND`)
  - Call `asyncio.run(start_server(config, creds, fs_template, tracker, llm))` to start the server
  - Configure Python `logging` (level INFO, structured format including timestamp and session ID where available)
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 7.4_

- [ ] 15. Checkpoint — unit test suite passes
  - Ensure all unit tests pass: `pytest tests/test_unit_*.py -v`
  - Ensure no import errors across the entire `trap/` package
  - Ask the user if questions arise before proceeding to property tests and integration.

- [ ] 16. Property-based test suite (`tests/test_properties.py`)
  - [ ] 16.1 Collect and wire all 22 property test functions into `tests/test_properties.py`
    - Each test function must have a comment header: `# Feature: trap-core, Property N: <title>`
    - Each test must be decorated with `@given(...)` using the Hypothesis strategy from the design
    - Each test must run a minimum of 100 trials (use `@settings(max_examples=100)`)
    - Consolidate any property test stubs written in earlier tasks (3.3, 4.4, 5.3, 6.3, 7.4, 8.6, 9.3, 10.3, 11.1, 12.2, 13.2) into a single canonical file
    - Verify each property matches its design description exactly
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 10.1, 10.4_

- [ ] 17. Integration smoke test (`tests/test_integration.py`)
  - [ ] 17.1 Implement the integration smoke test
    - Spin up a real `asyncssh` server on a random available port using `start_server()` with a test config (in-memory key, temp log dir)
    - Connect a test SSH client using `asyncssh.connect`
    - Verify: MOTD is received and contains `records-srv-09`
    - Verify: `pwd` returns `/root` for a root login
    - Verify: `whoami` returns the authenticated username
    - Verify: the session log file at `<LOG_DIR>/<session_id>.jsonl` exists and contains at least a `session_start` event and one `command` event, each line parsing as valid JSON
    - Verify: the server closes cleanly after the client disconnects
    - _Requirements: 1.1, 2.1, 4.1, 4.3, 9.1, 9.2, 5.1, 5.5_

- [ ] 18. Static analysis gate
  - [ ] 18.1 Run and fix ruff
    - Run `ruff check trap/ tests/` and fix all reported issues
    - Ensure the `ruff` config in `pyproject.toml` targets Python 3.12
    - _Requirements: 10.5_

  - [ ] 18.2 Run and fix bandit
    - Run `bandit -r trap/ -ll` and fix or annotate any high-severity findings
    - Confirm `B603`, `B602`, `B605` (subprocess), `B506` (`yaml.load`) report zero findings
    - _Requirements: 10.1, 10.5_

  - [ ] 18.3 Run and fix mypy
    - Run `mypy --strict trap/` and fix all type errors
    - All dataclasses must have complete type annotations; no `Any` unless explicitly justified
    - _Requirements: 10.5_

- [ ] 19. Final checkpoint — all tests and static analysis pass
  - Run `pytest tests/ -v` (all unit, property, and integration tests)
  - Run `ruff check trap/ tests/`, `bandit -r trap/ -ll`, `mypy --strict trap/`
  - All checks must pass with zero findings before this task is complete.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; core functionality is fully testable without them.
- Every task references the requirements and design sections it satisfies for traceability.
- The dependency order is: scaffold → models → config → filesystem+template → logger → LLM → commands → dispatcher → tracker → credentials → server → shell → entry point → tests → static analysis.
- Property tests (tasks 3.3, 4.4, 5.3, 6.3, 7.4, 8.6, 9.3, 10.3, 11.1, 12.2, 13.2) are consolidated into `tests/test_properties.py` in task 16.1 — individual subtasks create stubs that get wired up there.
- The `bandit` high-severity gate (task 18.2) is a hard merge gate per the security steering rules.
- `yaml.load` is forbidden in `trap/`; use only `yaml.safe_load`.
- No command handler, dispatcher, or shell coroutine may import `subprocess`, `os.system`, `os.popen`, `pty`, `eval`, or `exec`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "3.3", "4.1", "4.2"] },
    { "id": 3, "tasks": ["4.3", "4.4", "5.1", "6.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "6.2", "6.3", "7.1", "7.2", "9.1", "10.1", "11"] },
    { "id": 5, "tasks": ["7.3", "7.4", "8.1", "8.2", "8.3", "8.4", "9.2", "9.3", "10.2", "10.3", "11.1", "12.1"] },
    { "id": 6, "tasks": ["8.5", "8.6", "12.2", "13.1"] },
    { "id": 7, "tasks": ["13.2", "14"] },
    { "id": 8, "tasks": ["16.1", "17.1"] },
    { "id": 9, "tasks": ["18.1", "18.2", "18.3"] }
  ]
}
```
