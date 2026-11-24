# Design Document

## Feature: dashboard

---

## Overview

The Dashboard is a React + TypeScript + Vite single-page app in `dashboard/` implementing the "Frankenstein Lab Cam" theme (`.kiro/steering/design.md`). It authenticates with a bearer `API_Token` entered at login, polls the Brain API (`.kiro/specs/brain`) on a fixed interval, and renders three signed-in pages — Lab Monitor, Lab Tapes, Containment — plus a Login screen. It is built to static files by a multi-stage Dockerfile and served by Caddy, which reverse-proxies `/api` to the Brain container.

All logic that can be expressed as a pure function (formatting, defanging, masking, parsing defensive API shapes, deriving view data) lives in small, independently testable TypeScript modules under `dashboard/src/lib/`. React components stay thin: they call these pure functions and render the result. This is what makes the property-based tests (vitest + fast-check) possible and keeps `mypy`-equivalent rigor (strict TS) on the Python-adjacent parts of the stack.

### Goals

- Gate all data behind a token the user supplies; never embed a token in the build.
- Poll live data efficiently, pausing when the tab is hidden and recovering cleanly from transient failures.
- Render every attacker-supplied string safely: as escaped text, defanged where it is URL-shaped, and never as a clickable link or injected HTML.
- Parse the Brain's loosely-specified `top_passwords` / `technique_counts` shapes defensively so a format change degrades to an empty state, not a crash.
- Match the Frankenstein Lab Cam design tokens and vocabulary from steering, at every supported viewport width.

### Non-goals (this feature)

- The Brain API itself (contract only; implementation is `brain` spec).
- A public/demo view with masked IPs (explicitly out of scope per Requirement 6.10 / `requirements.md` assumptions).
- Applying Containment rules to any real host.

---

## Architecture

```
dashboard/
  src/
    main.tsx                 – app entry, mounts <App/>
    App.tsx                  – auth gate: renders LoginScreen or <AuthedApp/>
    AuthedApp.tsx             – router (primary nav) for the 3 signed-in pages
    api/
      client.ts               – fetchJson() wrapper: adds Authorization header,
                                 throws typed ApiError on non-2xx, triggers
                                 onUnauthorized() callback on 401
      types.ts                 – TS types mirroring Brain API JSON shapes
      stats.ts, sessions.ts, containment.ts
                                – one typed fetch function per endpoint
    auth/
      AuthContext.tsx          – React context: token, signIn(), signOut()
      tokenStorage.ts           – pure wrapper around sessionStorage (get/set/clear)
    hooks/
      usePoller.ts              – generic polling hook (interval, visibility,
                                  cancel-on-unmount/deps-change)
    lib/                        – PURE functions, no React, no DOM
      duration.ts                – formatDuration(seconds) -> "HH:MM:SS"
      timestamp.ts                – formatTimestamp(iso) -> string | "—"
      offset.ts                   – formatOffset(ms) -> "+S.mmm s"
      severity.ts                  – mapSeverity(value), severityChipVariant(value)
      statParsers.ts                – parseTopPasswords(), parseTechniqueCounts()
      voltage.ts                    – clampVoltage(), voltageDescription(),
                                      techniqueBarWidth()
      sanitize.ts                    – stripControlChars()
      defang.ts                       – defangUrl(), defangText()
      maskIp.ts                        – maskIp()
      truncate.ts                      – truncateAttackerText()
      checklist.ts                      – pure checklist reducer
      containmentSpecimens.ts            – deriveContainedSpecimens()
      replay.ts                           – sortEventsWithOffsets(), decodePayload()
    pages/
      LoginScreen.tsx
      LabMonitor.tsx
      LabTapes.tsx / TapeList.tsx / TapeReplay.tsx
      Containment.tsx
    components/
      Nav.tsx, Header.tsx, SeverityChip.tsx, VoltageMeter.tsx,
      AttackerText.tsx (safe text renderer), StitchedTag.tsx,
      EmptyState.tsx, ConnectionLostBanner.tsx
    styles/
      tokens.css (custom properties from design.md), base.css, components.css
  index.html
  vite.config.ts
  vitest.config.ts
  Dockerfile
  package.json / tsconfig.json
```

### Auth flow

```
App mounts
  -> AuthContext reads tokenStorage.get()
       token present -> render AuthedApp (optimistic; a 401 on first poll
                         demotes to LoginScreen via onUnauthorized)
       token absent  -> render LoginScreen

LoginScreen submit(token)
  -> stats.fetchStats(token)        [validation call, Requirement 1.2]
       200       -> tokenStorage.set(token); AuthContext.signIn(token)
       401       -> show "token rejected"; do not store
       other/err -> show network error; do not store

Any authenticated request (via api/client.fetchJson)
  -> response 401 -> tokenStorage.clear(); AuthContext.signOut()
                     (this fires from ANY page's poller, not just login)
```

`api/client.ts` is the single chokepoint: every `api/*.ts` function calls `fetchJson`, which always sets `Authorization: Bearer <token>` (Requirement 2.6) and always routes a 401 through the same `onUnauthorized` callback (Requirement 1.4), regardless of which endpoint triggered it.

### Polling

`usePoller<T>(fetchFn, { intervalMs: 5000, enabled })` is a single hook used by every page:

```ts
function usePoller<T>(
  fetchFn: () => Promise<T>,
  opts: { intervalMs: number; enabled: boolean },
): { data: T | null; connectionLost: boolean; refetchNow: () => void }
```

Behavior:
- On mount (and whenever `fetchFn`'s identity/deps change, e.g. navigating to a different page or selecting a different Tape id), it fetches immediately, then sets a `setInterval(intervalMs)`.
- On `document.visibilitychange` to hidden, it clears the interval; on becoming visible again, it fetches immediately and restarts the interval (Requirement 2.2, 2.3).
- On unmount or when `opts.enabled` becomes false (navigated away, signed out), it clears the interval (Requirement 2.4).
- On fetch failure (network error or any `ApiError` with status ≥ 500), it keeps the last successful `data` and sets `connectionLost = true`; the next successful fetch clears the flag (Requirement 2.5).
- A 401 is not treated as "connection lost" — `fetchFn` lets it propagate so `api/client.ts`'s `onUnauthorized` handler can sign the user out.

`LabMonitor` and `LabTapes` (list) use `usePoller` against `fetchStats`/`fetchSessions`. `TapeReplay` uses it against `fetchSessionDetail(id)` only while the loaded Tape's `open` is true (Requirement 4.11); once closed, polling for that Tape stops (`enabled: tape.open`).

---

## Components and Interfaces

### `lib/duration.ts`

```ts
export function formatDuration(totalSeconds: number): string
// Converts to "HH:MM:SS". Returns "00:00:00" for NaN, Infinity, -Infinity,
// or any negative number. Non-integer input is floored.
```

### `lib/timestamp.ts`

```ts
export function formatTimestamp(iso: string | null | undefined): string
// Parses ISO 8601 UTC. Returns a locale-independent display string
// (e.g. "2024-03-01 14:02:11 UTC") for a valid date; returns "—" for
// null, undefined, empty string, or a string Date can't parse.
```

### `lib/offset.ts`

```ts
export function formatOffset(ms: number): string
// Returns "+S.mmm s", e.g. formatOffset(1234) -> "+1.234 s".
// Negative input is clamped to 0 before formatting (offsets are always
// relative to the first/earliest event).
```

### `lib/severity.ts`

```ts
export type Severity = "Class_1" | "Class_3" | "Class_5";
export function mapSeverity(value: string): string
// "Class_1" -> "Class 1", "Class_3" -> "Class 3", "Class_5" -> "Class 5";
// any other string is returned unchanged.

export function severityChipVariant(value: string): "solid" | "outline" | "outline-muted" | "unknown"
// Class_5 -> "solid", Class_3 -> "outline", Class_1 -> "outline-muted",
// anything else -> "unknown" (rendered as a neutral/outline-muted chip so
// the UI never throws on an unexpected severity string).
```

### `lib/statParsers.ts` — defensive shape normalization

```ts
export type LabelCount = { label: string; count: number };

export function parseTopPasswords(raw: unknown): LabelCount[]
export function parseTechniqueCounts(raw: unknown): LabelCount[]
```

Both accept the three documented shapes:
- array of `{ password | attack_id, count }` objects
- array of `[label, count]` pairs
- object mapping `label -> count`

Each is tried in turn with a runtime shape check (no `any`-casts assumed valid); numeric `count` is coerced with `Number()` and any `NaN` result drops that entry. Any input that is not an array or plain object, or that yields zero usable entries, returns `[]` — the caller then renders an empty-state panel (Requirement 3.9) while the rest of the page renders normally, because each panel reads only its own slice of `stats` and independently decides to show empty-state.

### `lib/voltage.ts`

```ts
export function clampVoltage(threatLevel: number): number
// Clamps to the integer range [0, 10]; non-finite input maps to 0.

export function voltageDescription(level: number): string
// 0 -> "Dormant", 1-3 -> "Low activity", 4-6 -> "Elevated", 7-10 -> "Critical"
// (exact copy is a product/UI decision; bands are fixed and total).

export function techniqueBarWidth(count: number, maxCount: number): number
// Returns a percentage in [0, 100]. maxCount <= 0 -> 0 for all bars.
// count === maxCount -> 100. Never negative, never > 100.
```

### `lib/sanitize.ts`

```ts
export function stripControlChars(value: string): string
// Removes ANSI CSI/OSC escape sequences (ESC [ ... final-byte, ESC ] ... BEL/ESC\)
// and strips C0/C1 control characters except \n (0x0A) and \t (0x09).
// Printable characters, including non-ASCII/unicode, pass through unchanged.
```

### `lib/defang.ts`

```ts
export function defangUrl(url: string): string
// Replaces a leading "http"/"https" scheme with "hxxp"/"hxxps" and every
// "." in the authority (host[:port]) segment with "[.]". Path/query/
// fragment are left as-is (Requirement 6.5).

export function defangText(text: string): string
// Finds http(s):// URL-shaped substrings anywhere in `text` and replaces
// each with defangUrl(match), leaving all other characters untouched
// (Requirement 6.3, 6.7). Idempotent: defangText(defangText(x)) === defangText(x),
// because the URL regex only matches a live "http(s)://" scheme, which no
// longer exists once defanged to "hxxp(s)://".
```

### `lib/maskIp.ts`

```ts
export function maskIp(value: string): string
// For a syntactically valid IPv4 address "a.b.c.d" (each octet 0-255),
// returns "a.b.c.x". Any other input (IPv6, hostname, garbage, empty
// string) is returned unchanged. Not used on any signed-in page per
// Requirement 6.10 — kept for the Helpers contract and tested directly,
// available for a future public/demo view.
```

### `lib/truncate.ts`

```ts
export function truncateAttackerText(value: string): { text: string; truncated: boolean }
// value.length <= 4096 -> { text: value, truncated: false }.
// value.length > 4096  -> { text: value.slice(0, 4096), truncated: true }.
```

### `components/AttackerText.tsx` — the single safe-rendering path

```tsx
function AttackerText({ value }: { value: string }): JSX.Element
```

Pipeline applied to every attacker-supplied string before render: `stripControlChars` → `truncateAttackerText` → `defangText`. Rendered as `<span className="mono">{text}{truncated && <em> (truncated)</em>}</span>` — a React text child, never `dangerouslySetInnerHTML`. No `<a>` is ever produced from this component. Every place in the app that displays a username, password, command, response payload, URL, Lab_Note, or IOC goes through `AttackerText` (Requirement 6.1, 6.2, 6.4).

### `lib/replay.ts`

```ts
export type TimedEvent<E> = E & { offsetMs: number };
export function sortEventsWithOffsets<E extends { timestamp: string }>(events: E[]): TimedEvent<E>[]
// Sorts by timestamp ascending; offsetMs of each event is its timestamp
// minus the earliest timestamp in the list (0 for the first event).

export function decodePayload(payload: string): { value: unknown; isJson: boolean }
// Attempts JSON.parse(payload). On success, returns the parsed value with
// isJson: true. On failure (any exception), returns the raw string with
// isJson: false. Never throws.
```

### `lib/checklist.ts`

```ts
export type ChecklistState = Record<string, boolean>;
export function toggleItem(state: ChecklistState, id: string): ChecklistState
// Pure, immutable: flips state[id]; unknown ids are added as true.
export function progressCount(state: ChecklistState): number
// Number of entries whose value is true.
```

Held in a single `useState<ChecklistState>` in `Containment.tsx`, initialized fresh on mount with every item `false` — no persistence (Requirement 5.11).

### `lib/containmentSpecimens.ts`

```ts
export type ContainedSpecimen = { ip: string; highestSeverity: Severity; tapeCount: number };
export function deriveContainedSpecimens(
  rules: { evidence_sessions: string[] }[],
  sessions: { id: string; src_ip: string; severity: Severity }[],
): ContainedSpecimen[]
```

Builds the set of distinct `session_id`s across all rules' `evidence_sessions`, looks each one up in `sessions` (ids with no match are dropped — Requirement 5.12), groups the found Tapes by `src_ip`, and for each IP computes the count of its Tapes and the highest severity among them using the total order `Class_5 > Class_3 > Class_1`.

### API client layer (`api/client.ts`, `api/*.ts`)

```ts
export class ApiError extends Error { status: number }

export async function fetchJson<T>(
  path: string, token: string, onUnauthorized: () => void, init?: RequestInit,
): Promise<T>
// Always sends `Authorization: Bearer ${token}`. On status 401, calls
// onUnauthorized() then throws ApiError(401). On any other non-2xx,
// throws ApiError(status). On 2xx, returns response.json() as T.

export function fetchStats(token: string, onUnauthorized: () => void): Promise<StatsResponse>
export function fetchSessions(token, onUnauthorized, { limit, offset }): Promise<SessionListResponse>
export function fetchSessionDetail(token, onUnauthorized, id: string): Promise<SessionDetailResponse>
export function fetchContainment(token, onUnauthorized): Promise<ContainmentRule[]>
export function fetchContainmentScript(token, onUnauthorized): Promise<Blob>
```

All paths are relative (`/api/stats`, `/api/sessions`, …) so no Brain host name is ever embedded in the build (Requirement 10.4).

---

## Data Models

TypeScript interfaces mirroring the Brain API contract:

```ts
interface StatsResponse {
  attempts: number;
  unique_ips: number;
  captured: number;
  longest_session_seconds: number;
  threat_level: number;                 // 0-10
  top_passwords: unknown;               // one of 3 shapes, parsed defensively
  technique_counts: unknown;            // one of 3 shapes, parsed defensively
}

interface SessionListItem {
  id: string;
  src_ip: string;
  src_port: number;
  username: string | null;
  started_at: string;                   // ISO 8601
  ended_at: string | null;
  severity: "Class_1" | "Class_3" | "Class_5";
  open: boolean;
  attack_ids: string[];
}

interface SessionDetailResponse extends SessionListItem {
  password: string | null;
  client_version: string;
  events: Array<{
    id: number; timestamp: string; kind: string; payload: string; generated_by: "scripted" | "llm";
  }>;
  techniques: Array<{ attack_id: string; name: string; evidence_event_id: number }>;
  lab_note: string | null;
  iocs: string[];                       // already defanged by the Brain
}

interface ContainmentRule {
  id: string; kind: string; title: string; description: string;
  content: string; evidence_sessions: string[];
}
```

These interfaces are declared but the Dashboard never trusts them blindly for the two documented loose fields (`top_passwords`, `technique_counts`): those are typed `unknown` and go through the parsers in `lib/statParsers.ts`.

---

## Error Handling

- **401 anywhere** → `api/client.ts`'s shared `onUnauthorized` callback clears `tokenStorage` and flips `AuthContext` to signed-out, which unmounts `AuthedApp` (and therefore cancels all its pollers) and mounts `LoginScreen` with a "session expired" message (Requirement 1.4).
- **Network error / 5xx on a poll** → `usePoller` keeps the last good `data` and renders `ConnectionLostBanner`; no page is ever blanked by a transient failure (Requirement 2.5).
- **404 on `GET /api/sessions/{id}`** → `TapeReplay` shows a "Tape not found" `EmptyState` with a control that navigates back to `TapeList` (Requirement 4.10).
- **Malformed `top_passwords`/`technique_counts`** → the relevant parser returns `[]`; the owning panel renders its own `EmptyState` while sibling panels on `LabMonitor` render normally, because each panel's render path is independent and guarded only by its own data (Requirement 3.9).
- **Clipboard write failure** (`navigator.clipboard.writeText` rejects) → `Containment` shows a "copy failed" message and leaves the `<pre>` content focusable/selectable so the user can copy manually (Requirement 5.5).
- **Download request failure** → `Containment` shows an error message and does not mutate any other page state (Requirement 5.10).
- **Invalid JSON event payload** → `decodePayload` never throws; `TapeReplay` falls back to the raw string rendered through `AttackerText` (Requirement 4.5).
- **Unrecognized severity value** → `severityChipVariant` returns `"unknown"`, rendered as a neutral chip instead of throwing, so a future Brain severity value can't crash the UI.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Voltage meter segment count is the clamped threat level

For any integer or non-finite `threatLevel` input, `clampVoltage(threatLevel)` returns an integer in `[0, 10]`, equal to `threatLevel` when it already lies in `[0, 10]`, equal to `0` or `10` when it lies outside that range on the low or high side respectively, and equal to `0` for any non-finite input (`NaN`, `Infinity`, `-Infinity`).

**Validates: Requirements 3.1**

### Property 2: Technique bar width is proportional and bounded

For any non-negative `count` and any `maxCount`, `techniqueBarWidth(count, maxCount)` returns a value in `[0, 100]`; it returns `100` when `count === maxCount` and `maxCount > 0`; it returns `0` whenever `maxCount <= 0`; and for any two counts `a <= b` with the same positive `maxCount`, `techniqueBarWidth(a, maxCount) <= techniqueBarWidth(b, maxCount)`.

**Validates: Requirements 3.6**

### Property 3: Stat shape parsers are equivalent across all documented input shapes

For any list of `(label, count)` pairs with unique labels and non-negative integer counts, encoding that list as an array of `{password|attack_id, count}` objects, as an array of two-element arrays, or as an object map, and passing each encoding through the matching parser (`parseTopPasswords` / `parseTechniqueCounts`) produces the same set of `{label, count}` entries (order-independent) in every case.

**Validates: Requirements 3.10, 3.11**

### Property 4: Unrecognized stat input always normalizes to an empty list

For any input that is not an array, not a plain object, or whose elements/values do not resolve to a finite `label`/`count` pair, `parseTopPasswords` and `parseTechniqueCounts` return `[]`, and never throw.

**Validates: Requirements 3.9, 9.5**

### Property 5: Every poll outcome sequence leaves the displayed data as the last success

For any sequence of simulated poll outcomes (each either a successful payload or a failure), after processing the sequence, `usePoller`'s `data` equals the payload of the most recent successful outcome in the sequence (or `null` if none has succeeded yet), and `connectionLost` is `true` if and only if the sequence's most recent outcome is a failure.

**Validates: Requirements 2.5**

### Property 6: The Authorization header is present on every request through the API client

For any endpoint function in `api/*.ts` and any non-empty token string, the request issued by `fetchJson` includes the header `Authorization: Bearer <token>` with that exact token.

**Validates: Requirements 2.6**

### Property 7: A 401 response always triggers sign-out, regardless of endpoint

For any endpoint function in `api/*.ts`, if the underlying response status is `401`, `fetchJson` invokes `onUnauthorized` exactly once and throws an `ApiError` with `status === 401`, before returning any parsed body.

**Validates: Requirements 1.4**

### Property 8: Event ordering and offsets are correct for any timestamp arrangement

For any non-empty list of events with arbitrary (including out-of-order and duplicate) ISO 8601 timestamps, `sortEventsWithOffsets` returns the events sorted by timestamp ascending, the first returned event has `offsetMs === 0`, and every event's `offsetMs` equals its timestamp minus the minimum timestamp in the list.

**Validates: Requirements 4.4**

### Property 9: Payload decoding never throws and round-trips valid JSON

For any string, `decodePayload` does not throw. For any value `v` serializable by `JSON.stringify`, `decodePayload(JSON.stringify(v))` returns `{ value: v, isJson: true }` (structurally equal to `v`). For any string that is not valid JSON, `decodePayload` returns `{ value: <that same string>, isJson: false }`.

**Validates: Requirements 4.5**

### Property 10: The Stitched tag appears exactly for LLM-generated events

For any event object, the Replay marks it with the Stitched_Tag if and only if its `generated_by` field equals the literal string `"llm"`.

**Validates: Requirements 4.6**

### Property 11: Checklist progress always equals the number of checked items

For any starting `ChecklistState` and any sequence of `toggleItem` calls, after applying the sequence, `progressCount(state)` equals the number of ids whose current value is `true`, and each `toggleItem` call changes only the targeted id's value (all other entries are unchanged, confirming toggling is idempotent-free and isolated per key).

**Validates: Requirements 5.2**

### Property 12: Contained specimens are derived exactly from evidence that matches a known Tape

For any list of Containment_Rules (each with a list of `evidence_sessions` ids) and any list of Sessions, `deriveContainedSpecimens` returns exactly one entry per distinct `src_ip` that appears on at least one Session referenced (by id) from some rule's `evidence_sessions`; each entry's `tapeCount` equals the number of distinct matched Session ids for that IP; each entry's `highestSeverity` equals the maximum severity (`Class_5 > Class_3 > Class_1`) among that IP's matched Sessions; and any `evidence_sessions` id with no matching Session contributes no entry and does not appear in any `tapeCount`.

**Validates: Requirements 5.7, 5.8, 5.12**

### Property 13: Defanging removes every live URL scheme and is idempotent

For any string, `defangText` (and `defangUrl` on a string that is itself a full URL) produces output containing no substring `"http://"` or `"https://"`. For any string `s`, `defangText(defangText(s)) === defangText(s)`.

**Validates: Requirements 6.3, 6.4, 6.6, 9.7**

### Property 14: Defanging replaces exactly the scheme and host dots, and preserves everything else

For any string composed of a valid `http`/`https` URL embedded in arbitrary surrounding text, `defangText` replaces the URL's scheme with `hxxp`/`hxxps` and every `.` within the URL's host with `[.]`, while every character of the surrounding (non-URL) text — including control characters, unicode, and any `.` outside a URL's host — is identical in input and output.

**Validates: Requirements 6.5, 6.7**

### Property 15: Control-character stripping removes exactly the disallowed bytes

For any string, `stripControlChars` returns a string containing no ANSI escape sequences and no C0/C1 control character other than `\n` and `\t`, and every printable (non-control) character of the input appears in the output in the same relative order.

**Validates: Requirements 6.8**

### Property 16: `maskIp` affects only valid IPv4 input, and always drops the last octet

For any string matching the IPv4 pattern `a.b.c.d` with each octet in `0-255`, `maskIp` returns `"a.b.c.x"`. For any string that is not a syntactically valid IPv4 address (including IPv6 addresses, hostnames, and malformed octets), `maskIp` returns the input unchanged.

**Validates: Requirements 6.9**

### Property 17: Truncation is exact and total

For any string, `truncateAttackerText` returns `truncated: false` and the original string unchanged when its length is at most 4096; it returns `truncated: true` and exactly the first 4096 characters when its length exceeds 4096.

**Validates: Requirements 6.11**

### Property 18: Duration formatting is total and correctly bounded

For any number, `formatDuration` returns a string matching `HH:MM:SS`; it returns `"00:00:00"` for any negative, `NaN`, or non-finite input; and for any non-negative finite input it returns the exact zero-padded hours/minutes/seconds decomposition of the floored value.

**Validates: Requirements 9.1**

### Property 19: Timestamp formatting is total

For any input, `formatTimestamp` does not throw; it returns `"—"` for `null`, `undefined`, the empty string, or any string that does not parse as a valid date; for any string that round-trips through `new Date(...).toISOString()` unchanged, it returns a non-empty display string.

**Validates: Requirements 9.2**

### Property 20: Offset formatting is total and monotonic

For any non-negative number of milliseconds, `formatOffset` returns a string of the form `+S.mmm s` whose numeric value (in seconds) equals the input converted to seconds; for any negative input, it is treated as `0`. For any two non-negative millisecond values `a <= b`, the numeric value parsed back out of `formatOffset(a)` is less than or equal to that of `formatOffset(b)`.

**Validates: Requirements 9.3**

### Property 21: Severity mapping and chip variant are total functions over all strings

For any string, `mapSeverity` returns `"Class 1"`, `"Class 3"`, or `"Class 5"` when the input is exactly `"Class_1"`, `"Class_3"`, or `"Class_5"` respectively, and otherwise returns the input unchanged. For any string, `severityChipVariant` returns `"solid"`, `"outline"`, or `"outline-muted"` for those same three inputs respectively, and `"unknown"` for any other input.

**Validates: Requirements 7.5, 9.4**

---

## Testing Strategy

**Unit tests** (vitest, example-based) cover: the auth flow's four outcomes (200/401/network-error/other-status) on login, sign-out, poller pause/resume on visibility change and interval ticking (`vi.useFakeTimers()`), navigation-cancels-polling, table/list rendering of fixed fixtures (stat cards, experiment log columns, Tape list fields, Replay header fields, IOC list), row-click and technique-tag-click navigation/scroll (`scrollIntoView` mocked), 404 handling in Replay, infinite-scroll pagination triggering with correct `limit`/`offset`, clipboard success/failure, download success/failure, empty-state rendering for zero sessions and zero Containment_Rules, Dockerfile build smoke test (`npm run build` produces `dist/`, grep confirms no secret value embedded), and a fixed-palette contrast-ratio check for the design tokens.

**Property tests** (vitest + fast-check, ≥100 iterations each) implement the properties above. Pure `lib/` functions are tested directly with generated inputs (arbitrary strings, numbers, timestamp lists, severity/stat shapes); `usePoller` and `fetchJson` properties are tested against a fake/mock fetch implementation driven by generated outcome sequences, not real network calls.

Each property test is tagged: **Feature: dashboard, Property {number}: {property title}**.
