"""Overview statistics for ``GET /api/stats`` (Requirement 9).

Severity and threat level are computed on read from login events and
Technique rows. Queries use the portable SQLModel expression API.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlmodel import Session as DBSession
from sqlmodel import select

from brain.analysis.severity import classify_severity
from brain.analysis.threat import compute_threat_level
from brain.models import Event, Severity, Technique
from brain.models import Session as SessionRow

_TOP_PASSWORDS_LIMIT = 10


def _payload(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def compute_stats(session: DBSession) -> dict[str, Any]:
    """Return the stats document; zero counts and empty lists when no data."""
    sessions = list(session.exec(select(SessionRow)).all())

    attempts = 0
    passwords: Counter[str] = Counter()
    captured_ids: set[str] = set()
    login_rows = session.exec(
        select(Event.session_id, Event.payload).where(Event.kind == "login_attempt")
    ).all()
    for session_id, raw in login_rows:
        attempts += 1
        data = _payload(raw)
        password = data.get("password")
        if isinstance(password, str):
            passwords[password] += 1
        if data.get("success") is True:
            captured_ids.add(session_id)

    technique_rows = session.exec(select(Technique.session_id, Technique.attack_id)).all()
    ids_by_session: dict[str, set[str]] = {}
    for session_id, attack_id in technique_rows:
        ids_by_session.setdefault(session_id, set()).add(attack_id)
    technique_counts = Counter(a for ids in ids_by_session.values() for a in ids)

    severities: list[Severity] = [
        classify_severity(s.id in captured_ids, ids_by_session.get(s.id, set())) for s in sessions
    ]

    durations = [
        int((s.ended_at - s.started_at).total_seconds()) for s in sessions if s.ended_at is not None
    ]
    longest = max(0, max(durations)) if durations else 0

    top = sorted(passwords.items(), key=lambda item: (-item[1], item[0]))[:_TOP_PASSWORDS_LIMIT]

    return {
        "attempts": attempts,
        "unique_ips": len({s.src_ip for s in sessions}),
        "captured": sum(1 for s in sessions if s.id in captured_ids),
        "longest_session_seconds": longest,
        "threat_level": compute_threat_level(severities, attempts),
        "top_passwords": [{"password": p, "count": c} for p, c in top],
        "technique_counts": dict(sorted(technique_counts.items())),
    }
