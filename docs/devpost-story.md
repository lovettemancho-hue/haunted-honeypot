## Inspiration
Any server on the internet gets attacked by bots within minutes. Big companies have security teams to watch for this. Students, solo developers and small organisations don't, and the honeypots that exist mostly produce raw logs that nobody reads.

I'm studying cybersecurity, and I wanted a tool that does what an analyst does: let the attacker in safely, watch everything they do, explain it in plain language, and say exactly how to protect a real server from it. Kiroween's **Frankenstein** category fit: I stitched a fake SSH server, an LLM, MITRE ATT&CK, a rules engine and a horror-film dashboard into one creature.

## What it does
**Haunted Honeypot** pretends to be a forgotten, "decommissioned" municipal records server (`records-srv-09`). The caretaker has not been seen since 2013, and the lights still flicker in the vault.

- **The Trap** is a fake SSH server on port 22. It accepts the weak passwords bots love (`root` / `123456`) and records every keystroke. **Nothing the attacker types is ever executed.**
- **The Ghost Shell** answers from a fake filesystem, so `whoami`, `uname -a` and `cat /etc/passwd` look real. It can use Gemini to improvise replies to unusual commands, with a scripted fallback and a daily call limit.
- **The Brain** (FastAPI) reads the session logs, maps behaviour to **MITRE ATT&CK** techniques (T1110 brute force, T1105 tool download, T1496 crypto-mining and more) and rates each session **Class 1 / 3 / 5**. It then writes a plain-English **lab note** and pulls out **defanged IOCs** (`hxxp://198[.]51[.]100[.]77/xmrig`).
- **Containment** turns what the attackers did into a hardening checklist and **ready-to-run rules**, such as disabling password logins or blocking outbound mining port 3333. You can download them as a shell script. Private IPs are never blocked, and nothing is applied automatically.
- **The Dashboard** is a "Frankenstein Lab Cam" in React: Lab Monitor (lab voltage = threat level), Lab Tapes (replay an attack like a terminal recording) and Containment.

It's live on a Google Cloud VM. **Within the first hour, 9 different addresses made 34 login attempts**, trying passwords like `1qaz2wsx#`, `Admin.123456` and `Dell123`.

## How I built it
I built it with **Kiro**, spec-first:

- **Steering** (`.kiro/steering/`): `product.md` (the lab vocabulary: Specimen, Tape, Lab voltage, Containment), `tech.md` (stack and conventions), `security.md` (attacker input is data, never code; `yaml.safe_load`; escaped rendering; bearer-token API) and `design.md` (the Lab Cam colour and font tokens). Kiro followed these in every task.
- **Four specs** (`.kiro/specs/`): `trap-core`, `ghost-llm`, `brain` and `dashboard`. Each has requirements, a design and a task list. Kiro worked through **166 tasks** across them.
- **Agent hook** (`.kiro/hooks/`): every time a trap or test Python file is saved, Kiro runs `ruff`, `bandit` and `pytest`. Security mistakes in the part that faces attackers get caught the moment they're written.
- **Property-based testing**: Hypothesis in Python and fast-check in TypeScript. They throw thousands of random inputs at the code and check rules like "no attacker input ever crashes the shell or reaches `subprocess`/`eval`", "two attackers' sessions never leak into each other" and "severity always matches the decision table".
- About **500 automated tests**: 209 trap, 138 brain, 155 dashboard. Plus `ruff`, `mypy --strict` and `bandit` on the Python code.

**Stack:** Python (asyncssh, FastAPI, SQLModel, SQLite), React + TypeScript + Vite, Docker Compose and Caddy, on a Google Cloud e2-micro (free tier).

**Hardening the deployment:** the containers are read-only, drop all Linux capabilities and run on separate Docker networks, so the trap cannot reach the brain or the dashboard. The real admin SSH is hidden on another port that is reachable only through Google's IAP tunnel. The honeypot runs in its own GCP project to limit the blast radius.

## Challenges I ran into
- **Two halves that each passed their tests but broke together.** The brain sent severity as `"Class 5 — Critical"`, while the dashboard expected `"Class_5"`, so React crashed on real data. The fix was to save real API responses as **contract fixtures** and make the dashboard's tests run against them.
- **AI edits on Windows corrupted files.** One bulk edit turned every `i` into `m` and every newline into a NUL byte in `main.tsx`. Another turned `—` into `â€”`. I caught them with `git diff --stat` (a text file showing up as `Bin`) and added a steering rule so Kiro keeps files UTF-8 and never edits code through PowerShell.
- **Caddy crashed with no domain name.** An empty `DOMAIN` turned the site block into a global-options block. The fix was to default it to `:80`.
- **Port 22 belongs to the trap.** I had to move the real SSH daemon to a hidden port first without locking myself out. Docker's port mapping keeps the attacker's real IP, which the analysis depends on.
- **Python 3.14 was very new**, and some pinned packages had no wheels for it yet.

## Accomplishments I'm proud of
- Real attackers found it within minutes, and the brain labelled their behaviour with industry-standard ATT&CK IDs on its own.
- It doesn't stop at "here are your logs". It ends with **what to change on your real server**.
- A security tool that is also fun to watch.

## What I learned
- How to plan with specs: with requirements and tasks written down first, Kiro's output was consistent across a four-part system.
- Threat modelling a program whose whole job is to talk to attackers: input as data, isolation, least privilege.
- Contract testing between services, and why "all tests pass" can still mean broken.
- Docker networking, IAP tunnels and cloud firewalls in practice.

## What's next for Haunted Honeypot
- Threat-intel enrichment (AbuseIPDB / GreyNoise) for each specimen.
- More fake services (Telnet, HTTP admin panels) and a "fleet" mode for several traps feeding one brain.
- Weekly emailed lab reports for small teams.
