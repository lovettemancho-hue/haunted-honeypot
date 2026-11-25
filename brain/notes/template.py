"""Pure Template_Note builder (fallback when no LLM note is available)."""

from __future__ import annotations

from dataclasses import dataclass

from brain.models import Severity

MAX_NOTE_CHARS = 2000


@dataclass(frozen=True)
class SessionSummary:
    """Facts about one Session that a Lab_Note must state."""

    src_ip: str
    login_succeeded: bool
    command_count: int
    attack_ids: tuple[str, ...]
    severity: Severity


def build_template_note(summary: SessionSummary) -> str:
    """Render a plain-text note stating IP, login outcome, command count,
    every attack_id and the severity. Capped at 2000 characters."""
    if summary.login_succeeded:
        login = "The specimen logged in successfully."
    else:
        login = "The specimen tried to log in but never got in."
    commands = f"Commands run: {summary.command_count}."
    if summary.attack_ids:
        techniques = "Techniques detected: " + ", ".join(summary.attack_ids) + "."
    else:
        techniques = "Techniques detected: none."
    severity = f"Severity: {summary.severity.label}. {summary.severity.description}"
    text = (
        f"Specimen {summary.src_ip} connected to the trap. "
        f"{login} {commands} {techniques} {severity}"
    )
    return text[:MAX_NOTE_CHARS]
