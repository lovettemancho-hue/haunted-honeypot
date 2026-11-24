"""Unit tests for trap.auth.tracker.AttemptTracker."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from trap.auth import tracker as tracker_mod
from trap.auth.tracker import MAX_TRACKED_IPS, AttemptTracker


class _Clock:
    """Controllable replacement for the ``datetime`` name in the tracker module."""

    def __init__(self) -> None:
        self.current = datetime(2025, 1, 1, tzinfo=UTC)

    def now(self, tz: object = None) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr(tracker_mod, "datetime", c)
    return c


def test_should_accept_false_before_n_true_at_n(clock: _Clock) -> None:
    t = AttemptTracker()
    ip = "10.0.0.1"
    assert t.should_accept(ip, 3) is False
    for _ in range(2):
        t.record_attempt(ip)
    assert t.should_accept(ip, 3) is False
    t.record_attempt(ip)
    assert t.should_accept(ip, 3) is True


def test_attempts_are_per_ip(clock: _Clock) -> None:
    t = AttemptTracker()
    t.record_attempt("10.0.0.1")
    assert t.should_accept("10.0.0.2", 1) is False


def test_old_timestamps_pruned(clock: _Clock) -> None:
    t = AttemptTracker()
    ip = "10.0.0.1"
    t.record_attempt(ip)
    t.record_attempt(ip)
    clock.advance(timedelta(hours=1, seconds=1))
    assert t.should_accept(ip, 1) is False
    assert ip not in t._window  # empty entry removed


def test_partial_pruning_keeps_recent(clock: _Clock) -> None:
    t = AttemptTracker()
    ip = "10.0.0.1"
    t.record_attempt(ip)
    clock.advance(timedelta(minutes=40))
    t.record_attempt(ip)
    clock.advance(timedelta(minutes=30))  # first is now 70 min old
    assert t.should_accept(ip, 1) is True
    assert t.should_accept(ip, 2) is False
    assert len(t._window[ip]) == 1


def test_per_ip_cap(clock: _Clock) -> None:
    t = AttemptTracker(max_attempts_per_ip=5)
    ip = "10.0.0.1"
    for _ in range(50):
        t.record_attempt(ip)
        assert len(t._window[ip]) <= 5
    assert len(t._window[ip]) == 5


def test_ip_count_cap_and_lru_eviction(clock: _Clock) -> None:
    t = AttemptTracker(max_attempts_per_ip=2)
    for i in range(MAX_TRACKED_IPS):
        t.record_attempt(f"ip-{i}")
    assert len(t._window) == MAX_TRACKED_IPS
    # Touch the oldest so ip-1 becomes the least recently used.
    t.record_attempt("ip-0")
    t.record_attempt("new-ip")
    assert len(t._window) == MAX_TRACKED_IPS
    assert "ip-1" not in t._window
    assert "ip-0" in t._window
    assert "new-ip" in t._window


def test_concurrent_use_in_event_loop(clock: _Clock) -> None:
    t = AttemptTracker()
    ip = "10.0.0.9"

    async def worker() -> bool:
        t.record_attempt(ip)
        await asyncio.sleep(0)
        return t.should_accept(ip, 1)

    async def main() -> list[bool]:
        return list(await asyncio.gather(*(worker() for _ in range(20))))

    results = asyncio.run(main())
    assert all(results)
    assert t.should_accept(ip, 20) is True
    assert t.should_accept(ip, 21) is False
