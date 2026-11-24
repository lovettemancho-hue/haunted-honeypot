"""Unit tests for trap.models (Requirements 9.2)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from trap.models import Event, Session

REQUIRED_EVENT_FIELDS = {"session_id", "timestamp", "kind", "payload", "generated_by"}


def _make_session(**overrides: object) -> Session:
    kwargs: dict[str, object] = {
        "session_id": "abc123",
        "src_ip": "203.0.113.7",
        "src_port": 54321,
        "username": "root",
        "password": "toor",
        "client_version": "SSH-2.0-OpenSSH_9.6",
        "started_at": datetime(2024, 1, 15, 10, 23, 45, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    return Session(**kwargs)  # type: ignore[arg-type]


def test_event_asdict_contains_required_fields_with_correct_values() -> None:
    event = Event(
        session_id="abc123",
        timestamp="2024-01-15T10:23:45.123456Z",
        kind="command",
        payload={"command": "ls -la", "args": ["-la"]},
        generated_by="scripted",
    )

    data = asdict(event)

    assert set(data) == REQUIRED_EVENT_FIELDS
    assert data["session_id"] == "abc123"
    assert data["timestamp"] == "2024-01-15T10:23:45.123456Z"
    assert data["kind"] == "command"
    assert data["payload"] == {"command": "ls -la", "args": ["-la"]}
    assert data["generated_by"] == "scripted"


def test_event_asdict_is_json_serialisable() -> None:
    event = Event(
        session_id="s1",
        timestamp="2024-01-15T10:23:45.000000Z",
        kind="response",
        payload={"output": "hi"},
        generated_by="llm",
    )

    assert json.loads(json.dumps(asdict(event))) == asdict(event)


def test_session_ended_at_defaults_to_none() -> None:
    assert _make_session().ended_at is None


def test_session_ended_at_can_be_set() -> None:
    end = datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)

    assert _make_session(ended_at=end).ended_at == end
