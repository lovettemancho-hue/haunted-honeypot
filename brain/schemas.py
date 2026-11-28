"""Pydantic response models for the Brain API.

Attacker-supplied strings are returned as plain JSON strings with no HTML,
Markdown or template rendering (Requirement 8.5). IOC values are defanged
here, in the schema layer (Requirement 8.6): pass *raw* IOCs in; the models
defang them on construction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from brain.iocs import defang
from brain.models import Severity


class SeverityInfo(BaseModel):
    """Severity as display text plus a plain-language meaning (Requirement 5.4)."""

    label: str
    description: str

    @classmethod
    def from_severity(cls, severity: Severity) -> SeverityInfo:
        return cls(label=severity.label, description=severity.description)


class PasswordCount(BaseModel):
    password: str
    count: int


class StatsOut(BaseModel):
    attempts: int
    unique_ips: int
    captured: int
    longest_session_seconds: int
    threat_level: int
    top_passwords: list[PasswordCount]
    technique_counts: dict[str, int]


class SessionListItem(BaseModel):
    id: str
    src_ip: str
    src_port: int
    username: str | None
    started_at: datetime
    ended_at: datetime | None
    severity: SeverityInfo
    open: bool
    techniques: list[str]
    reviewed: bool = False


class TechniqueOut(BaseModel):
    attack_id: str
    name: str
    evidence_event_id: int


class EventOut(BaseModel):
    id: int
    timestamp: datetime
    kind: str
    payload: dict[str, Any]
    generated_by: str


class SessionDetail(BaseModel):
    id: str
    src_ip: str
    src_port: int
    username: str | None
    password: str | None
    client_version: str
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    severity: SeverityInfo
    open: bool
    events: list[EventOut]
    techniques: list[TechniqueOut]
    lab_note: str | None
    iocs: list[str]
    reviewed: bool = False

    @field_validator("iocs")
    @classmethod
    def _defang_iocs(cls, value: list[str]) -> list[str]:
        return [defang(item) for item in value]


class SessionSummary(BaseModel):
    """Counts for the tape filters. ``by_severity`` ignores the severity filter
    and ``by_technique`` ignores the technique filter, so each filter shows how
    many tapes picking it would give."""

    total: int
    unreviewed: int
    by_severity: dict[str, int]
    by_technique: dict[str, int]
    first_seen: datetime | None
    last_seen: datetime | None


class ReviewIn(BaseModel):
    reviewed: bool


class BulkReviewIn(BaseModel):
    ids: list[str] = Field(max_length=500)
    reviewed: bool


class ReviewOut(BaseModel):
    updated: int
    reviewed: bool


class ContainmentRuleOut(BaseModel):
    id: str
    kind: str
    title: str
    description: str
    content: str
    evidence_sessions: list[str]
