# Design Document

## Feature: tape-navigation

## Overview

This feature makes Lab Tapes usable at thousands of Tapes. The Brain gains server-side filtering, sorting, facet counts and review marks. The Dashboard gains a two-pane layout where the replay stays in view, a Filter Bar whose state lives in the URL, date-grouped rows with repeat-attacker and review markers, a Previous/Next review flow with automatic review marking, keyboard shortcuts, and Lab Monitor shortcuts into filtered Tapes.

Design rule for the whole feature: **additive only**. With no new query parameters the Brain returns exactly what it returns today, existing hash routes keep working, and new response fields are additions.

### Goals
- Replay never scrolls away while browsing the list (Requirement 1).
- Filtering is correct and fast on the server, so results are complete even when only one page is loaded (Requirements 2, 3).
- Review progress survives reloads, devices and a rebuild of the session Database (Requirement 4).
- Every view is a URL (Requirement 6).

### Non-goals
- Cross-session brute-force detection in ATT&CK mapping (a separate future change). The Repeat_Count badge makes the pattern visible without changing analysis.
- Per-user accounts. There is one operator token, so Review_Marks are shared by everyone who holds it.
- Changing Lab Note text, severity rules, Containment rules or the Trap.

---

## Architecture

```
Brain (Python, brain/)
  api/sessions.py        GET /api/sessions  (+ filters, sort, X-Total-Count, reviewed, repeat_count)
                         GET /api/sessions/facets        (registered BEFORE /api/sessions/{session_id})
                         PUT /api/sessions/{id}/review
                         POST /api/sessions/review
  api/tape_query.py      NEW pure-ish query layer: TapeQuery model, candidate selection, severity
                         computation, filtering, sorting, pagination (unit + property tested)
  reviews.py             NEW Review_Store: separate SQLite file, ReviewMark table, get/set helpers
  config.py              + review_db_path (BRAIN_REVIEW_DB_PATH, default: <database dir>/reviews.db)
  schemas.py             + SessionListItem.reviewed, .repeat_count; FacetsOut; ReviewIn/ReviewOut;
                           BulkReviewIn/BulkReviewOut

Dashboard (TypeScript, dashboard/src/)
  lib/tapeFilter.ts      NEW pure: TapeFilter type, DEFAULT_FILTER, parseFilter(query), serializeFilter(f),
                           toApiParams(f, now), activeFilterCount(f)
  lib/dateGroups.ts      NEW pure: groupByUtcDay(items, now) -> [{label, items}]
  lib/neighbours.ts      NEW pure: neighbours(ids, selectedId) -> {newer, older}
  routes.ts              parseHash ignores "?..." when choosing the page; exposes the raw query
  api/sessions.ts        fetchSessions(..., filter) returns {items, total}; fetchFacets(); setReviewed();
                           setReviewedBulk()
  api/adapter.ts         normalise new optional fields (reviewed default false, repeat_count default 1)
  pages/LabTapes.tsx     owns TapeFilter state from the hash; two-pane layout; keyboard shortcuts
  pages/FilterBar.tsx    NEW Filter Bar component
  pages/TapeList.tsx     filtered paging, date groups, row markers, scroll-into-view
  pages/TapeReplay.tsx   Newer/Older, review toggle + auto-review timer, "All tapes from this IP"
  pages/LabMonitor.tsx   stat cards and technique bars become links
  styles/lab-tapes.css   pane layout, sticky Filter Bar, row markers, chips
```

---

## Brain design

### Query parameters (`GET /api/sessions`)

| Param | Type | Validation | Meaning |
|---|---|---|---|
| `limit`, `offset` | int | unchanged | unchanged |
| `q` | str | 1..100 chars | substring of `src_ip` or `username`, case-insensitive |
| `severity` | list[int] | each in {1,3,5} | severity class in set |
| `technique` | list[str] | each `^T\d{4}(\.\d{3})?$` | has any of these techniques |
| `ip` | str | ≤45 chars | exact `src_ip` |
| `captured` | bool | | Break_In or not |
| `reviewed` | bool | | has Review_Mark or not |
| `since`, `until` | datetime | ISO-8601 | `since <= started_at < until` |
| `sort` | enum | newest/oldest/severity | ordering |

Validation uses FastAPI `Query` constraints (`pattern=`, `max_length=`, `Literal[...]`), so invalid values return 422 automatically.

### Query layer (`api/tape_query.py`)

1. **SQL stage** (cheap, indexed columns): build a `select(SessionRow)` with bound conditions for `q` (`func.lower(col).like(:p, escape="\\")` with `%`, `_`, `\` escaped), `ip`, `since`, `until`, and for `technique` an `EXISTS` subquery on `Technique`.
2. **Fast path:** if none of `severity`, `captured`, `reviewed` is set and `sort` is `newest` or `oldest`, apply ORDER BY + OFFSET/LIMIT in SQL and run `COUNT(*)` for the total. With no new params at all, this is the original query, which is what keeps Requirement 2.1 true.
3. **Slow path** (severity/captured/reviewed filters, or `sort=severity`): fetch candidate rows' `id, started_at` from the SQL stage. Compute the Break_In set and techniques for all candidates **without huge `IN (...)` lists**: query all successful `login_attempt` events and all techniques joined to the same SQL-stage subquery. Then compute severity with the existing `classify_severity`, apply the remaining filters and the sort in Python, take the total, and slice for `offset/limit`. Then load full rows for the page only.
4. `repeat_count` for the page: `SELECT src_ip, COUNT(*) ... WHERE src_ip IN (<page ips>) GROUP BY src_ip` (at most 200 IPs).
5. `reviewed` for the page: one query to the Review_Store for the page ids.

Sorting: `newest` = (`started_at` desc, `id` asc); `oldest` = (`started_at` asc, `id` asc); `severity` = (class desc, `started_at` desc, `id` asc). Class rank: Class_5=5, Class_3=3, Class_1=1.

`X-Total-Count` is set on the FastAPI `Response`. Caddy and the Dashboard are same-origin, so no CORS header exposure is needed.

### Facets (`GET /api/sessions/facets`)

```json
{"total": 2310, "severity": {"1": 2290, "3": 14, "5": 6}, "techniques": {"T1110": 120, "T1078": 20},
 "captured": 20, "reviewed": 200, "unreviewed": 2110,
 "earliest": "2026-11-25T19:30:00Z", "latest": "2026-11-26T11:02:25Z"}
```

Computed over all Sessions using the slow-path helpers. The router must declare `/api/sessions/facets` and `/api/sessions/review` before `/api/sessions/{session_id}`.

### Review_Store (`reviews.py`)

- A second SQLModel engine on `review_db_path`, table `reviewmark(session_id TEXT PRIMARY KEY, reviewed_at TIMESTAMP)`. Created at startup like the main Database.
- It's separate because the session Database is a rebuildable cache (brain spec). Deleting `brain.db` must not lose review progress. Review marks for sessions that no longer exist are harmless and ignored.
- `set_reviewed(ids, flag)`: upsert or delete; returns the number of rows changed. `reviewed_ids(ids)` and `count_reviewed(all_ids)` for list and facets.
- Endpoints: `PUT /api/sessions/{id}/review` with body `ReviewIn{reviewed: bool}` returns 404 for an unknown session. `POST /api/sessions/review` with `BulkReviewIn{ids: list[str] (1..200, each ≤ 64 chars), reviewed: bool}` returns `{"changed": n}`.
- Both are covered by the existing router-level `require_token` dependency. They write nothing except the Review_Store.

### Compose / config
`BRAIN_REVIEW_DB_PATH` is optional. The default places `reviews.db` in the same directory as `BRAIN_DATABASE_PATH`, which is already the writable `brain_data` volume, so **no compose change is required**. Add the variable, commented, to `.env.example`.

---

## Dashboard design

### TapeFilter (pure, `lib/tapeFilter.ts`)

```ts
type Sort = "newest" | "oldest" | "severity";
type DatePreset = "any" | "24h" | "7d" | "30d" | "custom";
interface TapeFilter {
  q: string; sev: (1|3|5)[]; tech: string[]; ip: string;
  captured: boolean | null; reviewed: boolean | null;
  date: DatePreset; from: string; to: string;   // from/to: YYYY-MM-DD (UTC), only for "custom"
  sort: Sort;
}
```

- Hash keys: `q, sev (comma list), tech (comma list), ip, captured (true|false), reviewed (true|false), date, from, to, sort`. Defaults are omitted. Invalid values fall back to their defaults. Lists are de-duplicated and sorted, so serialisation is canonical (this is what makes the round trip exact).
- `toApiParams(filter, now)` maps presets to `since` (`now - 24h/7d/30d`). Custom `from` maps to `since = from T00:00Z`, `to` maps to `until = (to + 1 day) T00:00Z`. Each `sev`/`tech` becomes a repeated param.
- `activeFilterCount` counts non-default fields (sort excluded) for the mobile "Filters (n)" badge.

### Routing
`parseHash` splits off `?…` before its current logic and returns `{page, tapeId, query}`. All existing outputs are unchanged when there is no `?`. `tapeHash(id, query)` builds `#/tapes/<id>?<query>`. Nav links still use `#/tapes` (which clears filters, as expected).

### Layout (Requirement 1), `styles/lab-tapes.css`
```css
@media (min-width: 641px) {
  .lab-tapes__list, .lab-tapes__replay {
    position: sticky; top: var(--space-3);
    max-height: calc(100vh - 2 * var(--space-3));
    overflow-y: auto; overscroll-behavior: contain;
  }
  .filter-bar { position: sticky; top: 0; z-index: 1; background: var(--bg); }
}
```
The page title scrolls away first, then both panes pin. The infinite-scroll sentinel keeps working because `IntersectionObserver` respects scroll-container clipping. When the selection changes, the Replay_Pane is scrolled to the top, and the selected row is scrolled into view with `scrollIntoView({block: "nearest"})` unless the change came from a click.

### Tape list
- Pages are fetched with `toApiParams(filter)` + `limit/offset`. When the serialised filter changes, loaded pages reset. The first page keeps polling every 5s with the current filter, merging as today.
- Rows are grouped by `groupByUtcDay` while sort is newest/oldest (labels: "Today", "Yesterday", `Mon 24 Nov 2026`, all UTC). Row layout: line 1 is IP + username (or muted "no username"); line 2 is `HH:MM:SS` + Severity_Chip + technique chips + `×N` badge (when `repeat_count ≥ 2`, a button with `aria-label="N tapes from this IP — show them"`).
- Unreviewed rows have a small volt dot plus visually hidden text "unreviewed". Reviewed rows use muted text.

### Replay header additions
`[◀ Newer] [Older ▶]` using `neighbours(loadedIds, selectedId)`. "Older" on the last loaded row triggers `loadMore()` and then selects the next row. Next to them: a review toggle and "All tapes from this IP".

Auto-review: a 2s timer starts when a Tape opens and is cancelled if the Tape changes or the operator toggles. On fire, `setReviewed(id, true)` updates the row optimistically. On error, the row reverts and an inline message shows.

### Filter Bar
Row 1 is the search box (label "Search IP or username") plus the result count ("142 of 2,310 tapes", `aria-live="polite"`). Row 2 is the chips (Class 5 / 3 / 1 with counts, Break-ins only, Unreviewed only), the technique `<select multiple>` or checkbox popover with counts, date preset `<select>` (+ two `<input type="date">` for Custom), and the sort `<select>`. Row 3 is "Clear filters" (only when active), "Mark all shown as reviewed" and the key hint "j/k next · / search". At 640px or less, everything except search collapses behind "Filters (n)". Facets refresh every 30s while Lab Tapes is open.

### Keyboard
A key handler on the List_Pane container handles ArrowDown/`j` and ArrowUp/`k` to select the next/previous loaded row and calls `preventDefault` only for those keys. A document-level handler focuses search on `/` unless the event target is an input, textarea, select or contentEditable.

### Lab Monitor shortcuts
Stat cards become `<a class="stat-card stat-card--link">` (same visuals, plus hover and focus styles). Technique bars are wrapped in `<a href="#/tapes?tech=ID">`. No attacker text is used in these `href`s: technique IDs come from a fixed regex-validated set, so the source-level safety test still holds.

---

## Correctness properties

### Property 1: Filtering is exact
For any generated set of sessions (random IPs, usernames, times, login success, techniques, review marks) and any valid TapeQuery, the ids returned across all pages equal the brute-force Python filter of the same predicate over all sessions. There are no extras, none missing, and no duplicates. **Validates: Requirements 2.2–2.8, 2.10**

### Property 2: Ordering and total
For any data and query, concatenated pages are sorted by the stated sort key with `id` tie-break, and `X-Total-Count` equals the brute-force match count. **Validates: Requirements 2.9, 2.10**

### Property 3: No-parameter backward compatibility
For any data, `GET /api/sessions?limit=L&offset=O` without new params returns the same ids, in the same order, with the same existing fields as the original implementation. **Validates: Requirement 2.1**

### Property 4: LIKE metacharacters are literal
For any `q` containing `%`, `_` or `\`, results are exactly those whose IP or username contains `q` literally. **Validates: Requirement 2.2**

### Property 5: Review marks are idempotent and isolated
Any sequence of PUT/POST review operations yields a final state equal to applying the last operation per id. Session, event and technique tables are unchanged. **Validates: Requirements 4.1, 4.2, 4.6, 4.7**

### Property 6: Facet sums are consistent
For any data, the severity counts sum to `total`, `reviewed + unreviewed = total`, and each technique count equals the number of sessions having it. **Validates: Requirement 3.1**

### Property 7: Filter hash round trip (fast-check)
For any TapeFilter in canonical form, `parseFilter(serializeFilter(f))` deep-equals `f`. For any arbitrary query string, `parseFilter` never throws and returns a valid TapeFilter. **Validates: Requirements 6.1, 6.5, 6.6**

### Property 8: Date grouping preserves order and membership (fast-check)
For any list of items with ISO timestamps, flattening `groupByUtcDay` returns the input in the same order, and every item sits under the label of its own UTC day. **Validates: Requirement 7.1**

### Property 9: Neighbours are adjacent (fast-check)
For any list of distinct ids and any member, `neighbours` returns the previous and next elements (null at the ends). For a non-member, both are null. **Validates: Requirement 8.1**

---

## Error handling
- The Brain returns 422 for invalid params (FastAPI validation), 404 for review of an unknown session, and 401 via the existing dependency.
- Dashboard: a failed facets fetch leaves the counts blank and does not block filtering. A failed list fetch shows the existing ConnectionLostBanner. A failed review toggle reverts the row and shows an inline message.

## Testing strategy
- **Brain:** Hypothesis properties 1–6 against an in-memory SQLite DB plus a temp Review_Store. Unit tests cover 422 cases, the 404 review case, route-order (`/facets` is not treated as an id) and the `X-Total-Count` header. The existing tests stay unchanged.
- **Dashboard:** fast-check properties 7–9. Component tests cover Filter Bar interactions and the URL updates they cause, debounce (fake timers), Clear filters, the empty filtered state, the ×N badge setting the IP filter, Newer/Older including load-more, the auto-review timer (fake timers) and revert on failure, keyboard j/k and `/`, Lab Monitor links (`href` values) and the mobile Filters button. jsdom has no layout, so the pane layout is asserted through classes and CSS presence.
- **Contract:** add a `brain-sessions-filtered.json` fixture (with `reviewed` and `repeat_count`) and a `brain-facets.json` fixture, and run them through the adapter in `contract.test.tsx`.
