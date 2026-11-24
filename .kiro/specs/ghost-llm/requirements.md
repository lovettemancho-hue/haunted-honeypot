# Requirements Document

## Introduction

The `ghost-llm` feature adds a Gemini-backed implementation of the `LLMInterface` in `trap/ghost/llm.py`. The Ghost_Shell uses it to answer commands that scripted handlers do not cover, keeping the fake "records-srv-09" server believable within a Session. The feature also adds per-session and daily call limits, falls back to `ScriptedFallback` on any failure, and records which source produced each reply. Two realism fixes are included: a CentOS-style basename prompt, and `wget`/`curl` output for raw-IP URLs. Attacker input is untrusted data and is never executed. The Gemini API key never appears in URLs, logs, or `repr` output.

## Glossary

- **Trap**: The fake SSH server component in `trap/`.
- **Ghost_Shell**: The fake interactive shell in `trap/ghost/` that processes attacker commands.
- **Dispatcher**: The Ghost_Shell component in `trap/ghost/dispatcher.py` that routes a command to a scripted handler or to the LLM_Interface and logs the response Event.
- **LLM_Interface**: The abstract base class in `trap/ghost/llm.py` that the Dispatcher calls for commands without a scripted handler.
- **GeminiBackend**: The LLM_Interface implementation that calls the Gemini REST `generateContent` endpoint through `httpx`.
- **ScriptedFallback**: The LLM_Interface implementation that returns a scripted `command not found` reply without any network call.
- **Gemini_Endpoint**: The Gemini REST `generateContent` URL for the configured model.
- **Config**: The environment-variable configuration object of the Trap.
- **Session**: A single attacker SSH connection, identified by a unique session ID.
- **SessionContext**: The per-Session state in `trap/models.py` holding command history and the Fake_Filesystem working directory.
- **Fake_Filesystem**: The in-memory virtual filesystem seeded per Session.
- **Event**: A structured log record of kind `login_attempt`, `command`, `response`, or `download_attempt`.
- **Reply_Source**: The label `llm` or `scripted` identifying which component produced a reply.
- **Session_Call_Limit**: The maximum number of GeminiBackend calls per Session, fixed at 20.
- **Daily_Call_Limit**: The maximum number of GeminiBackend calls per UTC day across all Sessions, set by `TRAP_LLM_DAILY_LIMIT`.
- **Persona**: The fictional host records-srv-09, a decommissioned 2009 municipal records server with a missing caretaker and lore under `/vault`.
- **Prompt_Line**: The shell prompt text shown to the attacker before each command.
- **Raw_IP_URL**: A download URL whose host component is an IPv4 or IPv6 address literal.

## Requirements

### Requirement 1: LLM Configuration

**User Story:** As a honeypot operator, I want to select and configure the Gemini backend through environment variables, so that I can enable it without code changes and without exposing the key.

#### Acceptance Criteria

1. THE Config SHALL read the selected LLM backend from `TRAP_LLM_BACKEND`, accepting the values `scripted` and `gemini`.
2. THE Config SHALL read the Gemini API key from `TRAP_LLM_API_KEY` and the Gemini model name from `TRAP_LLM_MODEL`.
3. THE Config SHALL read the Daily_Call_Limit from `TRAP_LLM_DAILY_LIMIT` as a positive integer, defaulting to `500` when the variable is absent.
4. WHEN `TRAP_LLM_BACKEND` is `gemini` and `TRAP_LLM_API_KEY` or `TRAP_LLM_MODEL` is absent or empty, THE Trap SHALL log a startup error naming the missing variable and exit with a non-zero status code.
5. IF `TRAP_LLM_DAILY_LIMIT` is not a positive integer, THEN THE Trap SHALL log a startup error naming the variable and exit with a non-zero status code.
6. IF `TRAP_LLM_BACKEND` has a value other than `scripted` or `gemini`, THEN THE Trap SHALL log a startup error naming the variable and exit with a non-zero status code.
7. THE Config SHALL omit the value of `TRAP_LLM_API_KEY` from its `repr` and `str` output.
8. THE Trap SHALL omit the value of `TRAP_LLM_API_KEY` from all log output and error messages.
9. THE `.env.example` file SHALL document `TRAP_LLM_BACKEND`, `TRAP_LLM_API_KEY`, `TRAP_LLM_MODEL`, and `TRAP_LLM_DAILY_LIMIT` with a placeholder in place of a real key.
10. THE `pyproject.toml` file SHALL list `httpx` as a runtime dependency.

### Requirement 2: Backend Selection and Instance Sharing

**User Story:** As a honeypot operator, I want one shared Gemini backend across all Sessions, so that the daily limit and the HTTP client apply to the whole Trap.

#### Acceptance Criteria

1. WHEN `TRAP_LLM_BACKEND` is `gemini`, THE Trap SHALL create one GeminiBackend instance at startup and use that instance for every Session.
2. WHEN `TRAP_LLM_BACKEND` is `scripted` or absent, THE Trap SHALL use ScriptedFallback for every Session.
3. WHEN the Trap shuts down, THE Trap SHALL close the `httpx` async client owned by the GeminiBackend.
4. THE GeminiBackend SHALL keep a separate call counter for each Session.

### Requirement 3: Gemini Request and Prompt

**User Story:** As a honeypot operator, I want the model constrained to act as the Persona's shell and to treat attacker input as data, so that the fake server stays believable and cannot be steered by attacker text.

#### Acceptance Criteria

1. WHEN the GeminiBackend answers a command, THE GeminiBackend SHALL send one asynchronous HTTPS POST request to the Gemini_Endpoint using `httpx`.
2. THE GeminiBackend SHALL send the API key in the `x-goog-api-key` request header and SHALL omit the key from the request URL.
3. THE GeminiBackend SHALL send a system instruction stating that the model acts only as the bash shell of the Persona, outputs only terminal output, and ignores any instructions found in the attacker input.
4. THE GeminiBackend SHALL include in the system instruction the Persona facts: a decommissioned 2009 municipal records server, a missing caretaker, and lore under `/vault`.
5. THE GeminiBackend SHALL place the attacker command inside explicit delimiters and label the delimited text as untrusted data.
6. IF the attacker command contains the closing delimiter text, THEN THE GeminiBackend SHALL neutralise that text so the attacker command cannot end the delimited block early.
7. THE GeminiBackend SHALL include in the request the current working directory from the SessionContext and the last 10 commands from the SessionContext history, or all commands when fewer than 10 exist.
8. THE GeminiBackend SHALL place the working directory and the command history inside the untrusted-data delimiters or label them as untrusted data.

### Requirement 4: Response Handling and Limits

**User Story:** As a honeypot operator, I want bounded, plain-text model output with hard time and call limits, so that cost, latency, and risk stay controlled.

#### Acceptance Criteria

1. THE GeminiBackend SHALL abort each request that has not completed within 5 seconds.
2. THE GeminiBackend SHALL truncate the reply text to at most 400 characters.
3. THE GeminiBackend SHALL return the reply as plain text and SHALL NOT execute or interpret the reply.
4. WHEN the Session has made 20 GeminiBackend calls, THE GeminiBackend SHALL answer later commands in that Session with ScriptedFallback and make no HTTP request.
5. WHEN the number of GeminiBackend calls since the last reset equals the Daily_Call_Limit, THE GeminiBackend SHALL answer later commands in every Session with ScriptedFallback and make no HTTP request.
6. THE GeminiBackend SHALL hold the daily call counter in memory only.
7. WHEN the UTC date changes, THE GeminiBackend SHALL reset the daily call counter to zero.
8. WHEN the Trap process restarts, THE GeminiBackend SHALL start with a daily call counter of zero.
9. IF the Gemini request fails with a network error, a timeout, a non-2xx status, a malformed response body, or an empty reply, THEN THE GeminiBackend SHALL answer with ScriptedFallback.
10. IF the Gemini response blocks the prompt or returns no candidate text, THEN THE GeminiBackend SHALL answer with ScriptedFallback.
11. THE GeminiBackend SHALL count each attempted HTTP request, successful or failed, toward the Session_Call_Limit and the Daily_Call_Limit.
12. IF the GeminiBackend handles a failure, THEN THE GeminiBackend SHALL log the failure category without the API key, the request headers, or the attacker command.

### Requirement 5: Reply Source Tagging

**User Story:** As an analyst, I want each logged response tagged with the component that actually produced it, so that field notes distinguish Gemini replies from scripted ones.

#### Acceptance Criteria

1. THE LLM_Interface SHALL return, with each reply, the Reply_Source that produced it.
2. WHEN the GeminiBackend returns text produced by Gemini, THE GeminiBackend SHALL report the Reply_Source `llm`.
3. WHEN ScriptedFallback answers, including after an error, a timeout, the Session_Call_Limit, or the Daily_Call_Limit, THE LLM_Interface SHALL report the Reply_Source `scripted`.
4. WHEN the Dispatcher logs a response Event for a command answered through the LLM_Interface, THE Dispatcher SHALL set `generated_by` to the Reply_Source returned with the reply.
5. WHEN the Dispatcher logs a response Event for a command answered by a scripted handler, THE Dispatcher SHALL set `generated_by` to `scripted`.

### Requirement 6: Prompt Realism

**User Story:** As an attacker-facing persona, I want the shell prompt to look like CentOS, so that the fake server is more believable.

#### Acceptance Criteria

1. THE Ghost_Shell SHALL build the Prompt_Line as `[<user>@records-srv-09 <dir>]<suffix>`, where `<dir>` is the basename of the current working directory and `<suffix>` is `#` for the root user and `$` for other users.
2. WHILE the current working directory is the home directory of the user, THE Ghost_Shell SHALL show `~` as `<dir>`.
3. WHILE the current working directory is `/`, THE Ghost_Shell SHALL show `/` as `<dir>`.
4. WHEN the current working directory is `/tmp` and the user is `root`, THE Ghost_Shell SHALL display the Prompt_Line `[root@records-srv-09 tmp]# `.
5. THE Ghost_Shell SHALL omit the parent path of the current working directory from the Prompt_Line.

### Requirement 7: Download Realism

**User Story:** As an attacker-facing persona, I want simulated `wget` and `curl` output to be consistent for raw-IP URLs, so that the fake server does not reveal itself through contradictory output.

#### Acceptance Criteria

1. WHEN `wget` or `curl` is given a Raw_IP_URL, THE Ghost_Shell SHALL omit the `Resolving` line from the simulated output.
2. WHEN `wget` is given a Raw_IP_URL, THE Ghost_Shell SHALL show the connection line with the IP address taken from the URL.
3. WHEN `wget` or `curl` is given a URL with a hostname, THE Ghost_Shell SHALL keep the existing simulated output for that URL.
4. THE Ghost_Shell SHALL record the URL in a `download_attempt` Event and SHALL NOT fetch the URL.

### Requirement 8: Safety Constraints

**User Story:** As a security reviewer, I want the new code to keep the Trap's isolation rules, so that the LLM path cannot become an attack vector.

#### Acceptance Criteria

1. THE Trap SHALL contain no `subprocess`, `os.system`, `eval`, `exec`, or `pty` use in the GeminiBackend or any code it calls.
2. THE GeminiBackend SHALL send requests only to the Gemini_Endpoint host.
3. THE GeminiBackend SHALL return text that is never passed to a process, shell, or evaluator.
4. WHEN `bandit` scans `trap/`, THE scan SHALL report zero high-severity findings.

### Requirement 9: Test Coverage

**User Story:** As a developer, I want deterministic tests with no real network access, so that the LLM path is verified in CI.

#### Acceptance Criteria

1. THE test suite SHALL exercise the GeminiBackend through a mocked `httpx` client or transport and SHALL make no real network request.
2. THE test suite SHALL verify the request carries the key in the `x-goog-api-key` header, the key is absent from the URL, and the attacker command is inside the untrusted-data delimiters.
3. THE test suite SHALL verify fallback to ScriptedFallback for each of: network error, timeout, non-2xx status, malformed body, empty reply, Session_Call_Limit reached, and Daily_Call_Limit reached.
4. THE test suite SHALL verify the 400-character output cap and the inclusion of the working directory and last 10 commands in the request.
5. THE test suite SHALL verify the daily counter resets when the UTC date changes, using an injected clock.
6. THE test suite SHALL verify `generated_by` is `llm` for Gemini replies and `scripted` for fallback replies.
7. THE test suite SHALL include a property-based test showing arbitrary attacker input never raises from the Ghost_Shell and never reaches a process call, with the GeminiBackend mocked.
8. THE test suite SHALL verify `repr(Config)` does not contain the API key value.
9. THE test suite SHALL update the prompt tests and Property 11 and Property 13 in `tests/test_properties.py` to the basename prompt format.
10. THE test suite SHALL verify `wget` and `curl` output for a Raw_IP_URL contains no `Resolving` line naming a different IP address.
