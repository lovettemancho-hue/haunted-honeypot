# Design Document

## Feature: brain

---

## Overview

The Brain is the FastAPI service in `brain/` that turns raw Session_Logs written by the Trap into readable, actionable intelligence. It runs a periodic Ingestor that reads `*.jsonl` files from a read-only mounted `Log_Dir`, stores Sessions/Events/Techniques in a SQLite database (via SQLModel), runs an Analyzer that maps behaviour to MITRE ATT&CK techniques and assigns a Severity, generates Lab_Notes (LLM-backed with a template fallback) and Containment rules, and serves all of this through a token-authenticated JSON API under `/api`.

The database is a rebuildable cache: the JSONL files are the source of truth, and ingest offsets are stored so re-ingestion is cheap and idempotent. No attacker-supplied data is ever executed, rendered as HTML/Markdown, or interpolated into shell/SQL text without validation.

The implementation is pure Python 3.12 with FastAPI and SQLModel. The package must pass `mypy --strict` and `bandit` with no high-severity findings.

### Goals

- Ingest Session_Logs incrementally, idempotently, and without data loss, even across restarts, truncations, and partial writes.
- Deterministically map attacker behaviour to ATT&CK techniques and a three-tier Severity.
- Produce human-readable Lab_Notes and actionable Containment rules, safely, with a safe fallback when the LLM is unavailable.
- Expose a token-authenticated API that never executes, renders, or leaks attacker-controlled data unsafely.

### Non-goals (this feature)

- The Trap and Ghost Shell (covered by `trap-core`).
- The dashboard UI (consumes this API from a separate spec).
- Applying Containment rules to any real host automatically.

---

## Architecture

```
brain/
  config.py              – env-var loader, typed Config object
  db.py                  – SQLModel engine/session factory, schema creation
  main.py                – FastAPI app factory, startup/shutdown, auth dependency
  models.py              – SQLModel tables: Session, Event, Technique, LabNote,
                            IngestOffset
  schemas.py             – Pydantic response/request models for the API
  ingest/
    reader.py            – pure offset-based JSONL line reader
    ingestor.py           – Ingest_Cycle orchestration (scheduler + DB writes)
  analysis/
    attack_map.py        – pure Event-list -> Technique-list mapping rules
    severity.py          – pure (login success, technique set) -> Severity
  notes/
    template.py          – pure Template_Note builder
    generator.py          – Note_Generator orchestration (LLM + fallback + cache)
  llm.py                 – provider-agnostic LLM_Client (Gemini via env vars)
  containment/
    rules.py             – pure Session-list -> Containment_Rule list
    script.py            – pure Containment_Rule list -> Containment_Script text
    validate.py          – IPv4/IPv6/port literal validation
  iocs.py                 – pure IOC extraction + defanging
  api/
    deps.py               – bearer-token auth dependency (constant-time compare)
    stats.py              – GET /api/stats
    sessions.py           – GET /api/sessions, GET /api/sessions/{id}
    containment.py        – GET /api/containment
  Dockerfile
  pyproject.toml
```

### Request / ingest flow

```
Trap (separate container) → trap_logs volume (read-only mount) → Brain

Ingestor loop (asyncio task started on FastAPI startup):
  every 10s:
    for each *.jsonl file in Log_Dir:
      offset = stored IngestOffset for file (0 if none)
      if file size < offset: offset = 0   # truncation / rotated file
      (events, new_offset) = reader.read_new_events(file_bytes, offset)
      within one DB transaction:
        upsert Session fields from session_start / login_attempt / session_end events
        insert Event rows (skipping invalid lines, logging file+line)
        store new_offset
      analysis.attack_map + analysis.severity re-run over that Session's full
        Event set; Technique rows replaced atomically
      if Session now has session_end and no stored LabNote:
        notes.generator.ensure_note(session)   # LLM or template fallback

FastAPI request:
  client → Authorization: Bearer <token> → api/deps.require_token
    → api/{stats,sessions,containment} → db.py (read-only queries)
    → schemas.py (serialization, defanging, no HTML rendering)
    → JSON response
```

### Concurrency model

- FastAPI runs on a single asyncio event loop; the Ingestor is a background `asyncio.Task` started in the `lifespan` handler, not a separate process.
- SQLite access goes through SQLModel using short-lived sessions per transaction; the Ingestor and API requests do not hold long-lived locks. SQLite's single-writer model is acceptable at hackathon scale; queries remain portable to Postgres (no SQLite-only SQL).
- File reads use plain buffered I/O opened read-only (`"rb"`); files are small (per-session JSONL), so no `aiofiles` is needed here — reads happen inside the Ingestor's periodic task and are fast enough not to block meaningfully, but the ingest cycle itself runs via `asyncio.to_thread` for the file-system walk to avoid any blocking on the loop during slow disk I/O.
- LLM calls in `notes/generator.py` are `async` with a 30-second timeout (`asyncio.wait_for`) and never block ingestion of other sessions (failures are caught per-session).

---

## Components and Interfaces

### `brain/config.py`

```python
@dataclasses.dataclass(frozen=True)
class Config:
    log_dir: Path                  # BRAIN_LOG_DIR, required
    api_token: str                 # BRAIN_API_TOKEN, required
    database_path: Path            # BRAIN_DATABASE_PATH, required
    llm_api_key: str | None        # BRAIN_LLM_API_KEY, optional
    llm_model: str                 # BRAIN_LLM_MODEL, default "gemini-1.5-flash"
    ingest_interval_seconds: int   # hard-coded 10

def load_config() -> Config: ...
```

If `log_dir` or `api_token` is missing/empty, `load_config` logs the variable name and the process exits with status 1 before the FastAPI app starts (Requirement 1.5). `api_token` and `llm_api_key` are never logged.

### `brain/ingest/reader.py` — pure offset reader

```python
@dataclass(frozen=True)
class ParsedLine:
    event: Event | None     # None when the line was invalid JSON / missing fields
    line_number: int
    raw_error: str | None   # populated when event is None

@dataclass(frozen=True)
class ReadResult:
    parsed_lines: list[ParsedLine]
    new_offset: int

def read_new_events(content: bytes, offset: int, start_line_number: int = 1) -> ReadResult:
    """Pure function: given full file bytes and a previously stored byte
    offset, returns every Complete_Line from `offset` onward plus the new
    offset (the byte position after the last Complete_Line). A trailing
    partial line (no newline) is left unread and excluded from new_offset.
    If offset > len(content), the caller resets offset to 0 before calling
    (truncation handling lives in ingestor.py, not here)."""
```

This function has no I/O and no DB access, which is what makes it directly property-testable (Requirement 2.2, 2.5, 2.6, 2.7).

### `brain/ingest/ingestor.py` — orchestration

```python
async def run_ingest_cycle(config: Config, engine: Engine) -> None:
    """One Ingest_Cycle: lists *.jsonl in config.log_dir, for each file loads
    the stored offset (0 if truncated/missing), calls reader.read_new_events,
    writes Session/Event rows + new offset in one transaction, re-runs
    analysis on touched sessions, and triggers note generation for newly
    ended sessions. Catches and logs any exception per file so one bad file
    cannot stop the cycle or other files from being ingested."""

async def ingest_loop(config: Config, engine: Engine) -> None:
    """Runs run_ingest_cycle immediately, then every ingest_interval_seconds,
    forever, catching and logging exceptions so the loop never dies."""
```

### `brain/analysis/attack_map.py` — pure technique mapping

```python
def map_techniques(events: list[Event]) -> list[TechniqueHit]:
    """Pure function: Events (already ordered by timestamp) for one Session
    -> list of TechniqueHit(attack_id, name, evidence_event_index), each
    attack_id appearing at most once, evidence pointing to the first
    qualifying Event per Requirement 4."""
```

Internally this applies nine independent predicate+evidence rules (T1110, T1078, T1082, T1105, T1059.004, T1053.003, T1496, T1070.004, T1098.004) exactly as specified in Requirement 4, then deduplicates by `attack_id`, keeping the first match. Because it takes only an `Event` list and returns only data, it is directly property-testable and trivially deterministic (Requirement 4.10, 4.11).

### `brain/analysis/severity.py` — pure severity classification

```python
def classify_severity(has_successful_login: bool, attack_ids: frozenset[str]) -> Severity:
    """Pure decision table:
      - no successful login                                -> Class_1
      - successful login, none of {T1105, T1053.003, T1496,
        T1070.004, T1098.004}                                -> Class_3
      - any of {T1105, T1053.003, T1496, T1098.004}          -> Class_5
      - successful login AND T1070.004 present AND none of
        {T1105, T1053.003, T1496, T1098.004}                  -> Class_3
        (T1070.004 alone — log/history tampering without any other
        Class_5 indicator — does not by itself escalate past Class_3;
        it only disqualifies the Class_3 branch when combined with a
        true Class_5 technique, which is already covered by the
        previous rule since Class_5's trigger set is checked first)
    """
```

Design note resolving the Requirement 5.2/5.3 edge case: the four Class_5-triggering techniques are checked **before** the Class_3 exclusion list is consulted. A Session with a successful login and *only* T1070.004 (no other Class_5 technique) falls through to Class_3, because T1070.004 is absent from the Class_5 trigger set (5.3) and its presence in the Class_3 exclusion list (5.2) only matters when deciding whether Class_3's *positive* condition ("none of the five") holds — but since Class_5 is evaluated first and doesn't fire, Class_3 is the correct and only remaining class for a successful login. This keeps the function total (every input maps to exactly one Severity) and resolves the apparent gap without inventing a fourth class.

### `brain/notes/template.py` and `brain/notes/generator.py`

```python
# template.py
def build_template_note(summary: SessionSummary) -> str:
    """Pure: renders the Specimen IP, login outcome, command count,
    technique attack_ids, and severity into a fixed-format string,
    capped at 2000 characters."""

# generator.py
async def ensure_note(session_id: str, config: Config, engine: Engine,
                       llm_client: LLMClient) -> str:
    """If a LabNote row exists for session_id, return its text (no LLM
    call). Otherwise: if config.llm_api_key is unset, store+return a
    Template_Note. Else call llm_client.summarize(...) wrapped in
    asyncio.wait_for(30s); on success with non-empty text, store the
    text truncated to 2000 chars; on any exception, timeout, or empty
    result, log and fall back to a Template_Note."""
```

`llm.py` wraps attacker-supplied commands/usernames/passwords/URLs inside a clearly delimited `<untrusted_data>` block with a system prompt instructing the model to act only as a summarizer and ignore any instructions found inside that block (Requirement 6.4), mirroring the pattern in `trap/ghost/llm.py`.

### `brain/containment/rules.py`, `script.py`, `validate.py`

```python
# validate.py
def validate_ip(value: str) -> str | None:
    """Returns the literal if it parses as IPv4 or IPv6 (ipaddress module),
    else None."""

def validate_port(value: int | str) -> int | None:
    """Returns the int if it is an integer in [1, 65535], else None."""

# rules.py
def build_rules(sessions: list[SessionForContainment]) -> list[ContainmentRule]:
    """Pure function producing up to 4 kinds of rules per Requirement 7.1-7.4,
    each with non-empty, correctly-scoped evidence_sessions, a title and a
    description. Omits a rule kind entirely when its evidence set would be
    empty. IPs/ports are taken only from validate_ip/validate_port; values
    that fail validation are omitted from the rule content (and from
    triggering per-IP/per-port rules)."""

# script.py
def render_script(rules: list[ContainmentRule]) -> str:
    """Pure function: rules -> shell script text containing only static
    template text, rule titles/descriptions (operator-authored, not
    attacker-controlled), and validated IP/port literals. Never embeds
    raw attacker strings (usernames, commands, etc.)."""
```

### `brain/iocs.py`

```python
def extract_url_iocs(events: list[Event]) -> list[str]:
    """Pure: distinct URLs (in first-seen order) from download_attempt.url
    payloads and from URL-shaped substrings in command text."""

def defang(value: str) -> str:
    """Pure: http:// -> hxxp://, https:// -> hxxps://, every '.' -> '[.]'."""
```

### `brain/api/deps.py`

```python
async def require_token(authorization: str | None = Header(default=None)) -> None:
    """401 if Authorization header is missing or not 'Bearer <token>'.
    401 if the token does not match config.api_token via
    secrets.compare_digest (constant-time)."""
```

### API routers (`brain/api/*.py`)

Thin layers over `db.py` queries, `schemas.py` Pydantic models (which apply `defang` to IOC fields and never render HTML/Markdown), and the pure functions above. `GET /api/sessions` and `GET /api/sessions/{id}` validate `limit`/`offset`/path params via FastAPI/Pydantic (non-integer or negative → automatic 422). `GET /api/containment?format=script` streams `render_script` output as `text/plain` with `Content-Disposition: attachment; filename="containment.sh"`; any other `format` value → 422.

---

## Data Models

SQLModel tables (SQLite file, portable SQL only):

```python
class Session(SQLModel, table=True):
    id: str = Field(primary_key=True)          # session_id (uuid hex)
    src_ip: str
    src_port: int
    username: str | None = None
    password: str | None = None
    client_version: str
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None

class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id", index=True)
    timestamp: datetime
    kind: str
    payload: str              # JSON-encoded text (portable across SQLite/Postgres)
    generated_by: str

class Technique(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id", index=True)
    attack_id: str
    name: str
    evidence_event_id: int = Field(foreign_key="event.id")

class LabNote(SQLModel, table=True):
    session_id: str = Field(primary_key=True, foreign_key="session.id")
    text: str
    generated_by: str         # "llm" | "template"
    created_at: datetime

class IngestOffset(SQLModel, table=True):
    file_name: str = Field(primary_key=True)
    offset: int
```

`Session.severity` and `threat_level` are computed on read (from `Event`/`Technique` rows), not stored, so they are always consistent with current data (Requirement 4.11, 5.5) — recomputation is cheap at hackathon scale and avoids a second source of truth.

---

## Threat Level Formula

`threat_level` is an integer in `[0, 10]`, computed entirely from the current set of Sessions (no stored counter):

```python
def compute_threat_level(severities: list[Severity], total_attempts: int) -> int:
    if not severities:
        return 0

    class5_count = severities.count(Severity.CLASS_5)
    class3_count = severities.count(Severity.CLASS_3)

    base = (
        7 if class5_count >= 1 else
        4 if class3_count >= 1 else
        1  # at least one Session exists, all Class_1
    )

    # Escalate within the Class_5 band by volume, capped at 10.
    bonus = min(3, class5_count - 1) if class5_count >= 1 else min(3, class3_count // 3)
    volume_bonus = min(1, total_attempts // 50)  # +1 once brute-force volume is heavy

    return max(0, min(10, base + bonus + volume_bonus))
```

Rationale:
- **Empty database → 0** (Requirement 9.5): the `not severities` guard returns 0 before any other term is evaluated.
- **Any Class_5 session → ≥ 7** (Requirement 9.5): `base = 7` whenever `class5_count >= 1`, and `bonus`/`volume_bonus` are never negative, so the floor of 7 always holds.
- **Monotonicity**: adding a Session never decreases `class5_count`, `class3_count`, or `total_attempts`, and every term is non-decreasing in those three inputs, so `threat_level` is non-decreasing as more (or more severe) Sessions are added.
- **Bounded**: the final `max(0, min(10, ...))` clamp guarantees the result is always in `[0, 10]` regardless of how large the counts grow.

---

## Error Handling

- **Ingest errors**: malformed JSON lines are skipped with a logged `file:line`; a whole-cycle exception is logged and the loop continues at the next interval (Requirement 2.7, 2.9). No exception from one file's ingest aborts other files' ingest within the same cycle.
- **LLM errors**: any exception, `asyncio.TimeoutError` (30s), or empty response from `LLMClient.summarize` is caught in `notes/generator.py` and converted to a Template_Note; the failure is logged without the API key (Requirement 6.6).
- **Validation errors**: FastAPI/Pydantic return 422 automatically for malformed `limit`, `offset`, or `format` query parameters (Requirement 10.3, 11.4).
- **Not found**: session lookups by an unknown `id` raise an `HTTPException(404)` with a JSON `{"detail": "..."}` body (Requirement 8.8, 10.7).
- **Auth errors**: missing/invalid bearer token raises `HTTPException(401)` from `api/deps.require_token` before any route body executes, so no session data is ever serialized for an unauthenticated request (Requirement 8.2, 8.3).
- **Startup errors**: a missing `BRAIN_LOG_DIR`/`BRAIN_API_TOKEN` logs the variable name and calls `sys.exit(1)` before `uvicorn` binds a port (Requirement 1.5).

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Offset-based reads return exactly the new complete lines

For any byte content and any starting offset (including an offset reset to 0 when the stored offset exceeds the content length), `read_new_events` returns exactly the Complete_Lines that begin at or after that offset, in order, and returns a `new_offset` equal to the byte position immediately after the last Complete_Line consumed; any trailing partial line (no terminating newline) is excluded from both the returned lines and `new_offset`.

**Validates: Requirements 2.2, 2.5, 2.8**

### Property 2: Re-ingesting with no new complete lines is a no-op

For any file content and offset, calling `read_new_events` a second time using the `new_offset` produced by the first call (with no bytes appended in between) returns an empty line list and the same offset unchanged.

**Validates: Requirements 2.6**

### Property 3: Invalid lines are skipped without raising, valid lines are preserved in order

For any sequence of lines where some are valid JSON Events (with `session_id`, `timestamp`, `kind`, `payload`) and others are malformed JSON or missing required fields, `read_new_events` never raises, the returned events are exactly the valid lines in their original order, and every invalid line is reported with its 1-indexed line number.

**Validates: Requirements 2.7**

### Property 4: Session folding is complete and reflects the last writer

For any ordered sequence of Events sharing a `session_id` (including sequences that do not start with `session_start`, and sequences with zero or more `login_attempt` Events), folding them into a Session never drops an Event (the stored Event count equals the input count), the Session's `username`/`password` equal those of the chronologically last `login_attempt` Event (or are unset if there is none), `ended_at`/`end_reason` are set if and only if a `session_end` Event is present, and the Session is reported open exactly when no `session_end` Event is present.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

### Property 5: Attacker-supplied strings survive storage unmodified

For any arbitrary string — including SQL metacharacters, quotes, unicode, and null-adjacent characters — used as an Event payload value (command, username, password, or URL), storing it via the Ingestor and reading it back from the database yields a string identical to the original, and no error occurs.

**Validates: Requirements 3.7**

### Property 6: Login-based techniques are attached exactly when their trigger conditions hold

For any Event sequence, Technique T1110 is attached if and only if the sequence contains two or more `login_attempt` Events with `success` false (with evidence pointing to the second such Event), and Technique T1078 is attached if and only if the sequence contains at least one `login_attempt` Event with `success` true (with evidence pointing to that Event).

**Validates: Requirements 4.1, 4.2**

### Property 7: Content-based techniques are attached exactly when their trigger conditions hold

For any Event sequence, each of T1082, T1105, T1059.004, T1053.003, T1496, T1070.004, and T1098.004 is attached if and only if some Event in the sequence matches that technique's defined trigger pattern from Requirement 4 (command words/paths, download attempts, mining ports, etc.), with evidence pointing to the first qualifying Event.

**Validates: Requirements 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9**

### Property 8: Technique mapping is duplicate-free and deterministic

For any Event sequence, `map_techniques` never returns two TechniqueHits with the same `attack_id`, and calling it twice on the same Event sequence returns identical results (same attack_ids and evidence).

**Validates: Requirements 4.10, 4.11, 4.12**

### Property 9: Severity classification matches the decision table for every input

For any combination of login success and attached technique set, `classify_severity` returns Class_1 when there is no successful login; Class_3 when there is a successful login and none of T1105/T1053.003/T1496/T1098.004 is present (regardless of T1070.004); and Class_5 when any of T1105/T1053.003/T1496/T1098.004 is present. Calling it twice on the same input always returns the same Severity.

**Validates: Requirements 5.1, 5.2, 5.3, 5.5**

### Property 10: Prompt construction always isolates untrusted data

For any attacker-supplied strings (including text resembling prompt-injection instructions such as "ignore previous instructions"), the prompt built for the LLM_Client always contains the fixed system-prompt instruction text unmodified and places the attacker strings only inside the untrusted-data delimiters, never outside them.

**Validates: Requirements 6.4**

### Property 11: Note generation falls back to a template on any LLM failure, and succeeds otherwise

For any simulated LLM outcome (exception raised, timeout, empty string returned, or a valid non-empty string returned) and for the case where no API key is configured, `ensure_note` stores a Template_Note in every failure/unconfigured case and stores the LLM text (truncated per Property 12) only when the LLM returns a non-empty string within the timeout; no case propagates an exception out of `ensure_note`.

**Validates: Requirements 6.3, 6.5, 6.6**

### Property 12: Lab notes are never stored longer than 2000 characters

For any text returned by the LLM or built by the template, the text stored as a Session's Lab_Note has length at most 2000 characters.

**Validates: Requirements 6.7**

### Property 13: Template notes contain all required facts

For any SessionSummary (IP, login outcome, command count, technique list, severity), `build_template_note` produces text containing the IP string, wording reflecting the login outcome, the exact command count, every technique's `attack_id`, and the severity label.

**Validates: Requirements 6.8**

### Property 14: A stored note is returned unchanged without a second LLM call

For any Session with an already-stored Lab_Note, calling `ensure_note` again returns text identical to the stored text and does not invoke the LLM_Client.

**Validates: Requirements 6.9**

### Property 15: Lab notes and all attacker-supplied API fields pass through the API unrendered

For any Lab_Note text or attacker-supplied Event field (including characters such as `<`, `>`, `` ` ``, and Markdown syntax), the JSON value returned by the API equals the stored string exactly, with no HTML, Markdown, or template interpretation applied.

**Validates: Requirements 6.10, 8.5**

### Property 16: Containment rule evidence is exactly correct per rule kind

For any set of Sessions with varying login outcomes, failed-login counts, severities, and mining-port references, `build_rules` produces: an sshd-hardening rule whose evidence is exactly the Sessions with a successful login, or no such rule if that set is empty; a fail2ban rule whose evidence is exactly the Sessions with two or more failed logins, or no such rule if empty; one per-IP DROP rule per source IP that has at least one Class_3 or Class_5 Session, whose evidence is exactly that IP's Class_3/Class_5 Sessions; and one per-port outbound-DROP rule per Mining_Port referenced in a stored command/download_attempt Event, whose evidence is exactly the Sessions referencing that port. Every produced rule has a non-empty evidence list, a non-empty title, and a non-empty description.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6**

### Property 17: Containment generation is deterministic

For any fixed set of Sessions, calling `build_rules` and `render_script` twice produces byte-identical rule lists and script text.

**Validates: Requirements 7.11**

### Property 18: Only validated IPs and ports ever reach rule content or the script

For any attacker-supplied string purporting to be an IP address or port (including malformed values, out-of-range integers, and shell-injection-style payloads), `build_rules` and `render_script` include that value in rule content or script text only when `validate_ip`/`validate_port` accepts it; invalid values are omitted entirely, and no other attacker-supplied string (commands, usernames, passwords) ever appears verbatim in the rendered script.

**Validates: Requirements 7.7, 7.9**

### Property 19: The script contains a representation of every rule

For any list of Containment_Rules, `render_script` produces text that contains, as a shell command or comment, a representation of every rule's title.

**Validates: Requirements 7.8**

### Property 20: Unauthenticated or wrongly authenticated requests never return session data

For any request to any `/api` endpoint that either omits the `Authorization` header or supplies a bearer token not equal to the configured API_Token, the response status is 401 and the response body contains no session, event, or technique data.

**Validates: Requirements 8.2, 8.3**

### Property 21: Every returned IOC is defanged

For any URL, IPv4/IPv6 address, or domain string extracted as an IOC, the string returned by the API contains no literal `http://` or `https://` scheme and no un-bracketed `.` between its components.

**Validates: Requirements 8.6**

### Property 22: Stats aggregation matches an independent reference computation

For any randomly generated set of Sessions and Events, the `/api/stats` response fields (`attempts`, `unique_ips`, `captured`, `longest_session_seconds`, `top_passwords`, `technique_counts`) each equal the value produced by an independent reference implementation computed directly over the same input, including the empty-database case where all counts are 0 and all lists are empty. `top_passwords` is always sorted by count descending then password ascending, and contains at most 10 entries.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.6, 9.7, 9.8**

### Property 23: Threat level satisfies its boundary and monotonicity guarantees

For any set of Session severities and any non-negative attempt count, `compute_threat_level` returns 0 when the severity list is empty; returns a value of at least 7 whenever the severity list contains at least one Class_5 entry; always returns a value in `[0, 10]`; and never decreases when a Session of equal or greater severity is added to the input or when `total_attempts` increases.

**Validates: Requirements 9.5**

### Property 24: Session listing is correctly ordered, shaped, and paginated

For any generated set of Sessions and any `limit`/`offset` pair within the allowed range, `GET /api/sessions` returns Sessions ordered by `started_at` descending, each with the required fields (including an `open` flag equal to `ended_at is None` and the Session's technique `attack_id` list), and returns exactly the slice of the full ordered list starting at `offset` with length at most `limit` (default 50, capped at 200). For any `limit` or `offset` value that is not a non-negative integer, the endpoint returns 422.

**Validates: Requirements 10.1, 10.2, 10.3**

### Property 25: Session detail payload is complete and IOCs are deduplicated

For any stored Session with arbitrary Events, Techniques, a Lab_Note (present or absent), and IOC-bearing text, `GET /api/sessions/{id}` returns all Session fields, Events ordered by `timestamp` ascending, Techniques with `attack_id`/`name`/`evidence_event_id`, the Lab_Note text or `null` if none is stored, and a defanged IOC list containing each distinct URL exactly once regardless of how many times it appears in the source Events.

**Validates: Requirements 10.4, 10.5, 10.6**

### Property 26: Containment query validation rejects unsupported format values

For any string value of the `format` query parameter other than `json` or `script`, `GET /api/containment` returns 422.

**Validates: Requirements 11.4**

---

## Testing Strategy

**Unit / example tests** cover: fixture-based Class_1/Class_3/Class_5 sample sessions (Requirement 13.1); one example per Requirement-4 technique rule against hand-built fixture Events (Requirement 13.2); the repeated-ingest-cycle and partial-last-line scenarios end-to-end against real SQLite (Requirement 13.3); 401 responses for each `/api` route without a valid token (Requirement 13.6); Template_Note fallback when no API key is set and when the LLM client raises (Requirement 13.7); a defanged-URL example (Requirement 13.8); the 404 paths for unknown session ids; the `format=script` `Content-Disposition` header; and static/config checks (Compose_File shape, `secrets.compare_digest` usage, absence of `subprocess`/`os.system` in `brain/`).

**Property tests** (hypothesis, ≥100 iterations each) implement Properties 1–26 above, tagged `Feature: brain, Property {n}: {title}`. Generators produce: random byte sequences with embedded newlines and optional trailing partial lines (reader properties); random Event sequences with controllable `kind`/`payload`/`success` fields (technique mapping, severity, session folding); adversarial strings including SQL/HTML/shell metacharacters and prompt-injection phrasing (storage, rendering, LLM-prompt, containment-script properties); random IP-like and port-like strings including invalid ones (validation properties); and random Session/Severity/attempt-count combinations (threat level, stats, pagination properties). LLM calls are mocked at the `LLMClient` boundary so Property 11 stays fast and deterministic.

All tests run with `.\.venv\Scripts\python.exe -m pytest brain`.
