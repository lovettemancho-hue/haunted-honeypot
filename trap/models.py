"""Data models shared across the trap: sessions, events and per-session context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from trap.config import Config
    from trap.ghost.filesystem import FakeFilesystem

EventKind = Literal[
    "login_attempt",
    "command",
    "response",
    "download_attempt",
    "session_start",
    "session_end",
]

SessionEndReason = Literal[
    "exit", "idle_timeout", "max_duration", "disconnect", "log_error"
]

GeneratedBy = Literal["scripted", "llm"]


@dataclass
class Session:
    """One attacker connection. ``started_at`` and ``ended_at`` are UTC."""

    session_id: str  # uuid4 hex
    src_ip: str
    src_port: int
    username: str
    password: str
    client_version: str
    started_at: datetime
    ended_at: datetime | None = None


@dataclass
class Event:
    """A single JSON Lines log record."""

    session_id: str
    timestamp: str  # ISO-8601 UTC, e.g. "2024-01-15T10:23:45.123456Z"
    kind: EventKind
    payload: dict[str, object]
    generated_by: GeneratedBy


@dataclass
class SessionContext:
    """All mutable per-session state, passed to command handlers and the LLM."""

    session: Session
    fs: FakeFilesystem
    history: list[str]
    config: Config
    # Basenames of files created by simulated wget/curl. Keyword-only so it can
    # keep a default while ``config`` (no default) stays a positional field.
    downloaded_files: set[str] = field(default_factory=set, kw_only=True)
    # Events raised by command handlers (e.g. ``download_attempt``). The shell
    # loop drains this list and writes each event to the session log.
    pending_events: list[Event] = field(default_factory=list, kw_only=True)
