# Requirements Document

## Introduction

Lab Tapes works well with a few dozen Tapes but becomes hard to use once the trap has recorded hundreds or thousands. Problems an operator reported on the live deployment:

- When a Tape is selected and the operator scrolls the long list, the replay panel scrolls away with it. Picking a Tape far down the list means scrolling down to pick it, then all the way back up to read it.
- There is no way to find Tapes by date, severity, technique, attacker IP or username. Finding "all Class 5 Tapes from yesterday" means opening Tapes one by one.
- There is no way to tell which Tapes have already been reviewed. An operator who has reviewed 200 of 800 Tapes must scroll past the 200 again.
- Repeat attackers (one IP returning every few minutes, a "low and slow" brute force) are invisible because every visit is a separate row.
- The Lab Monitor shows counts (break-ins, techniques) but they don't lead anywhere.

This feature adds a two-pane layout where the replay stays in view, server-side search, filters and sorting, review tracking, review navigation (previous/next), repeat-attacker counts, and links from the Lab Monitor into filtered Tapes. It extends the `brain` and `dashboard` specs without changing any existing behaviour: with no new parameters, every existing endpoint, route and test behaves exactly as before.

Visual design follows `.kiro/steering/design.md`, vocabulary follows `product.md`, and safety rules follow `security.md`.

## Glossary

- **Tape_Filter**: The set of optional criteria applied to the Tape list: text query, severities, techniques, IP, break-ins only, date range, review state and sort order.
- **Text_Query**: A case-insensitive substring matched against a Tape's source IP and username.
- **Break_In**: A Tape with at least one successful login (the existing "captured" definition).
- **Review_Mark**: An operator's record that a Tape has been reviewed, with the time it was marked.
- **Review_Store**: The SQLite file that holds Review_Marks, separate from the rebuildable session Database.
- **Repeat_Count**: The number of stored Tapes whose source IP equals a given Tape's source IP.
- **Facets**: Totals that label the filter controls: Tapes per severity, per technique, Break_Ins, reviewed and unreviewed counts, and the total.
- **Filter_Bar**: The Lab Tapes control area holding the search box, filter chips, date range, sort and result count.
- **List_Pane**: The left column of Lab Tapes holding the Filter_Bar and the Tape list.
- **Replay_Pane**: The right column of Lab Tapes holding the selected Tape's replay.
- **Hash_Query**: The query string after `?` in the URL hash, for example `#/tapes/<id>?sev=5&tech=T1105`.

## Requirements

### Requirement 1: Replay stays in view (two-pane layout)

**User Story:** As an operator, I want the replay to stay on screen while I scroll the Tape list, so that I can pick any Tape and read it without scrolling back up.

#### Acceptance Criteria

1. WHILE the viewport is wider than 640px, THE Lab_Tapes page SHALL show the List_Pane and the Replay_Pane side by side, each scrolling independently, each no taller than the visible viewport.
2. WHEN the operator scrolls the List_Pane, THE Replay_Pane SHALL keep its position and content.
3. WHILE the List_Pane is scrolled, THE Filter_Bar SHALL stay visible at the top of the List_Pane.
4. WHEN a Tape is selected, THE Replay_Pane SHALL scroll to its top.
5. WHEN a Tape is selected by any means other than clicking its row (keyboard, Previous/Next, deep link), THE List_Pane SHALL scroll the selected row into view if it is loaded.
6. WHILE the viewport is 640px wide or less, THE Lab_Tapes page SHALL keep the existing stacked list/replay views with a back control, and the back control SHALL return to the list with the Tape_Filter preserved.

### Requirement 2: Search, filter and sort (Brain API)

**User Story:** As an operator, I want the Brain to filter Tapes for me, so that searching stays fast and correct even with thousands of Tapes.

#### Acceptance Criteria

1. WHEN `GET /api/sessions` is requested with none of the new parameters, THE Brain_API SHALL return exactly the same response as before this feature.
2. WHERE the `q` parameter is supplied (1 to 100 characters), THE Brain_API SHALL return only Sessions whose `src_ip` or `username` contains `q`, case-insensitively, treating `%`, `_` and `\` in `q` as literal characters.
3. WHERE one or more `severity` parameters are supplied (each `1`, `3` or `5`), THE Brain_API SHALL return only Sessions whose severity class is one of them.
4. WHERE one or more `technique` parameters are supplied, THE Brain_API SHALL return only Sessions with at least one of those ATT&CK technique IDs.
5. WHERE the `ip` parameter is supplied, THE Brain_API SHALL return only Sessions whose `src_ip` equals it exactly.
6. WHERE `captured=true` is supplied, THE Brain_API SHALL return only Break_Ins; WHERE `captured=false` is supplied, only Sessions that are not Break_Ins.
7. WHERE `since` or `until` (ISO-8601 date-times) are supplied, THE Brain_API SHALL return only Sessions with `started_at` at or after `since` and before `until`.
8. WHERE `reviewed=true` or `reviewed=false` is supplied, THE Brain_API SHALL return only Sessions that have, or do not have, a Review_Mark.
9. WHERE `sort` is supplied, THE Brain_API SHALL order results by `newest` (default: `started_at` descending), `oldest` (`started_at` ascending) or `severity` (severity class descending, then `started_at` descending), with ties broken by `id`.
10. THE Brain_API SHALL combine all supplied criteria with AND, apply `limit` and `offset` after filtering and sorting, and return the number of matching Sessions before pagination in an `X-Total-Count` response header.
11. IF a `severity` value is not `1`, `3` or `5`, a `technique` value does not match `^T\d{4}(\.\d{3})?$`, `q` is longer than 100 characters, `ip` is longer than 45 characters, `since`/`until` is not a valid date-time, or `sort` is not one of the allowed values, THEN THE Brain_API SHALL respond with status 422.
12. THE Brain_API SHALL add to each list item a `reviewed` boolean and a `repeat_count` integer (the Repeat_Count), without removing or renaming existing fields.
13. THE Brain_API SHALL build all filters with bound query parameters and SHALL NOT interpolate request values into SQL text.

### Requirement 3: Facets

**User Story:** As an operator, I want each filter to show how many Tapes it would match, so that I know where to look before I click.

#### Acceptance Criteria

1. WHEN an authenticated client requests `GET /api/sessions/facets`, THE Brain_API SHALL return the total number of Sessions, counts per severity class, counts per technique ID, the Break_In count, the reviewed and unreviewed counts, and the earliest and latest `started_at` (null when there are no Sessions).
2. IF the Database holds no Sessions, THEN THE Brain_API SHALL return all counts as zero, empty technique counts and null dates, with status 200.
3. THE route `/api/sessions/facets` SHALL NOT be shadowed by `/api/sessions/{session_id}`.

### Requirement 4: Review marks

**User Story:** As an operator reviewing hundreds of Tapes, I want reviewed Tapes to be remembered, so that I can continue where I stopped.

#### Acceptance Criteria

1. WHEN an authenticated client sends `PUT /api/sessions/{id}/review` with the JSON body `{"reviewed": true}` or `{"reviewed": false}`, THE Brain_API SHALL create or remove that Session's Review_Mark and return `{"id": ..., "reviewed": ...}`.
2. WHEN an authenticated client sends `POST /api/sessions/review` with `{"ids": [...], "reviewed": true|false}` holding 1 to 200 Session ids, THE Brain_API SHALL apply the mark to every listed stored Session and return the number changed.
3. IF a `PUT` names a Session that is not stored, THEN THE Brain_API SHALL respond with status 404; IF a bulk request lists unknown ids, THEN THE Brain_API SHALL ignore those ids.
4. IF the request body is invalid, the `ids` list is empty or longer than 200, THEN THE Brain_API SHALL respond with status 422.
5. THE Review_Store SHALL be a separate SQLite file (path from `BRAIN_REVIEW_DB_PATH`, defaulting to `reviews.db` next to the session Database) so that deleting and rebuilding the session Database keeps Review_Marks.
6. Marking SHALL be idempotent: repeating the same request SHALL leave the same state and return success.
7. THE review endpoints SHALL require the same bearer token as every other `/api` route and SHALL change nothing but Review_Marks.

### Requirement 5: Filter Bar (Dashboard)

**User Story:** As an operator, I want simple controls to narrow the Tape list, so that I can find the Tapes I care about in seconds.

#### Acceptance Criteria

1. THE Filter_Bar SHALL provide: a labelled search box (Text_Query), severity toggle chips Class 5 / Class 3 / Class 1 each with its Facet count, a "Break-ins only" toggle, an "Unreviewed only" toggle, a technique selector listing techniques with their Facet counts, a date range selector (Any time, Last 24 hours, Last 7 days, Last 30 days, Custom with from/to dates in UTC), and a sort selector (Newest, Oldest, Highest severity).
2. WHEN the operator types in the search box, THE Dashboard SHALL apply the Text_Query 300ms after the last keystroke.
3. WHEN any Tape_Filter value changes, THE Dashboard SHALL discard loaded pages, request the first page with the new Tape_Filter, and keep the current selection open in the Replay_Pane.
4. THE Filter_Bar SHALL show a live result count such as "142 of 2,310 tapes" from `X-Total-Count` and the Facet total, announced to assistive technology politely.
5. WHILE any Tape_Filter value differs from the default, THE Filter_Bar SHALL show a "Clear filters" control that restores the defaults.
6. IF the filtered list is empty, THEN THE List_Pane SHALL show "No tapes match these filters" with a "Clear filters" control.
7. WHILE the viewport is 640px wide or less, THE Filter_Bar SHALL collapse into a "Filters" button showing the number of active filters, which expands the controls.
8. Toggle chips SHALL expose their state with `aria-pressed` and have a touch target of at least 44px.

### Requirement 6: Filters in the URL

**User Story:** As an operator, I want filters to live in the address, so that Back/Forward work and I can bookmark or share a view.

#### Acceptance Criteria

1. THE Dashboard SHALL store the Tape_Filter in the Hash_Query using the keys `q`, `sev`, `tech`, `ip`, `captured`, `reviewed`, `from`, `to`, `sort`, omitting keys at their default value.
2. WHEN a Tape is selected, THE Dashboard SHALL navigate to `#/tapes/<id>?<current Hash_Query>`, preserving the Tape_Filter.
3. WHEN the hash changes through Back or Forward, THE Dashboard SHALL restore the Tape_Filter and selection from it.
4. THE route parser SHALL ignore the Hash_Query when deciding the page, so `#/tapes?sev=5` opens Lab Tapes and `#/tapes/<id>?sev=5` opens that Tape.
5. IF the Hash_Query contains unknown keys or invalid values, THEN THE Dashboard SHALL ignore them and use defaults for those values.
6. Parsing a serialised Tape_Filter SHALL return the same Tape_Filter (round trip).

### Requirement 7: Easier scanning of the list

**User Story:** As an operator, I want the list to be easy to scan, so that I can spot what matters quickly.

#### Acceptance Criteria

1. WHILE the sort is Newest or Oldest, THE Tape list SHALL group rows under date headings in UTC ("Today", "Yesterday", or a date such as "Mon 24 Nov 2026"), and each row SHALL show only the time of day.
2. THE Tape row SHALL show the source IP, the username or a muted "no username" label, the time, the Severity_Chip and technique chips.
3. WHEN a Tape's Repeat_Count is 2 or more, THE Tape row SHALL show a "×N" badge whose label explains it ("N tapes from this IP"); WHEN the badge is activated, THE Dashboard SHALL filter the list to that IP.
4. THE Tape row SHALL show unreviewed Tapes with a visible marker and reviewed Tapes in a muted style, with the state also exposed as text for assistive technology.
5. All attacker-supplied strings in the list SHALL continue to be rendered through `AttackerText`.

### Requirement 8: Review workflow

**User Story:** As an operator, I want to move through Tapes one after another and have them marked as reviewed, so that reviewing hundreds of Tapes is quick.

#### Acceptance Criteria

1. THE Replay_Pane header SHALL provide "Newer" and "Older" controls that select the adjacent Tape in the current filtered list order, disabled at either end; WHEN "Older" is used at the last loaded row and more pages exist, THE Dashboard SHALL load the next page and then select the next Tape.
2. WHEN a Tape has been open in the Replay_Pane for 2 seconds, THE Dashboard SHALL mark it reviewed through the Brain_API, unless the operator has already toggled its review state during this visit.
3. THE Replay_Pane SHALL provide a "Mark unreviewed" / "Mark reviewed" toggle that updates the row immediately and reverts with an inline error if the request fails.
4. THE Filter_Bar SHALL provide "Mark all shown as reviewed", which marks the loaded rows of the current filtered list (in batches of at most 200) after a confirmation that states how many Tapes will be marked.
5. WHILE focus is inside the List_Pane, the keys ArrowDown/`j` and ArrowUp/`k` SHALL select the next and previous Tape; WHILE focus is not in a text field, `/` SHALL focus the search box; a short visible hint SHALL list these keys.
6. THE Replay_Pane SHALL offer "All tapes from this IP", which filters the list to the selected Tape's source IP.

### Requirement 9: Lab Monitor shortcuts

**User Story:** As an operator, I want the Lab Monitor numbers to take me to the matching Tapes, so that I can go from overview to evidence in one click.

#### Acceptance Criteria

1. THE Break-ins stat card SHALL link to `#/tapes?captured=true`.
2. THE Login attempts and Unique attacker IPs stat cards SHALL link to `#/tapes`.
3. Each ATT&CK technique bar SHALL link to `#/tapes?tech=<id>`.
4. These links SHALL be keyboard-focusable, show a visible focus style, and keep the existing card and bar visuals.

### Requirement 10: No regressions

**User Story:** As the maintainer, I want the new features to leave everything else working, so that the live deployment stays reliable.

#### Acceptance Criteria

1. All existing Brain, Trap and Dashboard tests SHALL pass; a test MAY be updated only where this document intentionally changes the asserted text or markup (for example "no username" in place of "—"), and each such change SHALL be listed in the final task's notes.
2. Existing routes `#/monitor`, `#/tapes`, `#/tapes/<id>` and `#/containment` SHALL keep working.
3. THE Dashboard SHALL continue to poll the first page of the (filtered) list every 5 seconds and keep loaded rows stable while new Tapes arrive.
4. THE Dashboard and Brain SHALL keep passing `npm run build`, `ruff`, `mypy --strict` and `bandit`.
5. Source files SHALL be saved as UTF-8 without BOM and edited with the editor's file tools, as stated in `tech.md`.
