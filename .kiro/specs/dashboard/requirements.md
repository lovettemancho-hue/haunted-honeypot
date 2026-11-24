# Requirements Document

## Introduction

The Dashboard is the "Frankenstein Lab Cam" web app of Haunted Honeypot. It is a React + TypeScript + Vite single-page app in `dashboard/` that reads the Brain API (contract defined in `.kiro/specs/brain`) and presents three pages: Lab Monitor (overview), Lab Tapes (session list and replay) and Containment (generated hardening rules). A login screen collects the API token. The app is built into static files by a multi-stage Dockerfile and served by Caddy, which also reverse-proxies `/api` to the Brain.

Visual design follows `.kiro/steering/design.md`, UI vocabulary follows `product.md`, and safety rules follow `security.md`.

Assumptions:
- The Brain container listens on internal port 8000 (not fixed by the Brain spec; confirm when the Brain is built).
- The JSON shapes of `top_passwords` and `technique_counts` in `GET /api/stats` are not fixed, so the Dashboard parses them defensively.
- No public or demo view is built. All pages sit behind login and show full IP addresses.

## Glossary

- **Dashboard**: The React + TypeScript + Vite single-page app in `dashboard/`.
- **Brain_API**: The HTTP API served by the Brain under `/api`, authenticated with a Bearer token.
- **API_Token**: The secret string the user enters at login and sends as `Authorization: Bearer <token>`.
- **Login_Screen**: The Dashboard view that asks for the API_Token.
- **Session_Store**: The browser `sessionStorage` entry holding the API_Token.
- **Poller**: The Dashboard component that refetches Brain_API data on a fixed interval.
- **Lab_Monitor**: The overview page.
- **Lab_Tapes**: The page listing sessions and replaying a selected session.
- **Containment_Page**: The page showing the checklist, generated rules and contained specimens.
- **Specimen**: An attacker, identified by source IP address.
- **Tape**: One attack session.
- **Lab_Voltage**: The threat level integer from 0 to 10 returned as `threat_level`.
- **Voltage_Meter**: The 10-segment meter that visualises Lab_Voltage.
- **Severity_Chip**: A label showing Class 1, Class 3 or Class 5, mapped from `Class_1`, `Class_3`, `Class_5`.
- **Stitched_Tag**: The tag marking a replay entry whose `generated_by` is `llm`.
- **Replay**: The chronological display of a Tape's events with relative timing.
- **Lab_Note**: The plain-English summary string of a Tape (`lab_note`).
- **Attacker_Text**: Any string originating from an attacker: usernames, passwords, commands, payloads, URLs, client strings, Lab_Note and IOC values.
- **Defanged_URL**: A URL rewritten with `hxxp://` or `hxxps://` and `[.]` in place of dots, shown as plain text.
- **Containment_Rule**: An item from `GET /api/containment` (id, kind, title, description, content, evidence_sessions).
- **Contained_Specimen**: A Specimen whose IP appears in a Tape listed in the `evidence_sessions` of at least one Containment_Rule.
- **Checklist**: The client-side list of hardening steps with checkable items on the Containment_Page.
- **Caddy**: The reverse proxy and static file server.
- **Dockerfile**: The multi-stage build file in `dashboard/` producing static assets.
- **Compose_File**: `deploy/docker-compose.yml`.
- **Helpers**: Pure TypeScript functions for escaping, defanging, formatting and IP masking, including `maskIp`.

## Requirements

### Requirement 1: Authentication

**User Story:** As an operator, I want to sign in with my API token, so that only authorised people can see captured attacker data.

#### Acceptance Criteria

1. WHILE no API_Token is present in the Session_Store, THE Dashboard SHALL display only the Login_Screen.
2. WHEN the user submits a non-empty API_Token, THE Dashboard SHALL validate it by requesting `GET /api/stats` with the header `Authorization: Bearer <token>`.
3. WHEN the validation request returns HTTP 200, THE Dashboard SHALL store the API_Token in the Session_Store and display the Lab_Monitor.
4. IF the Brain_API returns HTTP 401 for any request, THEN THE Dashboard SHALL remove the API_Token from the Session_Store and display the Login_Screen with a message that the token was rejected.
5. IF the validation request fails because the Brain_API is unreachable or returns a status other than 200 or 401, THEN THE Dashboard SHALL display an error message on the Login_Screen and keep the Login_Screen visible.
6. WHEN the user activates the sign-out button, THE Dashboard SHALL remove the API_Token from the Session_Store and display the Login_Screen.
7. THE Dashboard SHALL store the API_Token only in the Session_Store.
8. THE Login_Screen SHALL present the token field as a labelled input of type password and a submit button with a touch target of at least 44px.

### Requirement 2: Data polling

**User Story:** As an operator, I want the data to refresh on its own, so that I can watch attacks arrive live.

#### Acceptance Criteria

1. WHILE the user is signed in, THE Poller SHALL refetch the data of the visible page every 5 seconds.
2. WHILE the browser tab is hidden, THE Poller SHALL pause refetching.
3. WHEN the browser tab becomes visible, THE Poller SHALL refetch immediately and resume the 5-second interval.
4. WHEN the user navigates to another page or signs out, THE Poller SHALL cancel the polling of the previous page.
5. IF a poll request fails with a network error or a 5xx status, THEN THE Dashboard SHALL keep showing the last received data and display a connection-lost notice until a later poll succeeds.
6. THE Dashboard SHALL send the header `Authorization: Bearer <token>` on every Brain_API request.

### Requirement 3: Lab Monitor overview

**User Story:** As an operator, I want a single overview screen, so that I can judge the current threat at a glance.

#### Acceptance Criteria

1. THE Lab_Monitor SHALL display the Voltage_Meter with 10 segments, lighting a number of segments equal to Lab_Voltage clamped to the range 0 to 10.
2. THE Lab_Monitor SHALL display the numeric Lab_Voltage and a plain-language description of the threat level next to the Voltage_Meter.
3. THE Lab_Monitor SHALL display four stat cards showing attempts, unique IPs, captured sessions and longest session duration, each with a plain-language label.
4. THE Lab_Monitor SHALL display an experiment log table of Tapes from `GET /api/sessions` with columns for start time, Specimen IP, username, Severity_Chip, duration and status (open or closed).
5. WHEN the user activates a row of the experiment log table, THE Dashboard SHALL open that Tape in Lab_Tapes.
6. THE Lab_Monitor SHALL display ATT&CK technique bars from `technique_counts`, each bar showing the attack ID in monospace font and a length proportional to its count relative to the largest count.
7. THE Lab_Monitor SHALL display the top passwords from `top_passwords` in descending order of count, with at most 10 entries.
8. THE Lab_Monitor SHALL display a containment call-out that links to the Containment_Page and states in plain language that hardening rules are ready.
9. IF `technique_counts` or `top_passwords` is missing, empty, or in a shape the Dashboard cannot interpret, THEN THE Lab_Monitor SHALL display an empty-state message in place of that panel and keep rendering the other panels.
10. THE Dashboard SHALL accept `top_passwords` as either an array of objects with a password and a count, an array of two-element arrays, or an object mapping password to count.
11. THE Dashboard SHALL accept `technique_counts` as either an object mapping attack ID to count, an array of objects with an attack ID and a count, or an array of two-element arrays.
12. WHEN a Tape has `open` equal to true, THE experiment log table SHALL show its status as live and its duration measured to the current time.
13. WHILE the Brain_API returns zero sessions, THE experiment log table SHALL display an empty-state message.

### Requirement 4: Lab Tapes list and replay

**User Story:** As an operator, I want to replay what a specimen did, so that I can understand the attack step by step.

#### Acceptance Criteria

1. THE Lab_Tapes page SHALL display a list of Tapes ordered by `started_at` descending, each showing Specimen IP, username, start time, Severity_Chip and attack IDs.
2. WHEN the user scrolls to the end of the Tape list and more Tapes exist, THE Dashboard SHALL fetch the next page of up to 50 Tapes using `limit` and `offset`.
3. WHEN the user selects a Tape, THE Dashboard SHALL request `GET /api/sessions/{id}` and display the Replay.
4. THE Replay SHALL display each event in ascending timestamp order with its time offset from the first event, its kind, and its payload.
5. THE Replay SHALL display the payload of each event as JSON-decoded text, falling back to the raw payload string when the payload is not valid JSON.
6. WHEN an event has `generated_by` equal to `llm`, THE Replay SHALL display the Stitched_Tag on that event together with the plain-language explanation that the AI invented the response.
7. THE Replay SHALL display the Lab_Note, or a message that no note is available yet when `lab_note` is null.
8. THE Replay SHALL display each technique as a tag showing attack ID and name, and WHEN the user activates a technique tag, THE Replay SHALL scroll to and highlight the event referenced by `evidence_event_id`.
9. THE Replay SHALL display the list of IOCs of the Tape as received.
10. IF `GET /api/sessions/{id}` returns HTTP 404, THEN THE Dashboard SHALL display a message that the Tape was not found and a control to return to the Tape list.
11. WHILE the selected Tape has `open` equal to true, THE Poller SHALL refetch the selected Tape every 5 seconds so that new events appear in the Replay.
12. WHILE the viewport width is 640px or less, THE Lab_Tapes page SHALL show the Tape list and the Replay as separate stacked views with a back control between them.
13. THE Replay SHALL display the Specimen IP, port, username, start time, end time and Severity_Chip of the Tape.

### Requirement 5: Containment page

**User Story:** As a small-business owner, I want ready-made hardening rules, so that I can protect my real server without security expertise.

#### Acceptance Criteria

1. THE Containment_Page SHALL display a Checklist of hardening steps, each as a labelled checkbox with a plain-language description.
2. WHEN the user toggles a Checklist item, THE Dashboard SHALL update its checked state and the displayed progress count.
3. THE Containment_Page SHALL display each Containment_Rule from `GET /api/containment` with its title, kind, description, content in a monospace block, and the number of evidence sessions.
4. WHEN the user activates the copy button of a Containment_Rule, THE Dashboard SHALL copy the rule content to the clipboard and show a confirmation message.
5. IF the clipboard write fails, THEN THE Dashboard SHALL show a message that copying failed and keep the rule content selectable.
6. WHEN the user activates the download button, THE Dashboard SHALL request `GET /api/containment?format=script` with the Authorization header and save the response as a `.sh` file.
7. THE Containment_Page SHALL display the Contained_Specimens, each with its IP, the highest Severity_Chip among its Tapes and the number of its Tapes.
8. THE Dashboard SHALL derive Contained_Specimens by joining the `evidence_sessions` of all Containment_Rules with the sessions list.
9. WHILE no Containment_Rule exists, THE Containment_Page SHALL display an empty-state message in place of the rules and disable the download button.
10. IF the download request fails, THEN THE Dashboard SHALL display an error message and leave the page state unchanged.
11. THE Dashboard SHALL keep Checklist state in memory for the current page view only.
12. IF an `evidence_sessions` entry matches no Tape in the sessions list, THEN THE Dashboard SHALL omit that entry from the Contained_Specimens list.

### Requirement 6: Attacker text safety

**User Story:** As an operator, I want attacker-supplied text rendered safely, so that the dashboard cannot be used to attack me.

#### Acceptance Criteria

1. THE Dashboard SHALL render all Attacker_Text as React text nodes in monospace font.
2. THE Dashboard SHALL contain no use of `dangerouslySetInnerHTML`, `innerHTML` or `outerHTML`.
3. WHEN the Dashboard displays a URL found in Attacker_Text, THE Helpers SHALL convert it to a Defanged_URL.
4. THE Dashboard SHALL display every Defanged_URL as plain text and SHALL render no `<a>` element whose `href` is derived from Attacker_Text.
5. THE Helpers SHALL replace `http` and `https` schemes with `hxxp` and `hxxps` and each `.` in the host of a URL with `[.]`.
6. WHEN the Helpers defang a string that is already defanged, THE Helpers SHALL return the same string.
7. THE Helpers SHALL preserve all non-URL characters of the input string, including control characters, in the defanged output.
8. THE Helpers SHALL provide a function that strips or visibly replaces terminal control characters (ANSI escape sequences and non-printing control characters other than newline and tab) in Attacker_Text before display.
9. THE Helpers SHALL provide a `maskIp` function that replaces the last octet of an IPv4 address with `x` and returns any non-IPv4 input unchanged.
10. THE Dashboard SHALL display full IP addresses to signed-in users and SHALL provide no public or demo view.
11. THE Dashboard SHALL truncate display of any single Attacker_Text value longer than 4096 characters and indicate the truncation.

### Requirement 7: Design system and vocabulary

**User Story:** As a judge, I want the dashboard to look like the Frankenstein Lab Cam while staying readable, so that the theme supports understanding.

#### Acceptance Criteria

1. THE Dashboard SHALL define the colour tokens, typography and signature elements listed in `.kiro/steering/design.md` as CSS custom properties and plain CSS, without a UI kit.
2. THE Dashboard SHALL load Creepster, Chakra Petch and Share Tech Mono from Google Fonts and use Creepster for H1 page titles only.
3. THE Dashboard SHALL display in the header the lightning-bolt logo, a REC indicator with the text `REC · LAB 09` and an uptime counter, and a `STATUS: IT'S ALIVE` badge.
4. THE Dashboard SHALL use the product terms from `product.md` (Specimen, Experiment, Lab Tapes, Class 1/3/5, Lab voltage, Containment, Lab Monitor, Stitched) and pair every themed label with a plain-language description.
5. THE Dashboard SHALL render Severity_Chips as: Class 5 solid `--volt` with `--on-volt` text, Class 3 `--volt` outline, Class 1 `--border` outline with `--muted` text.
6. THE Dashboard SHALL render all interactive controls as native `button`, `a href`, `input` with `label`, or `select` elements with a minimum touch target of 44px.
7. THE Dashboard SHALL use square corners except for bolts, the REC dot and live dots, and SHALL use no emoji and no gradients.
8. THE Dashboard SHALL provide primary navigation between Lab Monitor, Lab Tapes and Containment on every signed-in page.
9. THE Dashboard SHALL meet a contrast ratio of at least 4.5:1 for body text on `--panel` and `--bg`.

### Requirement 8: Responsive layout

**User Story:** As an operator on a phone, I want every page to be usable on a narrow screen, so that I can check the lab anywhere.

#### Acceptance Criteria

1. WHILE the viewport width is 360px or more, THE Dashboard SHALL render every page without horizontal scrolling of the page body.
2. WHILE the viewport width is 640px or less, THE Dashboard SHALL stack side-by-side panels vertically.
3. WHILE a table is wider than its panel, THE Dashboard SHALL scroll that table horizontally inside its panel.
4. WHILE the viewport width is 640px or less, THE Dashboard SHALL keep the primary navigation reachable without leaving the current page.

### Requirement 9: Formatting helpers

**User Story:** As a developer, I want small pure helper functions, so that formatting and safety behaviour is unit-testable.

#### Acceptance Criteria

1. THE Helpers SHALL provide a duration formatter that converts a number of seconds into `HH:MM:SS`, and returns `00:00:00` for negative, NaN or non-finite input.
2. THE Helpers SHALL provide a timestamp formatter that converts an ISO 8601 string into a display string, and returns a placeholder dash for missing or unparsable input.
3. THE Helpers SHALL provide a relative-offset formatter that converts milliseconds into a `+S.mmm s` style offset for the Replay.
4. THE Helpers SHALL provide a severity mapper that converts `Class_1`, `Class_3` and `Class_5` into the display strings `Class 1`, `Class 3` and `Class 5`, and returns the input unchanged for any other value.
5. THE Helpers SHALL provide a defensive parser that normalises `top_passwords` and `technique_counts` into arrays of label and count pairs, returning an empty array for unrecognised input.
6. THE Dashboard SHALL include vitest tests covering the escaping or control-character helper, the defang helper, `maskIp`, the duration, timestamp and offset formatters, the severity mapper, and the defensive parsers.
7. THE vitest tests for the defang helper SHALL include property-based assertions that defanged output contains no substring `http://` or `https://` and that defanging is idempotent.

### Requirement 10: Build and container image

**User Story:** As a deployer, I want the dashboard built into static files by Docker, so that I can run it without installing Node on the server.

#### Acceptance Criteria

1. THE Dockerfile SHALL use a multi-stage build in which a Node stage runs `npm ci` and `npm run build` and a final stage contains only the static build output.
2. WHEN the image is built, THE Dockerfile SHALL produce static files from the Vite `dist` directory.
3. THE Dashboard build SHALL read no secrets and SHALL embed no API_Token.
4. THE Dashboard SHALL request the Brain_API using relative `/api` paths so that no Brain host name is embedded in the build.

### Requirement 11: Caddy serving and proxy

**User Story:** As a deployer, I want Caddy to serve the app over HTTPS and forward API calls, so that one domain exposes both.

#### Acceptance Criteria

1. THE Caddy configuration SHALL serve the Dashboard static files at `/`.
2. THE Caddy configuration SHALL reverse-proxy requests under `/api` to the Brain at `brain:8000`.
3. THE Caddy configuration SHALL read its site address from the `DOMAIN` environment variable.
4. IF the `DOMAIN` environment variable is unset or empty, THEN THE Caddy configuration SHALL listen on `:80`.
5. WHEN a request path matches no static file and is not under `/api`, THE Caddy configuration SHALL serve `index.html` so that client-side routes load.
6. WHERE `DOMAIN` is a public host name, THE Caddy configuration SHALL obtain HTTPS certificates through Caddy automatic HTTPS.

### Requirement 12: Compose integration and isolation

**User Story:** As a deployer, I want dashboard and caddy added to the existing compose file, so that `docker compose up -d` starts the whole product.

#### Acceptance Criteria

1. THE Compose_File SHALL define a `dashboard` service built from the Dockerfile and a `caddy` service, in addition to the existing `trap` service.
2. THE Compose_File SHALL leave the existing `trap` service definition, its volumes and its `trap_net` network unchanged.
3. THE Compose_File SHALL attach the `dashboard` and `caddy` services to a network of which the `trap` service is not a member.
4. THE Compose_File SHALL publish ports 80 and 443 on the `caddy` service and publish no ports on the `dashboard` service.
5. THE Compose_File SHALL pass the `DOMAIN` environment variable to the `caddy` service.
6. THE Compose_File SHALL persist Caddy certificate data in a named volume.
7. THE `dashboard` and `caddy` services SHALL run with `no-new-privileges` and `restart: unless-stopped`.
8. WHERE the `brain` service is defined in the Compose_File, THE `caddy` service SHALL be attached to the same network as the `brain` service.
