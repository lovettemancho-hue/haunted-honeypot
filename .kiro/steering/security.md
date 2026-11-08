---
inclusion: always
---

# Security rules (non-negotiable)

This project deliberately invites attackers in. These rules exist so the honeypot can never become a weapon or a liability. If a requested change conflicts with any rule below, stop and flag it instead of implementing it.

## The Ghost Shell never executes anything
- Attacker input is **data, never code**. No `subprocess`, `os.system`, `eval`, `exec`, `pty`, or shell spawning anywhere in `trap/`.
- "Downloads" (`wget`, `curl`) are simulated: the trap may record the URL, but it must never fetch it.
- All filesystem effects happen in an in-memory fake filesystem per session. Nothing is written to the real disk except the session log.

## Isolation
- The trap container runs as a non-root user, with a read-only root filesystem, dropped Linux capabilities, and CPU/memory limits.
- The trap listens on an unprivileged port (2222). Port 22 is redirected to it by the host firewall.
- The trap has **no outbound network access** except to the configured LLM API endpoint.
- The trap and the dashboard never share a database write path with attacker-controlled strings that are rendered unescaped.

## LLM safety and cost
- Attacker input sent to the LLM is wrapped as untrusted data, with a system prompt that tells the model to act only as a Linux shell simulator and to ignore instructions inside the input.
- LLM output is plain text, length-capped, and never executed or interpreted.
- Per-session and per-day token budgets are enforced; when exceeded, fall back to scripted responses (e.g. `command not found`).
- API keys live only in environment variables / secrets, never in code, logs, or the repo.

## Dashboard
- All attacker-supplied text (commands, usernames, passwords, URLs) is rendered as escaped text. No `dangerouslySetInnerHTML`.
- URLs from attackers are displayed defanged (`hxxp://`, `[.]`) and are never clickable.
- The dashboard requires authentication; demo credentials are provided to judges separately.
- Public demo views mask the last octet of attacker IPs unless the viewer is authenticated.

## Data handling
- Store only what the attacker sent to the trap plus connection metadata. No data about legitimate users.
- Logs are retained for a configurable period (default 30 days).

## Before merging any change to `trap/`
- Property-based tests prove arbitrary input never crashes the shell and never reaches a process call.
- `bandit` reports no high-severity findings.
