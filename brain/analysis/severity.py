"""Pure severity classification from login outcome and ATT&CK technique ids."""

from __future__ import annotations

from collections.abc import Iterable

from brain.models import Severity

CLASS_5_TECHNIQUES: frozenset[str] = frozenset({"T1105", "T1053.003", "T1496", "T1098.004"})


def classify_severity(has_successful_login: bool, attack_ids: Iterable[str]) -> Severity:
    """Return Class_1 without a successful login, Class_5 if any high-impact
    technique is present, otherwise Class_3. T1070.004 does not affect the result."""
    if not has_successful_login:
        return Severity.CLASS_1
    if CLASS_5_TECHNIQUES.intersection(attack_ids):
        return Severity.CLASS_5
    return Severity.CLASS_3
