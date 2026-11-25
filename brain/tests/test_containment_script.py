"""Property tests for script safety in brain.containment.script."""

from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from brain.analysis.attack_map import MINING_PORTS
from brain.containment.rules import (
    KIND_IP_DROP,
    ContainmentRule,
    SessionForContainment,
    build_rules,
)
from brain.containment.script import render_script
from brain.containment.validate import validate_ip, validate_port
from brain.models import Severity

_PAYLOADS = [
    "1.2.3.4; rm -rf /",
    "$(reboot)",
    "`id`",
    "1.2.3.4\niptables -F",
    "fe80::1%eth0",
    "999.1.1.1",
    "",
    "203.0.113.5 -j ACCEPT",
]

_ip_text = st.one_of(
    st.sampled_from(["203.0.113.5", "198.51.100.1", "2001:db8::1", *_PAYLOADS]),
    st.ip_addresses().map(str),
    st.text(max_size=30),
)

_sessions = st.lists(
    st.builds(
        SessionForContainment,
        session_id=st.text(alphabet="abcdef0123456789", min_size=1, max_size=8),
        src_ip=_ip_text,
        severity=st.sampled_from(list(Severity)),
        had_successful_login=st.booleans(),
        failed_login_count=st.integers(0, 5),
        mining_ports=st.frozensets(
            st.one_of(
                st.sampled_from(sorted(MINING_PORTS)),
                st.integers(-10, 70000),
            ),
            max_size=4,
        ),
    ),
    max_size=10,
    unique_by=lambda s: s.session_id,
)

_IP_LINE = re.compile(r"^(?:ip6tables|iptables) -A INPUT -s (\S+) -j DROP$", re.MULTILINE)
_PORT_LINE = re.compile(r"^iptables -A OUTPUT -p tcp --dport (\S+) -j DROP$", re.MULTILINE)
_SAFE_LINE = re.compile(r"^[\x20-\x7e]*$")


@given(_sessions)
def test_property_17_script_byte_identical(sessions: list[SessionForContainment]) -> None:
    """Property 17: rendering twice gives byte-identical script text.

    **Validates: Requirements 7.11**
    """
    first = render_script(build_rules(sessions))
    second = render_script(build_rules(list(reversed(sessions))))
    assert first == second
    assert first.encode() == render_script(build_rules(sessions)).encode()


@given(_sessions)
def test_property_18_only_validated_values_reach_script(
    sessions: list[SessionForContainment],
) -> None:
    """Property 18: only validated IPs/ports appear; other attacker strings never do.

    **Validates: Requirements 7.7, 7.9, 13.5**
    """
    rules = build_rules(sessions)
    script = render_script(rules)

    for payload in _PAYLOADS:
        if payload and validate_ip(payload) is None:
            assert payload not in script

    ip_ok = {
        s.src_ip
        for s in sessions
        if s.severity in (Severity.CLASS_3, Severity.CLASS_5) and validate_ip(s.src_ip)
    }
    assert set(_IP_LINE.findall(script)) == ip_ok

    port_ok = {
        p
        for s in sessions
        for p in s.mining_ports
        if validate_port(p) is not None and p in MINING_PORTS
    }
    assert {int(p) for p in _PORT_LINE.findall(script)} == port_ok


@given(_sessions)
def test_every_ip_and_port_in_script_passes_validation(
    sessions: list[SessionForContainment],
) -> None:
    """Every IP and port found in a generated script passes validation.

    **Validates: Requirements 7.7, 7.9**
    """
    script = render_script(build_rules(sessions))
    for ip in _IP_LINE.findall(script):
        assert validate_ip(ip) == ip
    for port in _PORT_LINE.findall(script):
        assert validate_port(port) is not None
    # Every iptables line is one of the two validated shapes.
    for line in script.splitlines():
        if line.startswith(("iptables", "ip6tables")):
            assert _IP_LINE.fullmatch(line) or _PORT_LINE.fullmatch(line)


@given(_sessions)
def test_session_ids_and_non_ascii_never_in_script(
    sessions: list[SessionForContainment],
) -> None:
    """Script is printable ASCII and carries no session identifiers.

    **Validates: Requirements 13.5**
    """
    script = render_script(build_rules(sessions))
    assert all(_SAFE_LINE.match(line) for line in script.splitlines())


_title = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
    min_size=1,
    max_size=60,
)

_rules = st.lists(
    st.builds(
        ContainmentRule,
        id=st.text(alphabet="abc-", min_size=1, max_size=8),
        kind=st.just(KIND_IP_DROP),
        title=_title,
        description=_title,
        content=st.just("# noop"),
        evidence_sessions=st.just(("a",)),
    ),
    max_size=8,
)


@given(_rules)
def test_property_19_script_contains_every_rule_title(rules: list[ContainmentRule]) -> None:
    """Property 19: the script contains every rule's title.

    **Validates: Requirements 7.8**
    """
    script = render_script(rules)
    for rule in rules:
        assert rule.title in script


def test_property_19_titles_of_built_rules() -> None:
    """Built rules' titles all appear in the rendered script.

    **Validates: Requirements 7.8**
    """
    sessions = [
        SessionForContainment("a", "203.0.113.5", Severity.CLASS_5, True, 3, frozenset({3333})),
    ]
    rules = build_rules(sessions)
    script = render_script(rules)
    assert len(rules) == 4
    assert all(r.title in script for r in rules)
