# Implementation Plan: Dashboard

## Overview

Build the React + TypeScript + Vite dashboard in `dashboard/` bottom-up. Pure helpers in `src/lib/` come first, followed by the API client, auth and polling layer, then shared components, then the three pages, then the Docker, Caddy and Compose integration. Every attacker-supplied string goes through the single `AttackerText` component. Property tests use vitest + fast-check, with at least 100 iterations each, and are tagged `Feature: dashboard, Property N: <title>`.

## Tasks

- [x] 1. Scaffold the dashboard project
  - [x] 1.1 Create the Vite + React + TypeScript project in `dashboard/`
    - Create `package.json` (react, react-dom, vite, typescript, vitest, fast-check, @testing-library/react, jsdom), `tsconfig.json` (strict), `vite.config.ts`, `vitest.config.ts`, `index.html`, `src/main.tsx` and a placeholder `src/App.tsx`
    - Add a vitest setup file and `npm run build` / `npm test` scripts (`vitest --run`)
    - Use relative `/api` paths only, with no secrets or hostnames in config
    - _Requirements: 10.3, 10.4_

  - [x] 1.2 Add design tokens and base styles
    - Create `src/styles/tokens.css` with the colour, typography and spacing custom properties from `.kiro/steering/design.md`
    - Create `src/styles/base.css` and `src/styles/components.css` (square corners, no gradients, 44px touch targets, mobile breakpoint at 640px, in-panel horizontal table scroll)
    - Load Creepster, Chakra Petch and Share Tech Mono from Google Fonts in `index.html`, with Creepster for H1 only
    - Import the styles in `main.tsx`
    - _Requirements: 7.1, 7.2, 7.6, 7.7, 8.1, 8.2, 8.3_

- [x] 2. Implement pure helper modules in `src/lib/`
  - [x] 2.1 Implement the safety helpers
    - `sanitize.ts`: `stripControlChars` (ANSI CSI/OSC sequences and C0/C1 controls except `\n` and `\t`)
    - `defang.ts`: `defangUrl` and idempotent `defangText`
    - `truncate.ts`: `truncateAttackerText` (limit 4096)
    - `maskIp.ts`: `maskIp` (IPv4 only)
    - _Requirements: 6.3, 6.5, 6.6, 6.7, 6.8, 6.9, 6.11_

  - [x] 2.2 Write property tests for defanging
    - **Property 13: Defanging removes every live URL scheme and is idempotent**
    - **Property 14: Defanging replaces exactly the scheme and host dots, and preserves everything else**
    - **Validates: Requirements 6.3, 6.4, 6.5, 6.6, 6.7, 9.7**

  - [x] 2.3 Write property tests for sanitize, maskIp and truncate
    - **Property 15: Control-character stripping removes exactly the disallowed bytes**
    - **Property 16: `maskIp` affects only valid IPv4 input, and always drops the last octet**
    - **Property 17: Truncation is exact and total**
    - **Validates: Requirements 6.8, 6.9, 6.11**

  - [x] 2.4 Implement the formatters
    - `duration.ts`: `formatDuration`
    - `timestamp.ts`: `formatTimestamp` (returns `—` for bad input)
    - `offset.ts`: `formatOffset`
    - `severity.ts`: `mapSeverity` and `severityChipVariant`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 7.5_

  - [x] 2.5 Write property tests for the formatters
    - **Property 18: Duration formatting is total and correctly bounded**
    - **Property 19: Timestamp formatting is total**
    - **Property 20: Offset formatting is total and monotonic**
    - **Property 21: Severity mapping and chip variant are total functions over all strings**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 7.5**

  - [x] 2.6 Implement the stat parsers and voltage helpers
    - `statParsers.ts`: `parseTopPasswords` and `parseTechniqueCounts` accepting the three documented shapes, returning `[]` for anything unrecognised and never throwing
    - `voltage.ts`: `clampVoltage`, `voltageDescription`, `techniqueBarWidth`
    - _Requirements: 3.1, 3.2, 3.6, 3.9, 3.10, 3.11, 9.5_

  - [x] 2.7 Write property tests for voltage helpers
    - **Property 1: Voltage meter segment count is the clamped threat level**
    - **Property 2: Technique bar width is proportional and bounded**
    - **Validates: Requirements 3.1, 3.6**

  - [x] 2.8 Write property tests for the stat parsers
    - **Property 3: Stat shape parsers are equivalent across all documented input shapes**
    - **Property 4: Unrecognized stat input always normalizes to an empty list**
    - **Validates: Requirements 3.9, 3.10, 3.11, 9.5**

  - [x] 2.9 Implement replay, checklist and containment helpers
    - `replay.ts`: `sortEventsWithOffsets`, `decodePayload` (never throws) and an `isStitched(event)` predicate (`generated_by === "llm"`)
    - `checklist.ts`: immutable `toggleItem` and `progressCount`
    - `containmentSpecimens.ts`: `deriveContainedSpecimens` (join on `evidence_sessions`, drop unmatched ids, highest severity `Class_5 > Class_3 > Class_1`)
    - _Requirements: 4.4, 4.5, 4.6, 5.2, 5.7, 5.8, 5.12_

  - [x] 2.10 Write property tests for replay helpers
    - **Property 8: Event ordering and offsets are correct for any timestamp arrangement**
    - **Property 9: Payload decoding never throws and round-trips valid JSON**
    - **Property 10: The Stitched tag appears exactly for LLM-generated events** (tested against `isStitched`)
    - **Validates: Requirements 4.4, 4.5, 4.6**

  - [x] 2.11 Write property tests for checklist and containment helpers
    - **Property 11: Checklist progress always equals the number of checked items**
    - **Property 12: Contained specimens are derived exactly from evidence that matches a known Tape**
    - **Validates: Requirements 5.2, 5.7, 5.8, 5.12**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement the API client, auth and polling layer
  - [x] 4.1 Implement the API types, client and endpoint functions
    - `api/types.ts`: interfaces from the design's Data Models (`top_passwords` and `technique_counts` typed `unknown`)
    - `api/client.ts`: `ApiError` and `fetchJson`, which always sends `Authorization: Bearer <token>`, calls `onUnauthorized` once on 401 and then throws, and throws `ApiError` on other non-2xx
    - `api/stats.ts`, `api/sessions.ts` (with `limit` and `offset`) and `api/containment.ts` (rules and `?format=script` Blob download)
    - _Requirements: 1.2, 1.4, 2.6, 4.2, 4.3, 5.6, 10.4_

  - [x] 4.2 Write property tests for the API client
    - **Property 6: The Authorization header is present on every request through the API client**
    - **Property 7: A 401 response always triggers sign-out, regardless of endpoint**
    - Use a mocked `fetch` and run each property across all endpoint functions
    - **Validates: Requirements 1.4, 2.6**

  - [x] 4.3 Implement token storage and the auth context
    - `auth/tokenStorage.ts`: get, set and clear on `sessionStorage` only
    - `auth/AuthContext.tsx`: provides `token`, `signIn` and `signOut`, and exposes an `onUnauthorized` handler that clears storage, signs out and sets a "token rejected" message
    - _Requirements: 1.1, 1.3, 1.4, 1.6, 1.7_

  - [x] 4.4 Implement the `usePoller` hook
    - 5000 ms interval with an immediate fetch on mount or dependency change
    - Pause on `visibilitychange` to hidden, then refetch immediately and resume on visible
    - Clear the interval on unmount or when `enabled` is false
    - Keep the last good `data` and set `connectionLost` on network or 5xx errors; let 401 propagate
    - Return `refetchNow`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 4.11_

  - [x] 4.5 Write tests for `usePoller`
    - **Property 5: Every poll outcome sequence leaves the displayed data as the last success**
    - Add unit tests with fake timers for interval ticking, pause and resume on visibility, and cancellation on unmount or `enabled=false`
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

- [x] 5. Implement shared components, shell and login
  - [x] 5.1 Implement the shared presentational components
    - `AttackerText.tsx`: `stripControlChars` → `truncateAttackerText` → `defangText`, rendered as a React text child in a monospace span with a "(truncated)" marker, with no `<a>` and no raw HTML
    - `SeverityChip.tsx`, `VoltageMeter.tsx` (10 segments, plain-language description), `StitchedTag.tsx` (with "the AI invented this response" explanation), `EmptyState.tsx` and `ConnectionLostBanner.tsx`
    - _Requirements: 3.1, 3.2, 4.6, 6.1, 6.2, 6.4, 6.11, 7.4, 7.5_

  - [x] 5.2 Write unit tests for the shared components
    - `AttackerText` renders HTML-like input, control characters and URLs as escaped, defanged text with no `<a>` or injected elements, and shows the truncation marker above 4096 characters
    - `SeverityChip` variants, `VoltageMeter` segment count, and `StitchedTag` shown only for `llm` events
    - _Requirements: 6.1, 6.4, 6.11, 7.5, 3.1_

  - [x] 5.3 Implement the app shell and login screen
    - `Header.tsx`: bolt logo, `REC · LAB 09` with an uptime counter, `STATUS: IT'S ALIVE` badge and a sign-out button
    - `Nav.tsx`: primary navigation for Lab Monitor, Lab Tapes and Containment, reachable at 640px or less
    - `App.tsx`: auth gate that renders `LoginScreen` or `AuthedApp`
    - `AuthedApp.tsx`: router with placeholder pages
    - `pages/LoginScreen.tsx`: labelled password input and a 44px submit button, which validates via `fetchStats` and handles the 200, 401 and other-error outcomes
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 7.3, 7.6, 7.8, 8.4_

- [x] 6. Implement the pages
  - [x] 6.1 Implement the Lab Monitor page
    - `pages/LabMonitor.tsx`: Voltage_Meter with numeric level and description, four stat cards, experiment log table (start time, IP, username, Severity_Chip, duration, open/closed status, with live duration for open Tapes, and a row click navigating to the Tape), technique bars, top 10 passwords, containment call-out, and independent empty states per panel
    - Poll with `usePoller` using `fetchStats` and `fetchSessions`
    - Render all attacker strings via `AttackerText`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.12, 3.13, 2.1_

  - [x] 6.2 Implement the Lab Tapes list and replay
    - `pages/LabTapes.tsx` and `pages/TapeList.tsx`: list ordered by `started_at` descending, infinite scroll fetching 50 per page via `limit` and `offset`
    - `pages/TapeReplay.tsx`: header fields (IP, port, username, start and end time, Severity_Chip), events with offsets, kinds, decoded payloads and Stitched tags, Lab_Note or a "no note yet" message, technique tags that scroll to and highlight the evidence event, IOC list, and a 404 "Tape not found" state with a back control
    - Poll with `enabled: tape.open`
    - At 640px or less, show the list and replay as stacked views with a back control
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13_

  - [x] 6.3 Implement the Containment page
    - `pages/Containment.tsx`: in-memory Checklist with progress count (via `checklist.ts`), rule cards (title, kind, description, monospace content, evidence count), copy button with success and failure messages, download button that saves a `.sh` file (disabled with no rules, with an error message on failure), Contained_Specimens from `deriveContainedSpecimens`, and an empty state
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12_

  - [x] 6.4 Write unit tests for the login and auth flow
    - Cover 200 (stores the token and shows Lab Monitor), 401 (rejected, nothing stored), network error and other status (error shown, nothing stored), sign-out clearing the token, and a 401 from a page poller returning to the login screen
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

- [x] 7. Wire the pages and add page-level tests
  - [x] 7.1 Wire the pages into the router
    - Replace the placeholder pages in `AuthedApp.tsx` with `LabMonitor`, `LabTapes` and `Containment`
    - Support opening a Tape by id from a Lab Monitor row, and the containment call-out link
    - Cancel the previous page's polling on navigation
    - _Requirements: 2.4, 3.5, 3.8, 4.3, 7.8_

  - [x] 7.2 Write unit tests for the pages
    - Lab Monitor: stat cards, log columns, row navigation, per-panel empty states with malformed stats, zero sessions, live status
    - Lab Tapes: list order, pagination `limit` and `offset`, replay fields, Stitched tag, technique tag scroll (mock `scrollIntoView`), 404 handling, no polling once the Tape is closed, stacked view at 640px
    - Containment: checklist progress, copy success and failure, download success and failure, disabled download with no rules, specimens list
    - _Requirements: 3.3, 3.4, 3.5, 3.9, 3.13, 4.1, 4.2, 4.8, 4.10, 4.11, 5.2, 5.4, 5.5, 5.9, 5.10_

  - [x] 7.3 Write source-level safety tests
    - Scan `dashboard/src` and fail on `dangerouslySetInnerHTML`, `innerHTML` or `outerHTML`
    - Assert that no `<a>` element has an `href` derived from attacker text
    - Check design-token text colours meet the 4.5:1 contrast ratio on `--bg` and `--panel`
    - _Requirements: 6.2, 6.4, 7.9_

- [x] 8. Implement build, Caddy and Compose integration
  - [x] 8.1 Create the multi-stage Dockerfile
    - Create `dashboard/Dockerfile`: a Node stage running `npm ci` and `npm run build`, and a final stage containing only `dist`
    - Create `dashboard/.dockerignore`
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 8.2 Create the Caddyfile
    - Create `deploy/Caddyfile` with the site address from `{$DOMAIN::80}`, static files at `/`, `handle /api/*` reverse-proxied to `brain:8000`, and an SPA fallback to `index.html`
    - Rely on automatic HTTPS for public hostnames
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 8.3 Extend `deploy/docker-compose.yml`
    - Add the `dashboard` service (built from `dashboard/Dockerfile`, no published ports) and the `caddy` service (ports 80 and 443, `DOMAIN` env, Caddyfile mount, named volume for certificate data)
    - Put both on a new network that `trap` is not a member of
    - Set `no-new-privileges` and `restart: unless-stopped` on both
    - Attach `caddy` to the `brain` network where a `brain` service is defined
    - Leave the `trap` service, its volumes and `trap_net` unchanged
    - Add `DOMAIN` to `.env.example`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.8_

  - [x] 8.4 Write config tests for the deployment files
    - Parse the compose and Caddy files and assert: `trap` unchanged and isolated from the new network, ports published only on `caddy`, `/api` proxied to `brain:8000`, `:80` fallback, SPA fallback, and a named volume
    - Build the app and assert that `dist/` exists and contains no token or secret values
    - _Requirements: 10.2, 10.3, 11.2, 11.4, 11.5, 12.2, 12.3, 12.4, 12.6, 12.7_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Property tests validate the universal correctness properties from the design. Unit tests cover examples and edge cases.
- Attacker-supplied text must only be rendered through `AttackerText`. Never use `dangerouslySetInnerHTML` or build a link from attacker text.
- Run tests in single-run mode (`vitest --run`), not watch mode.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "2.4", "2.6", "2.9", "8.1", "8.2", "8.3"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.5", "2.7", "2.8", "2.10", "2.11", "4.1", "4.3", "8.4"] },
    { "id": 3, "tasks": ["4.2", "4.4", "5.1"] },
    { "id": 4, "tasks": ["4.5", "5.2", "5.3"] },
    { "id": 5, "tasks": ["6.1", "6.2", "6.3", "6.4"] },
    { "id": 6, "tasks": ["7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3"] }
  ]
}
```
