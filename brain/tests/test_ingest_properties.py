"""Property tests for session folding and attacker-string storage (Properties 4 and 5)."""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlmodel import col, select

from brain.config import Config
from brain.db import create_db_and_tables, make_engine, session_scope
from brain.ingest.ingestor import run_ingest_cycle
from brain.models import Event
from brain.models import Session as SessionRow

SID = "sess-1"
BASE = datetime(2025, 1, 1, tzinfo=UTC)

# Any unicode except lone surrogates (not encodable as UTF-8 in a log file).
# Includes NUL, quotes, SQL metacharacters and non-ASCII text.
_text = st.text(alphabet=st.characters(exclude_categories=["Cs"]), max_size=40)
_sql_text = st.sampled_from(
    ["'; DROP TABLE session; --", '" OR "1"="1', "a\x00b", "%_\\", "💀\u202e", "", "\n\r\t"]
)
_attacker_text = st.one_of(_text, _sql_text)


def _payload(kind: str, a: str, b: str) -> dict[str, Any]:
    if kind == "session_start":
        return {"src_ip": "203.0.113.9", "src_port": 4444, "client_version": "SSH-2.0-x"}
    if kind == "login_attempt":
        return {"username": a, "password": b, "accepted": True}
    if kind == "session_end":
        return {"reason": a}
    return {"command": a}


_kinds = st.sampled_from(["session_start", "login_attempt", "command", "session_end"])
_sequences = st.lists(st.tuples(_kinds, _text, _text), max_size=15)


def _ingest(lines: list[dict[str, Any]]) -> tuple[list[Event], SessionRow | None]:
    """Write lines as a Session_Log, run one Ingest_Cycle, return stored rows."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        log_dir = root / "logs"
        log_dir.mkdir()
        body = "".join(json.dumps(line) + "\n" for line in lines)
        (log_dir / f"{SID}.jsonl").write_bytes(body.encode("utf-8"))
        engine = make_engine(root / "brain.db")
        try:
            create_db_and_tables(engine)
            config = Config(
                log_dir=log_dir, api_token="t", database_path=root / "brain.db"
            )
            asyncio.run(run_ingest_cycle(config, engine))
            with session_scope(engine) as db:
                events = list(
                    db.exec(
                        select(Event)
                        .where(Event.session_id == SID)
                        .order_by(col(Event.id))
                    ).all()
                )
                session = db.get(SessionRow, SID)
                if session is not None:
                    db.expunge(session)
                for event in events:
                    db.expunge(event)
        finally:
            engine.dispose()
    return events, session


def _line(index: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": SID,
        "timestamp": (BASE + timedelta(seconds=index)).isoformat(),
        "kind": kind,
        "payload": payload,
        "generated_by": "scripted",
    }


@settings(max_examples=40, deadline=None)
@given(_sequences)
def test_session_folding_complete_and_last_writer(
    seq: list[tuple[str, str, str]],
) -> None:
    """**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**"""
    lines = [_line(i, k, _payload(k, a, b)) for i, (k, a, b) in enumerate(seq)]
    events, session = _ingest(lines)

    if not seq:
        assert events == []
        assert session is None
        return

    assert len(events) == len(seq)
    assert session is not None

    logins = [(a, b) for k, a, b in seq if k == "login_attempt"]
    if logins:
        assert (session.username, session.password) == logins[-1]
    else:
        assert session.username is None
        assert session.password is None

    ends = [(i, a) for i, (k, a, _b) in enumerate(seq) if k == "session_end"]
    if ends:
        last_index, reason = ends[-1]
        assert session.ended_at is not None
        assert session.ended_at.replace(tzinfo=UTC) == BASE + timedelta(seconds=last_index)
        assert session.end_reason == reason
    else:
        assert session.ended_at is None
        assert session.end_reason is None
    # Open state is defined as "no session_end seen" (API: open = ended_at is None).
    assert (session.ended_at is None) == (not ends)


@settings(max_examples=40, deadline=None)
@given(_attacker_text, _attacker_text, _attacker_text, _attacker_text)
def test_attacker_strings_survive_storage_unmodified(
    command: str, username: str, password: str, url: str
) -> None:
    """**Validates: Requirements 3.7**"""
    lines = [
        _line(0, "login_attempt", {"username": username, "password": password}),
        _line(1, "command", {"command": command}),
        _line(2, "download_attempt", {"url": url}),
    ]
    events, session = _ingest(lines)

    assert len(events) == 3
    assert session is not None
    assert session.username == username
    assert session.password == password
    payloads = [json.loads(e.payload) for e in events]
    assert payloads[0] == {"username": username, "password": password}
    assert payloads[1] == {"command": command}
    assert payloads[2] == {"url": url}
