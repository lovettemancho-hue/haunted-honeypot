---
inclusion: always
---

# Tech stack and conventions

## Stack
- **Trap + Ghost Shell:** Python 3.12, `asyncssh`.
- **Brain (API + analyzer):** Python 3.12, FastAPI, SQLite via SQLModel (single file DB is enough for the hackathon; keep queries portable to Postgres).
- **Dashboard:** React + TypeScript + Vite. Plain CSS with design tokens from `design.md` (no UI kit).
- **LLM access:** one small provider-agnostic module (`brain/llm.py` and `trap/ghost/llm.py` share an interface). Provider and model come from environment variables; never hard-code keys.
- **Deployment:** Docker Compose (services: `trap`, `brain`, `dashboard`, `caddy`). Caddy handles HTTPS.
- **Testing:** `pytest` + `hypothesis` (property-based tests) for Python; `vitest` for the dashboard.
- **Lint / security scan:** `ruff`, `bandit`.

## Repository layout
```
trap/        # fake SSH server + Ghost Shell
  ghost/     # command handlers, fake filesystem, LLM fallback
brain/       # FastAPI app, analyzer, ATT&CK mapping, enrichment
dashboard/   # React app (Live Feed, Footage, Containment)
deploy/      # docker-compose.yml, Caddyfile, server setup script
docs/        # write-up, screenshots, architecture notes
.kiro/       # steering, specs, hooks — NEVER gitignored
```

## Conventions
- Type hints everywhere in Python; `mypy --strict` clean for `trap/` and `brain/`.
- Async I/O in the trap; no blocking calls on the event loop.
- Small, pure functions for anything testable (command parsing, filesystem state, ATT&CK mapping).
- Configuration only via environment variables, documented in `.env.example`.
- Every new module gets tests in the same pull request.
- Commit messages: imperative mood, short subject line.

## Data model (initial)
- `Session`: id, src_ip, src_port, started_at, ended_at, username, password, client_version, severity.
- `Event`: id, session_id, timestamp, kind (`login_attempt` | `command` | `response` | `download_attempt`), payload, generated_by (`scripted` | `llm`).
- `Technique`: session_id, attack_id (e.g. `T1110`), name, evidence_event_id.
