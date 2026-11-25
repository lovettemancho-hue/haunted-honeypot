"""Property tests for login-based ATT&CK techniques (T1110, T1078)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from brain.analysis.attack_map import map_techniques
from brain.models import Event

_TS = datetime(2024, 1, 1, tzinfo=UTC)


def _login(success: bool) -> Event:
    return Event(
        session_id="s",
        timestamp=_TS,
        kind="login_attempt",
        payload=json.dumps({"username": "root", "password": "x", "success": success}),
        generated_by="scripted",
    )


def _command(text: str) -> Event:
    return Event(
        session_id="s",
        timestamp=_TS,
        kind="command",
        payload=json.dumps({"command": text}),
        generated_by="scripted",
    )


_event_spec = st.one_of(
    st.sampled_from([True, False]).map(lambda s: ("login", s)),
    st.sampled_from(["ls", "pwd", "echo hi", ""]).map(lambda c: ("cmd", c)),
)


def _build(spec: list[tuple[str, object]]) -> list[Event]:
    return [_login(bool(v)) if k == "login" else _command(str(v)) for k, v in spec]


@given(st.lists(_event_spec, max_size=30))
def test_login_techniques_attached_iff_triggers_hold(
    spec: list[tuple[str, object]],
) -> None:
    """Feature: brain, Property 6: Login-based techniques are attached exactly
    when their trigger conditions hold.

    **Validates: Requirements 4.1, 4.2**
    """
    events = _build(spec)
    hits = {h.attack_id: h for h in map_techniques(events)}

    failed = [i for i, e in enumerate(events) if json.loads(e.payload).get("success") is False]
    ok = [i for i, e in enumerate(events) if json.loads(e.payload).get("success") is True]

    if len(failed) >= 2:
        assert "T1110" in hits
        assert hits["T1110"].evidence_event_index == failed[1]
    else:
        assert "T1110" not in hits

    if ok:
        assert "T1078" in hits
        assert hits["T1078"].evidence_event_index == ok[0]
    else:
        assert "T1078" not in hits
