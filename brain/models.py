"""SQLModel tables and the Severity enum for the Brain.

Portable SQL only: event payloads are stored as JSON-encoded text.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


class Severity(StrEnum):
    """Three-tier session severity (shown as Class 1 / Class 3 / Class 5)."""

    CLASS_1 = "CLASS_1"
    CLASS_3 = "CLASS_3"
    CLASS_5 = "CLASS_5"

    @property
    def label(self) -> str:
        """Display text: "Class 1", "Class 3" or "Class 5"."""
        return _LABELS[self]

    @property
    def description(self) -> str:
        """Plain-language meaning of this severity."""
        return _DESCRIPTIONS[self]


_LABELS: dict[Severity, str] = {
    Severity.CLASS_1: "Class 1",
    Severity.CLASS_3: "Class 3",
    Severity.CLASS_5: "Class 5",
}

_DESCRIPTIONS: dict[Severity, str] = {
    Severity.CLASS_1: (
        "Low: the specimen only tried to guess logins and never got in."
    ),
    Severity.CLASS_3: (
        "Medium: the specimen logged in and looked around, "
        "but did not try to install, persist or mine."
    ),
    Severity.CLASS_5: (
        "High: the specimen logged in and tried to download tools, "
        "persist, mine cryptocurrency or add its own SSH key."
    ),
}


class Session(SQLModel, table=True):
    id: str = Field(primary_key=True)
    src_ip: str
    src_port: int
    username: str | None = None
    password: str | None = None
    client_version: str
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id", index=True)
    timestamp: datetime
    kind: str
    payload: str
    generated_by: str


class Technique(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="session.id", index=True)
    attack_id: str
    name: str
    evidence_event_id: int = Field(foreign_key="event.id")


class LabNote(SQLModel, table=True):
    session_id: str = Field(primary_key=True, foreign_key="session.id")
    text: str
    generated_by: str
    created_at: datetime


class IngestOffset(SQLModel, table=True):
    file_name: str = Field(primary_key=True)
    offset: int
