"""Pure threat-level computation (Lab voltage, 0..10)."""

from __future__ import annotations

from collections.abc import Sequence

from brain.models import Severity


def compute_threat_level(severities: Sequence[Severity], total_attempts: int) -> int:
    """Return an integer in [0, 10] from session severities and login volume.

    0 with no sessions; at least 7 when any session is Class_5; non-decreasing
    as sessions or attempts are added.
    """
    if not severities:
        return 0

    class5_count = sum(1 for s in severities if s == Severity.CLASS_5)
    class3_count = sum(1 for s in severities if s == Severity.CLASS_3)

    if class5_count >= 1:
        base = 7
        bonus = min(3, class5_count - 1)
    elif class3_count >= 1:
        base = 4
        bonus = min(3, class3_count // 3)
    else:
        base = 1
        bonus = 0

    volume_bonus = min(1, max(0, total_attempts) // 50)
    return max(0, min(10, base + bonus + volume_bonus))
