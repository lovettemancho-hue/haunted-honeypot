"""Per-IP login attempt tracker with bounded memory."""

from __future__ import annotations

from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta

MAX_TRACKED_IPS: int = 10_000
WINDOW: timedelta = timedelta(hours=1)


class AttemptTracker:
    """Counts login attempts per source IP within a rolling one-hour window.

    Memory is bounded: at most ``MAX_TRACKED_IPS`` IPs are tracked (LRU
    eviction) and at most ``max_attempts_per_ip`` timestamps are kept per IP.
    """

    def __init__(self, max_attempts_per_ip: int = 101) -> None:
        self._window: OrderedDict[str, deque[datetime]] = OrderedDict()
        self._max_per_ip: int = max_attempts_per_ip

    def record_attempt(self, src_ip: str) -> None:
        """Record one attempt from src_ip; enforces both memory caps."""
        self._prune_ip(src_ip)
        if src_ip not in self._window:
            if len(self._window) >= MAX_TRACKED_IPS:
                self._window.popitem(last=False)
            self._window[src_ip] = deque()
        stamps = self._window[src_ip]
        while len(stamps) >= self._max_per_ip and stamps:
            stamps.popleft()
        stamps.append(datetime.now(UTC))
        self._move_to_end(src_ip)

    def should_accept(self, src_ip: str, n: int) -> bool:
        """Return True if attempt count from src_ip within the last hour >= n."""
        self._prune_ip(src_ip)
        return len(self._window.get(src_ip, deque())) >= n

    def _prune_ip(self, src_ip: str) -> None:
        """Remove timestamps older than 1 hour for src_ip; remove key if empty."""
        stamps = self._window.get(src_ip)
        if stamps is None:
            return
        cutoff = datetime.now(UTC) - WINDOW
        while stamps and stamps[0] < cutoff:
            stamps.popleft()
        if not stamps:
            del self._window[src_ip]

    def _move_to_end(self, src_ip: str) -> None:
        """Mark src_ip as most-recently-seen."""
        self._window.move_to_end(src_ip)
