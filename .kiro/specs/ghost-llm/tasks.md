# Implementation Plan: ghost-llm

## Overview

Python 3.12 implementation, in this order: config and dependencies, the `LLMReply` interface change (with dispatcher and existing-test updates), `GeminiBackend`, server wiring, the prompt basename fix, and the raw-IP download fix. Tests sit under the task they cover. Tools are run as `.\.venv\Scripts\python.exe -m <tool>`. The full checks (ruff, bandit, mypy, pytest) run only at the final checkpoint, not after each file.

## Tasks

- [x] 1. Config and dependencies
  - [x] 1.1 Add LLM settings to config, `.env.example` and `pyproject.toml`
    - In `trap/config.py` add `llm_backend` (default `scripted`), `llm_api_key` (`field(default="", repr=False)`), `llm_model` and `llm_daily_limit` (default 500, parsed with the existing `_positive_int` helper)
    - Raise `ConfigError` naming `TRAP_LLM_BACKEND` for values other than `scripted`/`gemini`
    - Raise `ConfigError` naming the specific missing variable when the backend is `gemini` and the key or model is empty
    - Never interpolate the key value into any error message
    - Document `TRAP_LLM_BACKEND`, `TRAP_LLM_API_KEY` (placeholder), `TRAP_LLM_MODEL` and `TRAP_LLM_DAILY_LIMIT` in `.env.example`
    - Add `httpx` to runtime dependencies in `pyproject.toml`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10_

  - [ ]* 1.2 Write unit tests for LLM config validation
    - In `tests/test_unit_config.py`, one example each: missing key, missing model, non-integer daily limit, unknown backend, default limit of 500
    - Assert exit status 1 and that the variable name appears in stderr
    - Assert `repr(config)` omits the key value
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 9.8_

  - [ ]* 1.3 Write property test for daily limit parsing
    - In `tests/test_properties_llm_config.py`
    - **Property 1: Daily limit parses or rejects consistently**
    - **Validates: Requirements 1.3, 1.5**

  - [ ]* 1.4 Write property test for key and model requirement
    - In `tests/test_properties_llm_config.py`
    - **Property 2: Gemini backend requires key and model**
    - **Validates: Requirements 1.4**

  - [ ]* 1.5 Write property test for unknown backend rejection
    - In `tests/test_properties_llm_config.py`
    - **Property 3: Unknown backend value is rejected**
    - **Validates: Requirements 1.6**

  - [ ]* 1.6 Write property test for key absent from Config repr
    - In `tests/test_properties_llm_config.py`
    - **Property 4: API key never appears in Config's textual representation**
    - **Validates: Requirements 1.7**

- [x] 2. LLMReply interface change, dispatcher and existing tests
  - [x] 2.1 Add `LLMReply` and change the `LLMInterface` contract
    - In `trap/ghost/llm.py` add `ReplySource`, the frozen `LLMReply(text, source)` dataclass, and change `LLMInterface.respond` to return `LLMReply`
    - Update `ScriptedFallback.respond` to return `LLMReply(..., "scripted")`
    - _Requirements: 5.1, 5.3_

  - [x] 2.2 Update the dispatcher to use `LLMReply`
    - In `trap/ghost/dispatcher.py` `_dispatch_single`, read `reply.text` (capped at `MAX_LLM_OUTPUT_CHARS`) and set `generated_by=reply.source`
    - Keep the existing exception fallback unchanged
    - Confirm scripted handler results keep `generated_by="scripted"`
    - _Requirements: 5.4, 5.5_

  - [x] 2.3 Update existing tests to the `LLMReply` contract
    - `tests/test_unit_llm.py`: `ScriptedFallback` assertions and stubs return or compare `LLMReply`
    - `tests/test_unit_dispatcher.py`: `RecordingLLM.respond` returns `LLMReply(reply, "llm")`, and assertions compare against `reply.text`
    - `tests/test_properties.py`: update the scripted-fallback property and the `_Raising` stub in the LLM-exception property to use `LLMReply`
    - _Requirements: 5.1, 5.3, 9.6_

  - [ ]* 2.4 Write property test for reply source to `generated_by`
    - In `tests/test_properties_llm_dispatch.py`, with a stub `LLMInterface` returning an arbitrary source
    - **Property 16: Reply source determines generated_by end to end**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [ ]* 2.5 Write property test for scripted handler tagging
    - In `tests/test_properties_llm_dispatch.py`
    - **Property 17: Scripted handler responses are always tagged scripted**
    - **Validates: Requirements 5.5**

- [x] 3. GeminiBackend
  - [x] 3.1 Implement `GeminiBackend` and prompt building in `trap/ghost/llm.py`
    - Constants: `SESSION_CALL_LIMIT=20`, `REQUEST_TIMEOUT_SECONDS=5`, `MAX_REPLY_CHARS=400`, `GEMINI_ENDPOINT_TEMPLATE`, `DELIMITER_START`, `DELIMITER_END`, `SYSTEM_INSTRUCTION` (with the Persona facts)
    - `_neutralise`, `_build_request_body` (cwd and last 10 history entries inside the untrusted block) and `_extract_text` (raises on blocked prompt or no candidate text)
    - Constructor takes keyword-only `client` and `clock` for injection
    - `respond`: roll the UTC day, check the session and daily limits (fallback with no HTTP call), increment both counters before the POST, send the key only in the `x-goog-api-key` header, and fall back on `httpx.HTTPError`, `ValueError`, `KeyError`, `IndexError` or empty text
    - Log only `type(exc).__name__`, never the key, headers or command
    - Add `aclose()` and `end_session(session_id)`
    - _Requirements: 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 5.2, 5.3, 8.1, 8.2, 8.3_

  - [ ]* 3.2 Write unit tests for `GeminiBackend`
    - In `tests/test_unit_gemini.py`, using `httpx.AsyncClient(transport=httpx.MockTransport(handler))` and an injected clock, with no real network
    - Cases: key in header and absent from URL, command inside the delimiters, system instruction contains the Persona facts, one success returns `source="llm"`
    - Fallback cases: network error, timeout, non-2xx, malformed body, empty reply, blocked prompt, session limit reached, daily limit reached
    - Also cover the 400-character cap, cwd and last 10 commands in the request, and the daily reset on UTC date change
    - Also cover `generated_by` `llm` vs `scripted` through the dispatcher, and the timeout value passed to the client
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 3.3 Write property test for per-session counter isolation
    - In `tests/test_properties_llm_limits.py`
    - **Property 5: Per-session call counters are isolated**
    - **Validates: Requirements 2.4**

  - [ ]* 3.4 Write property test for key only in header
    - In `tests/test_properties_llm_request.py`
    - **Property 6: API key travels only in the request header**
    - **Validates: Requirements 3.1, 3.2**

  - [ ]* 3.5 Write property test for delimiter neutralisation
    - In `tests/test_properties_llm_request.py`
    - **Property 7: Delimiter neutralisation prevents early block closure**
    - **Validates: Requirements 3.5, 3.6**

  - [ ]* 3.6 Write property test for bounded request context
    - In `tests/test_properties_llm_request.py`
    - **Property 8: Request carries bounded, correct context**
    - **Validates: Requirements 3.7, 3.8**

  - [ ]* 3.7 Write property test for reply cap
    - In `tests/test_properties_llm_reply.py`
    - **Property 9: Reply text is always capped and never executed**
    - **Validates: Requirements 4.2, 4.3, 8.1, 8.3**

  - [ ]* 3.8 Write property test for the session limit
    - In `tests/test_properties_llm_limits.py`
    - **Property 10: Session limit forces scripted fallback with no HTTP call**
    - **Validates: Requirements 4.4**

  - [ ]* 3.9 Write property test for the daily limit
    - In `tests/test_properties_llm_limits.py`
    - **Property 11: Daily limit forces scripted fallback across all sessions with no HTTP call**
    - **Validates: Requirements 4.5, 4.6**

  - [ ]* 3.10 Write property test for UTC day rollover
    - In `tests/test_properties_llm_limits.py`, with an injected clock
    - **Property 12: UTC day rollover resets the daily counter exactly once**
    - **Validates: Requirements 4.7, 4.8**

  - [ ]* 3.11 Write property test for failure fallback
    - In `tests/test_properties_llm_reply.py`
    - **Property 13: Any Gemini failure mode falls back to ScriptedFallback with the same text format**
    - **Validates: Requirements 4.9, 4.10, 5.3**

  - [ ]* 3.12 Write property test for call counting
    - In `tests/test_properties_llm_limits.py`
    - **Property 14: Every attempted call counts toward both limits regardless of outcome**
    - **Validates: Requirements 4.11**

  - [ ]* 3.13 Write property test for failure log content
    - In `tests/test_properties_llm_reply.py`, using `caplog`
    - **Property 15: Failure logs never contain sensitive data**
    - **Validates: Requirements 4.12, 1.8**

- [x] 4. Server wiring
  - [x] 4.1 Share one LLM backend across sessions in `trap/server.py`
    - Add `build_llm_backend(config)` returning one `GeminiBackend` or `ScriptedFallback`
    - Store it in `_Shared.llm` and pass it to `build_default_dispatcher` for every session
    - Make the shared backend reachable from `start_server`, choosing the smallest diff that keeps existing call sites working, and `await aclose()` on a `GeminiBackend` in the `finally` block
    - Call `end_session(session_id)` in the `handle_process` `finally` block for a `GeminiBackend`
    - Update existing callers and tests of `create_trap_server` if the return shape changes
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 4.2 Write unit tests for backend selection and shutdown
    - In `tests/test_unit_server_llm.py`
    - `gemini` yields one shared `GeminiBackend` for multiple sessions, `scripted` or absent yields `ScriptedFallback`
    - `aclose` is awaited once on shutdown, and `end_session` is called when a session ends
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 4.3 Write property test for arbitrary input with Gemini mocked
    - In `tests/test_properties_llm_dispatch.py`, driving the full Ghost Shell with a `MockTransport` returning arbitrary or malformed responses
    - Patch `subprocess`, `os.system`, `eval` and `exec` to fail if called
    - **Property 21: Ghost Shell never crashes or reaches a process call under arbitrary input with Gemini mocked**
    - **Validates: Requirements 9.7, 8.1**

- [x] 5. Prompt basename fix
  - [x] 5.1 Change `build_prompt` to show the cwd basename
    - In `trap/ghost/shell.py` show `~` for the home directory, `/` for root, otherwise only the last path component
    - Use `#` for root and `$` for other users
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 5.2 Update prompt tests and the prompt property in `tests/test_properties.py`
    - Update the existing prompt unit tests to the basename format, including the `/tmp` as root case `[root@records-srv-09 tmp]# `
    - Update `_expected_prompt` and the prompt property (Property 11 of trap-core) to compute the basename
    - _Requirements: 6.4, 9.9_

  - [ ]* 5.3 Write property test for basename prompt
    - In `tests/test_properties_llm_realism.py`
    - **Property 18: Prompt shows only the basename of the working directory**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.5**

- [x] 6. Download raw-IP fix
  - [x] 6.1 Fix `wget` output for raw-IP URLs in `trap/ghost/commands/download.py`
    - Add `_is_raw_ip` using `ipaddress.ip_address`
    - For a raw IP, omit the `Resolving` line and print `Connecting to <ip>:80... connected.` with the IP from the URL
    - Keep hostname output unchanged, keep `curl` output free of a `Resolving` line, and keep recording `download_attempt` without fetching
    - Handle bracketed IPv6 hosts
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 6.2 Write unit tests for download output
    - In `tests/test_unit_download.py`: IPv4 `wget`, IPv6 `wget`, hostname `wget` unchanged, raw-IP `curl`
    - Assert no `Resolving` line for raw IPs and no mismatched IP
    - _Requirements: 7.1, 7.2, 7.3, 9.10_

  - [ ]* 6.3 Write property test for raw-IP URLs
    - In `tests/test_properties_llm_realism.py`
    - **Property 19: Raw-IP download URLs never show a resolving line or a mismatched IP**
    - **Validates: Requirements 7.1, 7.2**

  - [ ]* 6.4 Write property test for hostname URLs
    - In `tests/test_properties_llm_realism.py`
    - **Property 20: Hostname download URLs are unaffected by the raw-IP fix**
    - **Validates: Requirements 7.3**

- [x] 7. Final checkpoint - Ensure all checks pass
  - Run `.\.venv\Scripts\python.exe -m ruff check .`
  - Run `.\.venv\Scripts\python.exe -m bandit -r trap -ll` and confirm zero high-severity findings
  - Run `.\.venv\Scripts\python.exe -m mypy --strict trap`
  - Run `.\.venv\Scripts\python.exe -m pytest`
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 8.4_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Full checks run only at the final checkpoint
- Property tests validate universal correctness properties, unit tests validate specific examples
- New property tests go in separate files per group so tasks in the same wave never write the same file

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "5.1", "6.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.2", "3.1", "5.2", "6.2"] },
    { "id": 2, "tasks": ["1.4", "2.3", "2.4", "3.2", "3.3", "3.4", "3.7", "4.1", "5.3"] },
    { "id": 3, "tasks": ["1.5", "2.5", "3.5", "3.8", "3.11", "4.2", "6.3"] },
    { "id": 4, "tasks": ["1.6", "3.6", "3.9", "3.13", "4.3", "6.4"] },
    { "id": 5, "tasks": ["3.10"] },
    { "id": 6, "tasks": ["3.12"] }
  ]
}
```
