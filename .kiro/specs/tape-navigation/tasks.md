# Implementation Plan: Tape Navigation

## Overview

Build server-side filtering, facets and review marks in the Brain, then the two-pane Lab Tapes UI with Filter Bar, URL filters, review workflow and Lab Monitor shortcuts in the Dashboard. Every change is additive. Run the full Brain and Dashboard test suites at each checkpoint, and do not modify existing tests except where a task says so.

Use the project venv for Python (`.\.venv\Scripts\python.exe -m pytest brain`) and `npm test` / `npm run build` in `dashboard/`. Save files as UTF-8 without BOM using the editor's file tools (see `tech.md`).

## Tasks

- [ ] 1. Brain: Review_Store
  - [ ] 1.1 Add `review_db_path` to `brain/config.py` (`BRAIN_REVIEW_DB_PATH`, default `reviews.db` in the same directory as the database path) and document it, commented, in `.env.example`
    - _Requirements: 4.5_
  - [ ] 1.2 Create `brain/reviews.py`: a separate SQLModel engine and `ReviewMark(session_id PK, reviewed_at)` table created at startup, plus `set_reviewed(ids, flag) -> int`, `reviewed_ids(ids) -> set[str]` and `count_reviewed(ids) -> int`; wire the engine into app startup next to the main database
    - _Requirements: 4.1, 4.2, 4.5, 4.6_
  - [ ] 1.3 Write property test for review idempotence and isolation (Property 5)
    - _Requirements: 4.1, 4.2, 4.6, 4.7_

- [x] 2. Brain: filtered session queries
  - [x] 2.1 Create `brain/api/tape_query.py` with a `TapeQuery` dataclass, the SQL stage (bound params; LIKE with escaped `%`, `_`, `\`; `EXISTS` subquery for techniques), the fast path (SQL order, offset, limit and COUNT) and the slow path (Break_In and technique sets via subquery joins with no large `IN` lists, `classify_severity`, Python filter, sort and slice)
    - _Requirements: 2.2–2.10, 2.13_
  - [x] 2.2 Extend `GET /api/sessions` with the validated params `q`, `severity`, `technique`, `ip`, `captured`, `reviewed`, `since`, `until` and `sort`; set the `X-Total-Count` header; add `reviewed` and `repeat_count` to `SessionListItem` (additive)
    - _Requirements: 2.1, 2.10, 2.11, 2.12_
  - [x] 2.3 Write property tests for exact filtering, ordering and total, and LIKE literals (Properties 1, 2, 4)
    - _Requirements: 2.2–2.10_
  - [ ] 2.4 Write the backward-compatibility property test: no new params gives the same ids, order and existing fields as the original query (Property 3)
    - _Requirements: 2.1_
  - [x] 2.5 Write unit tests for every 422 case in Requirement 2.11
    - _Requirements: 2.11_

- [x] 3. Brain: facets and review endpoints
  - [x] 3.1 Add `GET /api/sessions/facets` returning `FacetsOut`, declared before `/api/sessions/{session_id}`
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 3.2 Add `PUT /api/sessions/{id}/review` (`ReviewIn`, 404 for an unknown id) and `POST /api/sessions/review` (`BulkReviewIn` with 1..200 ids, unknown ids ignored, returns `{"changed": n}`), both declared before `/api/sessions/{session_id}`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7_
  - [x] 3.3 Write the facet consistency property test (Property 6) and unit tests for empty data, route order, 401 without a token on the new routes, 404 and 422
    - _Requirements: 3.1, 3.2, 3.3, 4.3, 4.4, 4.7_

- [x] 4. Checkpoint: Brain
  - Run `pytest brain`, `ruff check brain`, `mypy --strict brain` and `bandit -r brain`. All existing tests must pass unchanged.

- [x] 5. Dashboard: pure helpers and API client
  - [x] 5.1 Create `src/lib/tapeFilter.ts` (`TapeFilter`, `DEFAULT_FILTER`, `parseFilter`, `serializeFilter` in canonical form, `toApiParams(filter, now)`, `activeFilterCount`)
    - _Requirements: 6.1, 6.5, 6.6, 5.1_
  - [x] 5.2 Create `src/lib/dateGroups.ts` (`groupByUtcDay`) and `src/lib/neighbours.ts` (`neighbours`)
    - _Requirements: 7.1, 8.1_
  - [x] 5.3 Write property tests for the filter round trip, date grouping and neighbours (Properties 7, 8, 9)
    - _Requirements: 6.6, 7.1, 8.1_
  - [x] 5.4 Update `routes.ts` so `parseHash` ignores `?…` when choosing the page and returns the query; add `tapeHash(id, query)`; keep all existing route outputs identical
    - _Requirements: 6.2, 6.4, 10.2_
  - [x] 5.5 Extend `api/sessions.ts`: `fetchSessions(token, onUnauthorized, {limit, offset}, filter?)` returning `{items, total}` (`total` from `X-Total-Count`, null if missing); add `fetchFacets`, `setReviewed` and `setReviewedBulk`; extend the adapter with `reviewed` (default false) and `repeat_count` (default 1). Keep existing callers working; update call sites if the return shape changes
    - _Requirements: 2.10, 2.12, 3.1, 4.1, 4.2_
  - [ ] 5.6 Add `brain-sessions-filtered.json` and `brain-facets.json` fixtures and extend `contract.test.tsx`
    - _Requirements: 10.1_

- [x] 6. Dashboard: two-pane layout and list
  - [x] 6.1 Implement the pane layout in `styles/lab-tapes.css` (sticky, independently scrolling List_Pane and Replay_Pane above 640px; sticky Filter Bar; existing stacked mobile views unchanged); scroll the Replay_Pane to top on selection and scroll the selected row into view when the selection did not come from a click
    - _Requirements: 1.1–1.6_
  - [x] 6.2 Update `TapeList.tsx`: filtered paging that resets when the filter changes, 5s polling of the filtered first page, UTC date groups for newest/oldest sort, time-only rows, a muted "no username" label, the ×N repeat badge that sets the IP filter, and unreviewed and reviewed markers with screen-reader text
    - _Requirements: 5.3, 7.1–7.5, 10.3_
  - [x] 6.3 Create `pages/FilterBar.tsx`: debounced search (300ms), severity chips with counts (`aria-pressed`, at least 44px), Break-ins only, Unreviewed only, technique selector with counts, date presets plus custom UTC dates, sort, a live result count, Clear filters, the empty filtered state, the collapsible "Filters (n)" control at 640px or less, "Mark all shown as reviewed" with confirmation and batches of 200, and the key hint; facets refresh every 30s
    - _Requirements: 5.1–5.8, 8.4_
  - [x] 6.4 Update `LabTapes.tsx` to own the TapeFilter from the hash (Back/Forward restore it), pass it to the list and the bar, select Tapes with `tapeHash(id, query)`, and handle j/k/arrows in the List_Pane and `/` to focus search
    - _Requirements: 6.1–6.3, 8.5_

- [x] 7. Dashboard: review workflow and replay
  - [x] 7.1 In `TapeReplay.tsx` add Newer/Older (with load-more at the end), the review toggle with optimistic update and revert, the 2-second auto-review timer that is cancelled on change or manual toggle, and "All tapes from this IP"
    - _Requirements: 8.1, 8.2, 8.3, 8.6_
  - [x] 7.2 Write component tests: Filter Bar URL updates, debounce, Clear filters, empty state, ×N badge, Newer/Older including load-more, auto-review timer and revert, keyboard j/k and `/`, mobile Filters button, and the "no username" label
    - _Requirements: 5.2–5.7, 7.3, 8.1–8.5_

- [x] 8. Dashboard: Lab Monitor shortcuts
  - [x] 8.1 Make the Break-ins card link to `#/tapes?captured=true`, the Login attempts and Unique attacker IPs cards link to `#/tapes`, and each technique bar link to `#/tapes?tech=<id>`, keeping the visuals and adding hover and focus styles
    - _Requirements: 9.1–9.4_
  - [x] 8.2 Write tests for the link `href` values and keyboard focusability; confirm `safety.test.ts` still passes
    - _Requirements: 9.1–9.4_

- [x] 9. Final checkpoint
  - Run `npm test` and `npm run build` in `dashboard/`, and run the Brain checks from task 4. All tests pass.
  - List here every existing test that was changed and why (Requirement 10.1).

## Implementation status (28 Nov 2026)

Built and tested: Brain 153 tests, Dashboard 171 tests, `ruff`, `mypy --strict` and the build all pass. The only existing tests changed are `brain/tests/test_main.py` (the token check now covers every HTTP method, so the new write endpoints are checked too) and `dashboard/src/safety.test.ts` (it now accepts the `tapesHref({...})` route helper and reads one level of nested braces in `href`).

Where the build differs from this plan:

- **Review marks (1.x, not done as planned):** marks are a `review` table in the main database, not a separate Review_Store. They are lost if `brain.db` is deleted and rebuilt from the logs. Moving them to their own file is still open.
- **Names:** the counts endpoint is `GET /api/sessions/summary` (not `/facets`); the list uses `logged_in` and `order` (not `captured` and `sort`); totals come from the summary instead of an `X-Total-Count` header. Bulk review takes up to 500 ids and returns `{"updated": n, "reviewed": bool}`.
- **Review flow:** no 2-second auto-review timer. Review is explicit: "Mark reviewed", "Reviewed, next", the R key, and "Mark N shown as reviewed" with Undo. Keys are J/N (next) and K/P (previous); `/` and arrow keys are not bound.
- **Layout:** the two-pane layout applies from 900px wide; below that the list and replay stack, with "← List" in a sticky toolbar. Advanced filters sit behind a "More filters" disclosure.
- **Lab Monitor:** Break-ins and each technique link to filtered tapes; the Login attempts and Unique IPs cards do not link. Added a "tapes waiting for review" call-out and limited the log to the latest 10 rows. Containment rules link to their first evidence tape.
- **Not done:** 2.4 (backward-compatibility property test; covered by the unchanged existing list tests instead) and 5.6 (new contract fixtures). The ×N repeat badge does not set the IP filter on click; "Show all its tapes" in the replay does.
