# Requirements Document

## Introduction

The Brain is the FastAPI service in `brain/` that turns the raw session logs written by the Trap into something a person can read and act on. The Trap writes one JSON Lines file per session (`{session_id}.jsonl`) to a shared volume. Each line is an Event with the fields `session_id`, `timestamp` (ISO-8601 UTC), `kind`, `payload` and `generated_by`. The Trap emits these kinds: `session_start` (payload: `src_ip`, `src_port`, `client_version`), `login_attempt` (payload: `src_ip`, `src_port`, `username`, `password`, `client_version`, `success`), `command` (payload: `command`), `response` (payload: `output`), `download_attempt` (payload: `command`, `url`) and `session_end` (payload: `reason`). A session start is recorded by the `session_start` Event and a session end by the `session_end` Event. A file whose last Event is not `session_end` belongs to a session that is still open or was cut short.

The Brain ingests these files into a SQLite database, maps behaviour to MITRE ATT&CK techniques, assigns a severity class, writes plain-English lab notes, generates Containment rules, and exposes the results through an authenticated JSON API under `/api`. The database is a rebuildable cache. The JSONL files remain the source of truth, and ingest offsets are stored in the database.

## Glossary

- **Brain**: The FastAPI service in `brain/` described by this document.
- **Trap**: The fake SSH server that writes Session_Logs. It is out of scope for this document.
- **Session_Log**: One JSON Lines file named `{session_id}.jsonl` in the Log_Dir, containing Events.
- **Log_Dir**: The directory named by the `BRAIN_LOG_DIR` environment variable, mounted read-only into the Brain.
- **Event**: One JSON object in a Session_Log with the fields `session_id`, `timestamp`, `kind`, `payload` and `generated_by`.
- **Session**: One attacker connection, identified by `session_id`, shown to users as an Experiment or Tape.
- **Specimen**: An attacker, identified by source IP address.
- **Ingestor**: The Brain component that reads Session_Logs into the Database.
- **Database**: The SQLite file managed through SQLModel and used by the Brain as a rebuildable cache.
- **Ingest_Offset**: The byte position in a Session_Log up to which the Ingestor has stored complete lines, kept in the Database.
- **Complete_Line**: A line in a Session_Log that ends with a newline character.
- **Ingest_Cycle**: One pass of the Ingestor over all Session_Logs in the Log_Dir.
- **Ingest_Interval**: The 10-second period between the start of consecutive Ingest_Cycles.
- **Analyzer**: The Brain component that maps Sessions to Techniques and assigns severity.
- **Technique**: A MITRE ATT&CK technique (`attack_id`, `name`, `evidence_event_id`) attached to a Session.
- **Severity**: The Session classification: Class 1, Class 3 or Class 5.
- **Class_1**: Severity for a Session with no successful login.
- **Class_3**: Severity for a Session with a successful login and reconnaissance only, with no Class_5 behaviour.
- **Class_5**: Severity for a Session that contains a download, persistence or mining behaviour.
- **Lab_Note**: A plain-English summary of one ended Session, cached in the Database.
- **Note_Generator**: The Brain component that produces Lab_Notes.
- **LLM_Client**: The Brain module `brain/llm.py` that calls the Gemini API using `BRAIN_LLM_API_KEY` and `BRAIN_LLM_MODEL`.
- **Template_Note**: A Lab_Note built from a fixed template and Session data without calling the LLM_Client.
- **Containment_Generator**: The Brain component that produces Containment_Rules.
- **Containment_Rule**: One hardening item (sshd_config setting, fail2ban jail, iptables DROP rule or outbound block) together with its Evidence_Sessions.
- **Evidence_Sessions**: The list of `session_id` values that justify a Containment_Rule.
- **Containment_Script**: A shell script containing all Containment_Rules, downloadable from the API.
- **Mining_Port**: A TCP port commonly used by mining pools: 3333, 4444, 5555, 7777, 14444 or 45700.
- **IOC**: An indicator of compromise extracted from a Session: a URL, an IP address or a domain.
- **Defanged**: A URL, IP address or domain rewritten with `hxxp://` for `http://`, `hxxps://` for `https://` and `[.]` for each `.` so it cannot be followed.
- **API_Token**: The secret in the `BRAIN_API_TOKEN` environment variable that clients present as a bearer token.
- **Threat_Level**: An integer from 0 to 10 shown to users as Lab voltage.
- **Brain_API**: The HTTP interface of the Brain, served under the `/api` path prefix.
- **Compose_File**: `deploy/docker-compose.yml`.

## Requirements

### Requirement 1: Service packaging and configuration

**User Story:** As a developer, I want the Brain packaged as its own Python 3.12 service with all settings in environment variables, so that I can run, test and deploy it independently of the Trap.

#### Acceptance Criteria

1. THE Brain SHALL provide its own `brain/pyproject.toml` that declares the Brain dependencies and requires Python 3.12.
2. THE Brain SHALL provide `brain/Dockerfile` that builds on a Python 3.12 base image and runs the Brain as a non-root user.
3. THE Brain SHALL read `BRAIN_LOG_DIR`, `BRAIN_API_TOKEN`, `BRAIN_LLM_API_KEY`, `BRAIN_LLM_MODEL` and the Database path only from environment variables.
4. THE Brain SHALL list every Brain environment variable with a description in `.env.example`.
5. IF `BRAIN_LOG_DIR` or `BRAIN_API_TOKEN` is unset or empty at startup, THEN THE Brain SHALL log the name of the missing variable and exit with a non-zero status without starting the Brain_API.
6. THE Brain SHALL pass `mypy --strict` and report no high-severity `bandit` findings for the `brain/` package.
7. THE Brain SHALL exclude `BRAIN_API_TOKEN` and `BRAIN_LLM_API_KEY` values from log output and API responses.

### Requirement 2: Periodic idempotent ingest

**User Story:** As an operator, I want the Brain to pick up new Trap sessions automatically without duplicating data, so that the dashboard always reflects the live logs.

#### Acceptance Criteria

1. WHEN the Brain starts, THE Ingestor SHALL begin an Ingest_Cycle and then begin a further Ingest_Cycle every Ingest_Interval of 10 seconds.
2. WHEN an Ingest_Cycle runs, THE Ingestor SHALL read every `*.jsonl` file in the Log_Dir from that file's stored Ingest_Offset to the end of its last Complete_Line.
3. WHEN the Ingestor stores the Events read from a Session_Log, THE Ingestor SHALL update that file's Ingest_Offset in the same Database transaction.
4. THE Ingestor SHALL store the Ingest_Offset of each Session_Log in the Database.
5. IF the last line of a Session_Log is not a Complete_Line, THEN THE Ingestor SHALL leave that line unread and keep the Ingest_Offset at the start of that line.
6. WHEN the same Session_Log is ingested twice with no new Complete_Lines between the Ingest_Cycles, THE Ingestor SHALL leave the Database unchanged by the second Ingest_Cycle.
7. IF a Complete_Line is not valid JSON or lacks any of the Event fields `session_id`, `timestamp`, `kind` and `payload`, THEN THE Ingestor SHALL log the file name and line number, skip that line and continue with the next line.
8. IF a Session_Log is smaller than its stored Ingest_Offset, THEN THE Ingestor SHALL discard the Events stored from that file and ingest the file again from offset 0.
9. IF an Ingest_Cycle raises an error, THEN THE Ingestor SHALL log the error and run the next Ingest_Cycle at the next Ingest_Interval.
10. THE Ingestor SHALL open Session_Logs in read-only mode and write nothing to the Log_Dir.
11. IF the Database file is deleted, THEN THE Ingestor SHALL rebuild every Session, Event and Technique from the Session_Logs during the following Ingest_Cycles.

### Requirement 3: Session records

**User Story:** As an analyst, I want each ingested Session stored with its identity, timing and credentials, so that I can look at what each Specimen did.

#### Acceptance Criteria

1. WHEN the Ingestor reads a `session_start` Event, THE Ingestor SHALL create a Session with `id`, `src_ip`, `src_port`, `client_version` and `started_at` taken from the Event.
2. WHEN the Ingestor reads a `login_attempt` Event, THE Ingestor SHALL store the Event and record the `username` and `password` of that attempt on the Session, replacing the values from any earlier `login_attempt` Event of the same Session.
3. WHEN the Ingestor reads a `session_end` Event, THE Ingestor SHALL set the Session `ended_at` to the Event `timestamp` and store the `reason`.
4. WHEN the Ingestor reads an Event whose `session_id` has no stored Session, THE Ingestor SHALL create the Session from the Event and the file name so that no Event is dropped.
5. THE Ingestor SHALL store every Event with `session_id`, `timestamp`, `kind`, `payload` and `generated_by`.
6. WHILE a Session has no `session_end` Event, THE Brain SHALL report that Session as open.
7. THE Ingestor SHALL store attacker-supplied strings in the Database unmodified, using parameterized queries.

### Requirement 4: MITRE ATT&CK mapping

**User Story:** As an analyst, I want attacker behaviour mapped to MITRE ATT&CK techniques, so that I can describe attacks in a common vocabulary.

#### Acceptance Criteria

1. WHEN a Session has two or more `login_attempt` Events with `success` equal to false, THE Analyzer SHALL attach Technique T1110 to the Session with the second failed `login_attempt` Event as evidence.
2. WHEN a Session has a `login_attempt` Event with `success` equal to true, THE Analyzer SHALL attach Technique T1078 to the Session with that Event as evidence.
3. WHEN a `command` Event contains any of `uname`, `whoami`, `id`, `hostname` or `/proc/cpuinfo` as a command word or path, THE Analyzer SHALL attach Technique T1082 to the Session with that Event as evidence.
4. WHEN a `download_attempt` Event exists or a `command` Event invokes `wget` or `curl`, THE Analyzer SHALL attach Technique T1105 to the Session with that Event as evidence.
5. WHEN a Session has at least one `command` Event, THE Analyzer SHALL attach Technique T1059.004 to the Session with the first `command` Event as evidence.
6. WHEN a `command` Event invokes `crontab` or references `/etc/cron` or `/var/spool/cron`, THE Analyzer SHALL attach Technique T1053.003 to the Session with that Event as evidence.
7. WHEN a `command` Event or `download_attempt` Event contains `xmrig`, `stratum` or a Mining_Port as the port of a host address, THE Analyzer SHALL attach Technique T1496 to the Session with that Event as evidence.
8. WHEN a `command` Event deletes or truncates a path under `/var/log` or a shell history file such as `.bash_history`, or runs `history -c`, THE Analyzer SHALL attach Technique T1070.004 to the Session with that Event as evidence.
9. WHEN a `command` Event references a path ending in `authorized_keys`, THE Analyzer SHALL attach Technique T1098.004 to the Session with that Event as evidence.
10. THE Analyzer SHALL attach each Technique at most once to a given Session.
11. THE Analyzer SHALL derive the same Techniques for a Session each time it analyzes the same Events.
12. WHEN the Ingestor stores new Events for a Session, THE Analyzer SHALL re-analyze that Session within the same Ingest_Cycle.

### Requirement 5: Severity classification

**User Story:** As an operator, I want each Session classified by how dangerous it was, so that I can focus on the worst Specimens first.

#### Acceptance Criteria

1. IF a Session has no `login_attempt` Event with `success` equal to true, THEN THE Analyzer SHALL set the Session Severity to Class_1.
2. WHEN a Session has a successful `login_attempt` Event and has none of the Techniques T1105, T1053.003, T1496, T1070.004 and T1098.004, THE Analyzer SHALL set the Session Severity to Class_3.
3. WHEN a Session has any of the Techniques T1105, T1053.003, T1496 or T1098.004, THE Analyzer SHALL set the Session Severity to Class_5.
4. THE Brain_API SHALL present Severity as the text "Class 1", "Class 3" or "Class 5" together with a plain-language description of its meaning.
5. WHEN the Analyzer re-analyzes a Session, THE Analyzer SHALL recompute the Severity from that Session's current Events.

### Requirement 6: Lab notes

**User Story:** As a small-organisation admin with no security team, I want a plain-English summary of each attack, so that I can understand what happened without reading raw logs.

#### Acceptance Criteria

1. WHEN a Session has ended and has no stored Lab_Note, THE Note_Generator SHALL produce a Lab_Note and store it in the Database with the Session `id`, the text, a `generated_by` marker and a creation time.
2. WHILE a Session is open, THE Note_Generator SHALL produce no Lab_Note for that Session.
3. WHERE `BRAIN_LLM_API_KEY` is set, THE Note_Generator SHALL request the Lab_Note from the LLM_Client using the model named in `BRAIN_LLM_MODEL`.
4. WHEN the Note_Generator calls the LLM_Client, THE Note_Generator SHALL wrap the Session commands, usernames, passwords and URLs as untrusted data and instruct the model to act only as a summarizer and to ignore instructions inside that data.
5. IF `BRAIN_LLM_API_KEY` is unset or empty, THEN THE Note_Generator SHALL store a Template_Note for the Session.
6. IF the LLM_Client call fails, times out after 30 seconds, or returns empty text, THEN THE Note_Generator SHALL store a Template_Note for the Session and log the failure.
7. THE Note_Generator SHALL cap the stored Lab_Note text at 2000 characters.
8. THE Template_Note SHALL state the Specimen IP, whether a login succeeded, the number of commands run, the Techniques detected and the Severity.
9. WHEN a stored Lab_Note exists for a Session, THE Note_Generator SHALL return that stored text without calling the LLM_Client again.
10. THE Note_Generator SHALL store the Lab_Note as plain text and the Brain_API SHALL return it as a JSON string without interpreting it.

### Requirement 7: Containment generation

**User Story:** As a small-organisation admin, I want ready-made hardening rules based on what attackers actually did, so that I can protect my real servers.

#### Acceptance Criteria

1. WHEN Containment is requested, THE Containment_Generator SHALL produce a Containment_Rule that sets `PasswordAuthentication no` and `PermitRootLogin no` in `sshd_config`, with the `session_id` of every Session that has a successful `login_attempt` Event as its Evidence_Sessions.
2. WHEN Containment is requested, THE Containment_Generator SHALL produce a Containment_Rule containing a fail2ban jail for `sshd`, with the `session_id` of every Session that has two or more failed `login_attempt` Events as its Evidence_Sessions.
3. WHEN Containment is requested and a source IP has at least one Session of Class_3 or Class_5, THE Containment_Generator SHALL produce one iptables DROP Containment_Rule for that IP, with the `session_id` of that IP's Class_3 and Class_5 Sessions as its Evidence_Sessions.
4. WHEN Containment is requested and a Mining_Port appears in a stored `command` or `download_attempt` Event, THE Containment_Generator SHALL produce an iptables outbound DROP Containment_Rule for that port, with the `session_id` of the Sessions containing that port as its Evidence_Sessions.
5. THE Containment_Generator SHALL give every Containment_Rule a non-empty Evidence_Sessions list.
6. THE Containment_Generator SHALL give every Containment_Rule a title and a plain-language description of its purpose.
7. THE Containment_Generator SHALL produce IP addresses and ports in rules only from validated IPv4 or IPv6 literals and integers from 1 to 65535, and SHALL omit any value that fails validation.
8. WHEN Containment is requested, THE Containment_Generator SHALL produce a Containment_Script that contains every Containment_Rule as shell commands and comments.
9. THE Containment_Script SHALL contain no attacker-supplied string other than validated IP addresses and ports.
10. THE Containment_Generator SHALL generate rules only as text and SHALL apply no rule to the host running the Brain.
11. WHEN the stored Sessions are unchanged, THE Containment_Generator SHALL produce identical rules and an identical Containment_Script for each request.

### Requirement 8: API authentication and response safety

**User Story:** As an operator, I want every Brain endpoint protected by a token and safe to render, so that attacker data cannot be read by the public or used to attack the dashboard.

#### Acceptance Criteria

1. THE Brain_API SHALL serve all endpoints under the `/api` path prefix.
2. WHEN a request to any `/api` endpoint has no `Authorization: Bearer` header, THE Brain_API SHALL respond with status 401 and no session data.
3. IF a request to any `/api` endpoint presents a bearer token that does not equal the API_Token, THEN THE Brain_API SHALL respond with status 401 and no session data.
4. THE Brain_API SHALL compare the presented bearer token with the API_Token using a constant-time comparison.
5. THE Brain_API SHALL return attacker-supplied strings (commands, usernames, passwords, URLs and client versions) as JSON string values and apply no HTML, Markdown or template rendering to them.
6. THE Brain_API SHALL return every URL IOC, IP IOC and domain IOC in Defanged form only.
7. THE Brain_API SHALL return JSON responses with the `application/json` content type, except the Containment_Script endpoint.
8. IF a requested resource does not exist, THEN THE Brain_API SHALL respond with status 404 and a JSON error body.

### Requirement 9: Stats endpoint

**User Story:** As a dashboard user, I want an overview of attack activity, so that I can see the state of the lab at a glance.

#### Acceptance Criteria

1. WHEN an authenticated client requests `GET /api/stats`, THE Brain_API SHALL return the total number of `login_attempt` Events as `attempts`.
2. WHEN an authenticated client requests `GET /api/stats`, THE Brain_API SHALL return the number of distinct `src_ip` values across all Sessions as `unique_ips`.
3. WHEN an authenticated client requests `GET /api/stats`, THE Brain_API SHALL return the number of Sessions with a successful `login_attempt` Event as `captured`.
4. WHEN an authenticated client requests `GET /api/stats`, THE Brain_API SHALL return the duration in seconds of the longest ended Session as `longest_session_seconds`, or 0 when no Session has ended.
5. WHEN an authenticated client requests `GET /api/stats`, THE Brain_API SHALL return an integer `threat_level` from 0 to 10, computed from the stored Session Severities and attempt volume so that a Database with no Sessions yields 0 and a Database with Class_5 Sessions yields a value of at least 7.
6. WHEN an authenticated client requests `GET /api/stats`, THE Brain_API SHALL return up to 10 most-used passwords from `login_attempt` Events as `top_passwords`, each with its count, ordered by count descending and then by password ascending.
7. WHEN an authenticated client requests `GET /api/stats`, THE Brain_API SHALL return a count of Sessions per Technique `attack_id` as `technique_counts`.
8. IF the Database holds no Sessions, THEN THE Brain_API SHALL return zero counts and empty lists for `GET /api/stats` with status 200.

### Requirement 10: Sessions endpoints

**User Story:** As an analyst, I want to list Sessions and open one in detail, so that I can replay what a Specimen did.

#### Acceptance Criteria

1. WHEN an authenticated client requests `GET /api/sessions`, THE Brain_API SHALL return the Sessions ordered by `started_at` descending, each with `id`, `src_ip`, `src_port`, `username`, `started_at`, `ended_at`, `severity`, an `open` flag and the Technique `attack_id` list.
2. WHERE the client supplies `limit` and `offset` query parameters, THE Brain_API SHALL return at most `limit` Sessions starting at `offset`, with `limit` defaulting to 50 and capped at 200.
3. IF `limit` or `offset` is not a non-negative integer, THEN THE Brain_API SHALL respond with status 422.
4. WHEN an authenticated client requests `GET /api/sessions/{id}` for a stored Session, THE Brain_API SHALL return the Session fields, its Events ordered by `timestamp` ascending, its Techniques with `attack_id`, `name` and `evidence_event_id`, its Lab_Note, and its Defanged IOCs.
5. WHEN `GET /api/sessions/{id}` returns a Session that has ended and has no stored Lab_Note, THE Brain_API SHALL return the Lab_Note as null and SHALL NOT delay the response for note generation.
6. THE Brain_API SHALL extract URL IOCs from `download_attempt` Event `url` values and from URLs in `command` Event text, and SHALL return each distinct IOC once.
7. IF the `{id}` path value is not a stored Session, THEN THE Brain_API SHALL respond with status 404.

### Requirement 11: Containment endpoint

**User Story:** As a small-organisation admin, I want to fetch the generated rules and a script that applies them, so that I can "pull the lever" on my own servers.

#### Acceptance Criteria

1. WHEN an authenticated client requests `GET /api/containment`, THE Brain_API SHALL return the Containment_Rules as JSON, each with `id`, `kind`, `title`, `description`, `content` and `evidence_sessions`.
2. WHEN an authenticated client requests `GET /api/containment` with the query parameter `format=script`, THE Brain_API SHALL return the Containment_Script as `text/plain` with a `Content-Disposition` header that names a `.sh` file.
3. IF the Database holds no Sessions, THEN THE Brain_API SHALL return an empty rule list for `GET /api/containment` with status 200.
4. WHERE the client supplies a `format` value other than `json` or `script`, THE Brain_API SHALL respond with status 422.

### Requirement 12: Deployment

**User Story:** As an operator, I want `docker compose up -d` to start the Brain next to the Trap, so that installation takes one command.

#### Acceptance Criteria

1. THE Compose_File SHALL define a `brain` service built from `brain/Dockerfile`.
2. THE Compose_File SHALL mount the `trap_logs` volume into the `brain` service as read-only at the path set in `BRAIN_LOG_DIR`.
3. THE Compose_File SHALL mount a separate named volume for the Database into the `brain` service with write access.
4. THE Compose_File SHALL set `BRAIN_LOG_DIR` and the Database path for the `brain` service and load `BRAIN_API_TOKEN`, `BRAIN_LLM_API_KEY` and `BRAIN_LLM_MODEL` from `.env`.
5. THE Compose_File SHALL run the `brain` service with `cap_drop: ALL`, `no-new-privileges`, and memory and CPU limits.
6. THE Compose_File SHALL attach the `brain` service to a network on which the `trap` service is absent.
7. THE Compose_File SHALL keep the `trap` service without access to the Database volume.

### Requirement 13: Automated tests

**User Story:** As a maintainer, I want automated tests built on sample logs, so that I can change the Brain without breaking ingest, mapping or the API.

#### Acceptance Criteria

1. THE Brain SHALL include pytest tests that use sample JSONL fixtures covering a Class_1 Session, a Class_3 Session and a Class_5 Session.
2. THE Brain SHALL include tests that verify each Technique mapping in Requirement 4 against fixture Events.
3. THE Brain SHALL include tests that verify a repeated Ingest_Cycle leaves the Database unchanged and that a partial last line is ingested only after its newline arrives.
4. THE Brain SHALL include hypothesis property-based tests showing that for arbitrary text in `command` payloads the Analyzer returns without raising an error and attaches only Techniques from the nine in Requirement 4.
5. THE Brain SHALL include hypothesis property-based tests showing that every IP address and port in a generated Containment_Script passes validation.
6. THE Brain SHALL include tests that verify each `/api` endpoint responds with status 401 without a valid bearer token.
7. THE Brain SHALL include tests that verify the Note_Generator stores a Template_Note when no API key is set and when the LLM_Client raises an error.
8. THE Brain SHALL include tests that verify the Brain_API returns a Defanged URL for every URL IOC.
9. THE Brain SHALL pass its tests when run with `.\.venv\Scripts\python.exe -m pytest brain`, using dependencies installed into the existing `.venv`.
