"""Tests for severity classification (Requirement 5) and fixture sessions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from brain.analysis.attack_map import map_techniques
from brain.analysis.severity import classify_severity
from brain.ingest.reader import read_new_events
from brain.models import Event, Severity

FIXTURES_DIR = Path(__file__).parent / "fixtures"

ALL_IDS = [
    "T1110",
    "T1078",
    "T1082",
    "T1105",
    "T1059.004",
    "T1053.003",
    "T1496",
    "T1070.004",
    "T1098.004",
]
CLASS_5_IDS = frozenset({"T1105", "T1053.003", "T1496", "T1098.004"})

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _event(kind: str, payload: dict[str, object], n: int = 0) -> Event:
    return Event(
        id=n,
        session_id="s1",
        timestamp=_T0,
        kind=kind,
        payload=json.dumps(payload),
        generated_by="scripted",
    )


def _classify_events(events: list[Event]) -> Severity:
    hits = map_techniques(events)
    has_login = any(
        e.kind == "login_attempt" and json.loads(e.payload).get("success") is True
        for e in events
    )
    return classify_severity(has_login, frozenset(h.attack_id for h in hits))


def _load_fixture(name: str) -> list[Event]:
    result = read_new_events((FIXTURES_DIR / name).read_bytes(), 0)
    events = [p.event for p in result.parsed_lines if p.event is not None]
    assert len(events) == len(result.parsed_lines)
    return events


def _expected(has_login: bool, ids: frozenset[str]) -> Severity:
    if not has_login:
        return Severity.CLASS_1
    if ids & CLASS_5_IDS:
        return Severity.CLASS_5
    return Severity.CLASS_3


@given(
    st.booleans(),
    st.frozensets(st.sampled_from(ALL_IDS + ["T9999", ""])),
)
def test_property_9_severity_matches_decision_table(has_login: bool, ids: frozenset[str]) -> None:
    """Feature: brain, Property 9: severity matches the decision table.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.5**
    """
    result = classify_severity(has_login, ids)
    assert result == _expected(has_login, ids)
    assert classify_severity(has_login, ids) == result


# One example per technique rule (Requirement 4).
_TECHNIQUE_EXAMPLES: list[tuple[str, list[tuple[str, dict[str, object]]]]] = [
    (
        "T1110",
        [
            ("login_attempt", {"username": "a", "password": "b", "success": False}),
            ("login_attempt", {"username": "a", "password": "c", "success": False}),
        ],
    ),
    ("T1078", [("login_attempt", {"username": "a", "password": "b", "success": True})]),
    ("T1082", [("command", {"command": "uname -a"})]),
    ("T1105", [("download_attempt", {"url": "http://x.example/a.sh"})]),
    ("T1059.004", [("command", {"command": "ls -la"})]),
    ("T1053.003", [("command", {"command": "crontab -l"})]),
    ("T1496", [("command", {"command": "./xmrig -o pool.example:3333"})]),
    ("T1070.004", [("command", {"command": "history -c"})]),
    ("T1098.004", [("command", {"command": "echo k >> ~/.ssh/authorized_keys"})]),
]


@pytest.mark.parametrize(("attack_id", "specs"), _TECHNIQUE_EXAMPLES)
def test_each_technique_rule_example(
    attack_id: str, specs: list[tuple[str, dict[str, object]]]
) -> None:
    events = [_event(k, p, i) for i, (k, p) in enumerate(specs)]
    assert attack_id in {h.attack_id for h in map_techniques(events)}


@pytest.mark.parametrize("attack_id", ALL_IDS)
def test_severity_with_single_technique_after_login(attack_id: str) -> None:
    expected = Severity.CLASS_5 if attack_id in CLASS_5_IDS else Severity.CLASS_3
    assert classify_severity(True, frozenset({attack_id})) == expected
    assert classify_severity(False, frozenset({attack_id})) == Severity.CLASS_1


def test_t1070_004_alone_is_class_3() -> None:
    assert classify_severity(True, frozenset({"T1070.004"})) == Severity.CLASS_3


def test_fixture_class1_session() -> None:
    assert _classify_events(_load_fixture("class1_session.jsonl")) == Severity.CLASS_1


def test_fixture_class3_session() -> None:
    assert _classify_events(_load_fixture("class3_session.jsonl")) == Severity.CLASS_3


def test_fixture_class5_session() -> None:
    assert _classify_events(_load_fixture("class5_session.jsonl")) == Severity.CLASS_5
