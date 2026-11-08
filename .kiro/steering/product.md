---
inclusion: always
---

# Product: Haunted Honeypot

## One-line pitch
An AI-powered SSH honeypot that traps attackers inside a believable "haunted" fake server, then explains what they did in plain language and generates the fixes to protect real servers.

## The problem
- Any server on the public internet is attacked by bots within minutes.
- Small businesses, universities, NGOs and solo developers (especially in Africa and other under-resourced regions) cannot afford security teams or enterprise deception tools.
- Existing open-source honeypots (e.g. Cowrie) are hard to set up and produce raw logs nobody reads.

## Who it is for
- Primary: small organisations and solo developers with no security team.
- Secondary: students and educators learning real attacker behaviour.

## What it does
1. **The Trap** — a fake SSH server that accepts weak logins and records every keystroke. Nothing the attacker types is ever executed.
2. **The Ghost Shell** — answers common commands from a fake filesystem; unusual commands are answered by an LLM so the fake system stays believable and consistent within a session.
3. **The Brain** — stores sessions, writes plain-English "field notes", maps behaviour to MITRE ATT&CK techniques, and enriches attacker IPs with public threat intel.
4. **The Dashboard** — a "ghost hunter camcorder" themed web app: Live Feed, Footage (session replay), Containment (auto-generated hardening rules).

## Vocabulary (use consistently in UI copy)
| Real meaning | Product term |
|---|---|
| Attacker / IP | Entity |
| Attack session | Sighting / Tape |
| Session replay page | Footage |
| Severity (low/medium/high) | Class 1 / Class 3 / Class 5 |
| Generated fixes / blocklist | Containment |
| Overview page | Live Feed |

Spooky wording must never hide meaning: every themed label is paired with a plain-language description.

## Success criteria for the hackathon demo
- Real attack data captured from a live deployment, not fabricated.
- A judge can SSH into the trap themselves and watch their own session appear on the dashboard.
- One-command install (`docker compose up -d`).
- Every feature works end-to-end; no dead buttons in the demo path.

## Out of scope (for now)
- Protocols other than SSH (Telnet/HTTP may come later).
- Multi-tenant SaaS accounts and billing.
- Automatically applying firewall rules to the user's real servers (we only generate them).
