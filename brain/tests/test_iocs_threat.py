"""Property tests for IOC defanging and threat level (Requirements 8.6, 9.5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from brain.analysis.threat import compute_threat_level
from brain.iocs import defang, extract_url_iocs
from brain.models import Event, Severity

_NOW = datetime(2024, 1, 1, tzinfo=UTC)

_urls = st.builds(
    lambda scheme, host, path: f"{scheme}://{host}{path}",
    st.sampled_from(["http", "https", "HTTP", "Https"]),
    st.from_regex(r"[a-z0-9]{1,8}(\.[a-z0-9]{1,8}){0,3}", fullmatch=True),
    st.from_regex(r"(/[a-zA-Z0-9._-]{0,8}){0,3}", fullmatch=True),
)
_noise = st.text(alphabet="abc xyz.;|-", max_size=10)


def _event(kind: str, payload: dict[str, object]) -> Event:
    return Event(
        session_id="s",
        timestamp=_NOW,
        kind=kind,
        payload=json.dumps(payload),
        generated_by="scripted",
    )


def _is_defanged(value: str) -> bool:
    lowered = value.lower()
    return (
        "http://" not in lowered
        and "https://" not in lowered
        and "." not in value.replace("[.]", "")
    )


@given(
    st.lists(_urls, max_size=5),
    st.lists(st.tuples(_noise, _urls, _noise), max_size=5),
)
def test_every_returned_ioc_is_defanged(
    downloads: list[str], commands: list[tuple[str, str, str]]
) -> None:
    """**Validates: Requirements 8.6**"""
    events = [_event("download_attempt", {"url": u}) for u in downloads]
    events += [_event("command", {"command": f"{a} {u} {b}"}) for a, u, b in commands]
    for url in extract_url_iocs(events):
        assert _is_defanged(defang(url))


_severity = st.sampled_from(list(Severity))
_sevs = st.lists(_severity, max_size=20)
_attempts = st.integers(min_value=0, max_value=1000)


def test_threat_level_zero_when_empty() -> None:
    """**Validates: Requirements 9.5**"""
    assert compute_threat_level([], 0) == 0
    assert compute_threat_level([], 500) == 0


@given(_sevs, _attempts)
def test_threat_level_in_range(sevs: list[Severity], attempts: int) -> None:
    """**Validates: Requirements 9.5**"""
    assert 0 <= compute_threat_level(sevs, attempts) <= 10


@given(_sevs, _attempts)
def test_threat_level_at_least_7_with_class_5(sevs: list[Severity], attempts: int) -> None:
    """**Validates: Requirements 9.5**"""
    assert compute_threat_level([*sevs, Severity.CLASS_5], attempts) >= 7


@given(_sevs, _attempts, _severity)
def test_threat_level_monotonic_adding_session(
    sevs: list[Severity], attempts: int, extra: Severity
) -> None:
    """**Validates: Requirements 9.5**"""
    assert compute_threat_level([*sevs, extra], attempts) >= compute_threat_level(sevs, attempts)


@given(_sevs, _attempts, st.integers(min_value=0, max_value=1000))
def test_threat_level_monotonic_in_attempts(sevs: list[Severity], attempts: int, more: int) -> None:
    """**Validates: Requirements 9.5**"""
    assert compute_threat_level(sevs, attempts + more) >= compute_threat_level(sevs, attempts)
