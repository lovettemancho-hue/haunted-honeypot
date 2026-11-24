# Implementation Plan: brain

## Overview

Implement the Brain (`brain/`) as a Python 3.12 FastAPI service in small steps. Pure functions come first (reader, ATT&CK mapping, severity, template notes, containment, IOCs, threat level) so they can be property-tested early. The database, ingestor, note generator and API are then wired on top, followed by packaging and deployment.

All commands use the existing `.venv` and run from the repo root with `.\.venv\Scripts\python.exe -m <tool>`:

- Tests: `.\.venv\Scripts\python.exe -m pytest brain`
- Lint: `.\.venv\Scripts\python.exe -m ruff check brain`
- Types: `.\.venv\Scripts\python.exe -m mypy --strict brain`
- Security: `.\.venv\Scripts\python.exe -m bandit -r brain -ll`

Tests live in `brain/tests/`. Property tests use hypothesis and are tagged `Feature: brain, Property {n}: {title}`.

## Tasks

- [ ] 1. Set up the brain package, dependencies and configuration
  - [ ] 1.1 Create `brain/pyproject.toml`, package skeleton and install dependencies into `.venv`
    - Create `brain/pyproject.toml` requiring Python 3.12 with runtime deps (`fastapi`, `uvicorn`, `sqlmodel`, `httpx`, `google-genai` or plain `httpx` for Gemini) and dev deps (`pytest`, `pytest-asyncio`, `hypothesis`, `ruff`, `mypy`, `bandit[toml]`)
    - Add `[tool.mypy] strict = true`, ruff and pytest settings (asyncio auto mode, `testpaths = ["tests"]`) to `brain/pyproject.toml`
    - Create empty packages with `__init__.py`: `brain/`, `brain/ingest/`, `brain/analysis/`, `brain/notes/`, `brain/containment/`, `brain/api/`, `brain/tests/`
    - Install into the existing venv: `.\.venv\Scripts\python.exe -m pip install -e ./brain[dev]` (run from the repo root; if the editable install fails, install the listed packages directly with `.\.venv\Scripts\python.exe -m pip install`)
    - Verify the toolchain runs: `.\.venv\Scripts\python.exe -m pytest brain --collect-only`, `.\.venv\Scripts\python.exe -m ruff --version`, `.\.venv\Scripts\python.exe -m mypy --version`, `.\.venv\Scripts\python.exe -m bandit --version`
    - _Requirements: 1.1, 1.6, 13.9_

  - [ ] 1.2 Implement `brain/config.py` and document env vars in `.env.example`
    - Frozen `Config` dataclass: `log_dir`, `api_token`, `database_path`, `llm_api_key`, `llm_model` (default `gemini-1.5-flash`), `ingest_interval_seconds` = 10
    - `load_config()` reads only environment variables; if `BRAIN_LOG_DIR` or `BRAIN_API_TOKEN` is unset or empty, log the variable name (never values) and `sys.exit(1)`
    - Ensure `api_token` and `llm_api_key` are excluded from `repr` (`field(repr=False)`)
    - Add `BRAIN_LOG_DIR`, `BRAIN_API_TOKEN`, `BRAIN_DATABASE_PATH`, `BRAIN_LLM_API_KEY`, `BRAIN_LLM_MODEL` with descriptions to `.env.example`
    - Add `brain/tests/test_config.py`: missing/empty variables exit non-zero and log only the name; secrets absent from `repr`
    - _Requirements: 1.3, 1.4, 1.5, 1.7_

- [ ] 2. Implement data models and database layer
  - [ ] 2.1 Implement `brain/models.py`
    - SQLModel tables `Session`, `Event`, `Technique`, `LabNote`, `IngestOffset` exactly as in the design (payload stored as JSON text, portable SQL only)
    - `Severity` enum (`CLASS_1`, `CLASS_3`, `CLASS_5`) with label ("Class 1" etc.) and plain-language description helpers
    - _Requirements: 3.5, 5.4_

  - [ ] 2.2 Implement `brain/db.py` and shared test fixtures
    - Engine factory (SQLite, `check_same_thread=False`), `create_db_and_tables()`, short-lived session context manager
    - Create `brain/tests/conftest.py` with temp-DB engine fixture, temp log-dir fixture and an authenticated-client helper
    - Create `brain/tests/fixtures/` with sample JSONL for a Class_1 session, a Class_3 session and a Class_5 session
    - _Requirements: 3.7, 13.1_

- [ ] 3. Implement the pure offset reader
  - [ ] 3.1 Implement `brain/ingest/reader.py`
    - `ParsedLine`, `ReadResult`, and `read_new_events(content, offset, start_line_number=1)`
    - Return only Complete_Lines from `offset`; leave a trailing partial line unread and out of `new_offset`
    - Invalid JSON or missing `session_id`/`timestamp`/`kind`/`payload` yields a `ParsedLine` with `event=None` and `raw_error`, never an exception
    - _Requirements: 2.2, 2.5, 2.7_

  - [ ]* 3.2 Write property tests for offset reads in `brain/tests/test_reader_offsets.py`
    - **Property 1: Offset-based reads return exactly the new complete lines**
    - **Property 2: Re-ingesting with no new complete lines is a no-op**
    - **Validates: Requirements 2.2, 2.5, 2.6, 2.8**

  - [ ]* 3.3 Write property test for invalid lines in `brain/tests/test_reader_invalid.py`
    - **Property 3: Invalid lines are skipped without raising, valid lines are preserved in order**
    - **Validates: Requirements 2.7**

- [ ] 4. Implement ATT&CK mapping and severity
  - [ ] 4.1 Implement `brain/analysis/attack_map.py`
    - `map_techniques(events) -> list[TechniqueHit]` with the nine rules T1110, T1078, T1082, T1105, T1059.004, T1053.003, T1496, T1070.004, T1098.004 per Requirement 4
    - Evidence is the first qualifying Event (second failed login for T1110); each `attack_id` at most once; deterministic
    - Match command words and paths by tokenizing text; no regex that can backtrack catastrophically on arbitrary input
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11_

  - [ ] 4.2 Implement `brain/analysis/severity.py`
    - `classify_severity(has_successful_login, attack_ids)`: no login → Class_1; any of T1105/T1053.003/T1496/T1098.004 → Class_5; otherwise Class_3
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

  - [ ]* 4.3 Write property tests for login techniques in `brain/tests/test_attack_map_login.py`
    - **Property 6: Login-based techniques are attached exactly when their trigger conditions hold**
    - **Validates: Requirements 4.1, 4.2**

  - [ ]* 4.4 Write property tests for content techniques in `brain/tests/test_attack_map_content.py`
    - **Property 7: Content-based techniques are attached exactly when their trigger conditions hold**
    - **Validates: Requirements 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9**

  - [ ]* 4.5 Write property tests for determinism and arbitrary input in `brain/tests/test_attack_map_properties.py`
    - **Property 8: Technique mapping is duplicate-free and deterministic**
    - Include the arbitrary-text `command` test: never raises and returns only the nine allowed attack_ids
    - **Validates: Requirements 4.10, 4.11, 4.12, 13.4**

  - [ ]* 4.6 Write property test and unit examples for severity in `brain/tests/test_severity.py`
    - **Property 9: Severity classification matches the decision table for every input**
    - Add one example per technique rule (Requirement 4) and the Class_1 / Class_3 / Class_5 fixture sessions
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.5, 13.1, 13.2**

- [ ] 5. Implement the ingestor
  - [ ] 5.1 Implement `brain/ingest/ingestor.py` core
    - Session folding: `session_start` creates Session; `login_attempt` sets latest username/password; `session_end` sets `ended_at`/`end_reason`; unknown `session_id` creates a Session from the Event and file name
    - `run_ingest_cycle(config, engine)`: list `*.jsonl` (via `asyncio.to_thread`), open `"rb"`, reset offset to 0 and delete that file's stored Events when file size < offset, insert Events and update `IngestOffset` in one transaction using parameterized SQLModel queries, log `file:line` for skipped lines
    - Re-run `map_techniques` and `classify_severity` for each touched Session and replace its Technique rows atomically in the same cycle
    - Catch and log exceptions per file; `ingest_loop` runs a cycle immediately then every 10 s and never dies
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.7, 2.8, 2.9, 2.10, 2.11, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.12_

  - [ ] 5.2 Implement `brain/notes/template.py` and `brain/llm.py`
    - `build_template_note(summary)` pure, includes IP, login outcome, exact command count, every `attack_id`, severity label, capped at 2000 chars
    - `LLMClient` with `summarize(...)`: provider/model/key from config, system prompt restricting the model to summarizing, attacker strings placed only inside `<untrusted_data>` delimiters, no key in logs
    - _Requirements: 1.7, 6.3, 6.4, 6.7, 6.8_

  - [ ] 5.3 Implement `brain/notes/generator.py`
    - `ensure_note(session_id, config, engine, llm_client)`: return stored note without calling the LLM; no note for open sessions; Template_Note when no API key; LLM call under `asyncio.wait_for(30)`; Template_Note on exception, timeout or empty text; truncate to 2000 chars; never raises
    - _Requirements: 6.1, 6.2, 6.3, 6.5, 6.6, 6.7, 6.9, 6.10_

  - [ ] 5.4 Wire note generation into the ingest cycle
    - After analysis, call `ensure_note` for each Session that has ended and has no stored note; failures are caught per session and never stop ingestion of other sessions
    - _Requirements: 6.1, 6.2, 6.6_

  - [ ]* 5.5 Write property tests for session folding and storage in `brain/tests/test_ingest_properties.py`
    - **Property 4: Session folding is complete and reflects the last writer**
    - **Property 5: Attacker-supplied strings survive storage unmodified**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

  - [ ]* 5.6 Write integration tests in `brain/tests/test_ingest_cycle.py`
    - Repeated cycle leaves the database unchanged; partial last line is ingested only after its newline arrives; truncated file is re-ingested from 0; deleted database is rebuilt from the logs; Class_1/Class_3/Class_5 fixtures produce the expected severity
    - _Requirements: 2.5, 2.6, 2.8, 2.11, 13.1, 13.3_

  - [ ]* 5.7 Write property and unit tests for notes in `brain/tests/test_notes.py`
    - **Property 10: Prompt construction always isolates untrusted data**
    - **Property 11: Note generation falls back to a template on any LLM failure, and succeeds otherwise**
    - **Property 12: Lab notes are never stored longer than 2000 characters**
    - **Property 13: Template notes contain all required facts**
    - **Property 14: A stored note is returned unchanged without a second LLM call**
    - Mock `LLMClient`; example tests for no API key and LLM raising
    - **Validates: Requirements 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 13.7**

- [ ] 6. Checkpoint - Ensure all tests pass
  - Run `.\.venv\Scripts\python.exe -m pytest brain`, ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement containment generation
  - [ ] 7.1 Implement `brain/containment/validate.py`
    - `validate_ip` (via `ipaddress`, IPv4/IPv6 only) and `validate_port` (integer 1 to 65535, rejects bools and non-numeric strings)
    - _Requirements: 7.7_

  - [ ] 7.2 Implement `brain/containment/rules.py`
    - `build_rules(sessions)`: sshd hardening, fail2ban jail, per-IP DROP, per-Mining_Port outbound DROP with exact Evidence_Sessions, non-empty title and description, rule kinds omitted when evidence is empty
    - Mining ports 3333, 4444, 5555, 7777, 14444, 45700; IPs and ports only via validators; deterministic ordering and stable rule ids
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.10, 7.11_

  - [ ] 7.3 Implement `brain/containment/script.py`
    - `render_script(rules)`: static template text plus rule titles/descriptions and validated IP/port literals only; each rule's title appears as a comment or command; never embeds usernames, passwords or commands; text only, applies nothing
    - _Requirements: 7.8, 7.9, 7.10, 7.11_

  - [ ]* 7.4 Write property tests for rules in `brain/tests/test_containment_rules.py`
    - **Property 16: Containment rule evidence is exactly correct per rule kind**
    - **Property 17: Containment generation is deterministic**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.11**

  - [ ]* 7.5 Write property tests for script safety in `brain/tests/test_containment_script.py`
    - **Property 17: Containment generation is deterministic** (script text byte-identical)
    - **Property 18: Only validated IPs and ports ever reach rule content or the script**
    - **Property 19: The script contains a representation of every rule**
    - Include the test that every IP and port in a generated script passes validation
    - **Validates: Requirements 7.7, 7.8, 7.9, 7.11, 13.5**

- [ ] 8. Implement IOCs, threat level and stats helpers
  - [ ] 8.1 Implement `brain/iocs.py`
    - `extract_url_iocs(events)`: distinct URLs in first-seen order from `download_attempt.url` and URL-shaped substrings in command text
    - `defang(value)`: `http://` → `hxxp://`, `https://` → `hxxps://`, every `.` → `[.]`
    - _Requirements: 8.6, 10.6_

  - [ ] 8.2 Implement `brain/analysis/threat.py` and `brain/stats.py`
    - `compute_threat_level(severities, total_attempts)` exactly as in the design (0 when empty, ≥ 7 with any Class_5, clamped to 0..10, monotonic)
    - `compute_stats(session)` using portable SQLModel queries: `attempts`, `unique_ips`, `captured`, `longest_session_seconds`, `threat_level`, `top_passwords` (max 10, count desc then password asc), `technique_counts`; zero counts and empty lists for an empty database
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [ ]* 8.3 Write property tests for IOCs and threat level in `brain/tests/test_iocs_threat.py`
    - **Property 21: Every returned IOC is defanged**
    - **Property 23: Threat level satisfies its boundary and monotonicity guarantees**
    - **Validates: Requirements 8.6, 9.5**

- [ ] 9. Implement the API
  - [ ] 9.1 Implement `brain/api/deps.py` and `brain/schemas.py`
    - `require_token` dependency: 401 when header missing, not `Bearer <token>`, or token mismatch, using `secrets.compare_digest`
    - Pydantic response models for stats, session list item, session detail, technique, containment rule; severity returned as label plus description; IOCs defanged in the schema layer; attacker strings returned as plain JSON strings
    - _Requirements: 5.4, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ] 9.2 Implement routers in `brain/api/stats.py`, `brain/api/sessions.py`, `brain/api/containment.py`
    - `GET /api/stats`
    - `GET /api/sessions` with `limit` (default 50, max 200) and `offset` validated as non-negative integers (422 otherwise), ordered by `started_at` desc, with `open` flag and technique ids
    - `GET /api/sessions/{id}` with events by timestamp asc, techniques, stored note or `null` (never triggers generation), defanged distinct IOCs; 404 JSON for unknown id
    - `GET /api/containment` with `format` of `json` (default) or `script` (`text/plain`, `Content-Disposition: attachment; filename="containment.sh"`); any other value gives 422
    - _Requirements: 8.1, 8.7, 8.8, 9.1, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 11.1, 11.2, 11.3, 11.4_

  - [ ] 9.3 Implement `brain/main.py` app factory and wire everything
    - `create_app()` with `lifespan` that loads config, creates tables and starts `ingest_loop` as an `asyncio.Task` (cancelled on shutdown)
    - Mount all routers under `/api` with `require_token` applied as a router-level dependency; add a `python -m brain` / `uvicorn brain.main:create_app --factory` entry point
    - _Requirements: 1.5, 2.1, 8.1, 8.2_

  - [ ]* 9.4 Write property tests for the API in `brain/tests/test_api_properties.py`
    - **Property 15: Lab notes and all attacker-supplied API fields pass through the API unrendered**
    - **Property 20: Unauthenticated or wrongly authenticated requests never return session data**
    - **Property 22: Stats aggregation matches an independent reference computation**
    - **Property 24: Session listing is correctly ordered, shaped, and paginated**
    - **Property 25: Session detail payload is complete and IOCs are deduplicated**
    - **Property 26: Containment query validation rejects unsupported format values**
    - **Validates: Requirements 6.10, 8.2, 8.3, 8.5, 9.1, 9.2, 9.3, 9.4, 9.6, 9.7, 9.8, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.4**

  - [ ]* 9.5 Write API example tests in `brain/tests/test_api_examples.py`
    - Every `/api` endpoint returns 401 without a valid bearer token; 404 for unknown session id; `format=script` returns `text/plain` with a `.sh` `Content-Disposition`; defanged URL returned for a URL IOC; empty database returns 200 with zero counts and empty lists for stats and containment; JSON content type on JSON endpoints
    - _Requirements: 8.7, 8.8, 9.8, 10.7, 11.2, 11.3, 13.6, 13.8_

- [ ] 10. Package and deploy
  - [ ] 10.1 Create `brain/Dockerfile` and add the `brain` service to `deploy/docker-compose.yml`
    - Dockerfile: Python 3.12 slim base, install from `brain/pyproject.toml`, run as a non-root user, start `uvicorn brain.main:create_app --factory`
    - Compose: build from `brain/Dockerfile`; mount `trap_logs` read-only at `BRAIN_LOG_DIR`; separate writable named volume for the database; set `BRAIN_LOG_DIR` and database path; load `BRAIN_API_TOKEN`, `BRAIN_LLM_API_KEY`, `BRAIN_LLM_MODEL` from `.env`; `cap_drop: ALL`, `no-new-privileges`, memory and CPU limits; attach to a network without the `trap` service; the `trap` service does not mount the database volume
    - _Requirements: 1.2, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [ ]* 10.2 Write static checks in `brain/tests/test_static.py`
    - Compose file shape for the `brain` service (volumes, `cap_drop`, `no-new-privileges`, network separation, trap has no DB volume); `brain/` contains no `subprocess`, `os.system`, `eval`, `exec`; `secrets.compare_digest` is used in `api/deps.py`
    - _Requirements: 1.6, 8.4, 12.2, 12.3, 12.5, 12.6, 12.7_

- [ ] 11. Final checkpoint - Ensure all tests pass
  - Run `.\.venv\Scripts\python.exe -m pytest brain`, `.\.venv\Scripts\python.exe -m ruff check brain`, `.\.venv\Scripts\python.exe -m mypy --strict brain` and `.\.venv\Scripts\python.exe -m bandit -r brain -ll`; ensure all pass with no high-severity findings, ask the user if questions arise.
  - _Requirements: 1.6, 13.9_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Every command uses `.\.venv\Scripts\python.exe -m <tool>` from the repo root; never rely on a globally installed tool.
- Each task references specific requirements for traceability.
- Property tests validate universal correctness properties; unit and integration tests cover specific examples and edge cases.
- Tasks that write the same file are placed in different waves.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "4.1", "4.2", "5.2", "7.1", "8.1", "8.2"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.3", "4.4", "4.5", "4.6", "5.1", "5.3", "7.2", "8.3", "9.1"] },
    { "id": 4, "tasks": ["5.4", "5.5", "5.7", "7.3", "7.4", "9.2"] },
    { "id": 5, "tasks": ["5.6", "7.5", "9.3"] },
    { "id": 6, "tasks": ["9.4", "9.5", "10.1"] },
    { "id": 7, "tasks": ["10.2"] }
  ]
}
```
