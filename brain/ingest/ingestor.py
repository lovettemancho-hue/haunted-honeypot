"""Ingest_Cycle orchestration: Session_Logs -> Sessions, Events, Techniques.

Each ``*.jsonl`` file is read read-only from its stored offset. Events, the
Session fields folded from them, the new offset and the re-computed Technique
rows are all written in a single transaction per file, so a crash can never
leave a file half-ingested. All queries use the SQLModel expression API
(parameterized); attacker-supplied strings are stored unmodified.

Hook point for note generation (task 5.4): pass ``after_cycle`` to
``run_ingest_cycle`` / ``ingest_loop``. It is awaited once per cycle with the
ids of every Session touched in that cycle (possibly none); its exceptions are logged and never
break ingestion.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlmodel import Session as DBSession
from sqlmodel import col, select

from brain.analysis.attack_map import map_techniques
from brain.analysis.severity import classify_severity
from brain.config import Config
from brain.db import session_scope
from brain.ingest.reader import read_new_events
from brain.models import Event, IngestOffset, Technique
from brain.models import Session as SessionRow

logger = logging.getLogger(__name__)

# Called once per cycle with the ids of Sessions touched in that cycle.
AfterCycleHook = Callable[[Config, Engine, Sequence[str]], Awaitable[None]]

_UNKNOWN = "unknown"


def _payload_dict(event: Event) -> dict[str, object]:
    try:
        data = json.loads(event.payload)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _new_session(event: Event, payload: dict[str, object]) -> SessionRow:
    """Create a Session from an Event (session_start, or any Event for an unknown id)."""
    return SessionRow(
        id=event.session_id,
        src_ip=_opt_str(payload.get("src_ip")) or _UNKNOWN,
        src_port=_int_or_zero(payload.get("src_port")),
        client_version=_opt_str(payload.get("client_version")) or _UNKNOWN,
        started_at=event.timestamp,
    )


def _fold_event(session: SessionRow, event: Event, payload: dict[str, object]) -> None:
    """Apply one Event to its Session row (pure field updates)."""
    if event.kind == "session_start":
        session.src_ip = _opt_str(payload.get("src_ip")) or session.src_ip
        port = _int_or_zero(payload.get("src_port"))
        session.src_port = port or session.src_port
        session.client_version = _opt_str(payload.get("client_version")) or session.client_version
        session.started_at = event.timestamp
    elif event.kind == "login_attempt":
        session.username = _opt_str(payload.get("username"))
        session.password = _opt_str(payload.get("password"))
    elif event.kind == "session_end":
        session.ended_at = event.timestamp
        session.end_reason = _opt_str(payload.get("reason"))


def _reset_sessions_for_reingest(db: DBSession, session_ids: set[str]) -> None:
    """Drop stored Events/Techniques of these Sessions and clear folded fields."""
    for sid in session_ids:
        db.execute(delete(Technique).where(col(Technique.session_id) == sid))
        db.execute(delete(Event).where(col(Event.session_id) == sid))
        existing = db.get(SessionRow, sid)
        if existing is not None:
            existing.username = None
            existing.password = None
            existing.ended_at = None
            existing.end_reason = None
            db.add(existing)
    db.flush()


def _recompute_analysis(db: DBSession, session_id: str) -> None:
    """Re-run ATT&CK mapping + severity and replace the Session's Technique rows."""
    events = list(
        db.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(col(Event.timestamp), col(Event.id))
        ).all()
    )
    hits = map_techniques(events)
    db.execute(delete(Technique).where(col(Technique.session_id) == session_id))
    for hit in hits:
        evidence_id = events[hit.evidence_event_index].id  # assigned by the flush
        if evidence_id is None:  # pragma: no cover - events were loaded from the DB
            continue
        db.add(
            Technique(
                session_id=session_id,
                attack_id=hit.attack_id,
                name=hit.name,
                evidence_event_id=evidence_id,
            )
        )
    attack_ids = frozenset(h.attack_id for h in hits)
    severity = classify_severity("T1078" in attack_ids, attack_ids)
    logger.debug("session %s: %d techniques, %s", session_id, len(hits), severity.value)


def _read_file(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read()


def _ingest_file(path: Path, engine: Engine) -> list[str]:
    """Ingest one Session_Log in one transaction; return touched Session ids."""
    name = path.name
    content = _read_file(path)
    size = len(content)
    touched: dict[str, None] = {}  # insertion-ordered set

    with session_scope(engine) as db:
        stored = db.get(IngestOffset, name)
        offset = stored.offset if stored is not None else 0
        truncated = size < offset
        if truncated:
            logger.warning("%s is smaller than its stored offset; re-ingesting from 0", name)
            offset = 0

        result = read_new_events(content, offset, content.count(b"\n", 0, offset) + 1)
        events: list[Event] = []
        for parsed in result.parsed_lines:
            if parsed.event is None:
                logger.warning("skipping %s:%d: %s", name, parsed.line_number, parsed.raw_error)
            else:
                events.append(parsed.event)

        if truncated:
            # Events are not tagged with their file, so discard the Sessions
            # named in the file now and the one matching the file stem.
            stale = {e.session_id for e in events} | {path.stem}
            _reset_sessions_for_reingest(db, stale)

        sessions: dict[str, SessionRow] = {}
        for event in events:
            payload = _payload_dict(event)
            session = sessions.get(event.session_id) or db.get(SessionRow, event.session_id)
            if session is None:
                session = _new_session(event, payload)
                logger.info(
                    "creating session %s from %s event in %s", event.session_id, event.kind, name
                )
            sessions[event.session_id] = session
            _fold_event(session, event, payload)
            db.add(session)
            db.add(event)
            touched[event.session_id] = None
        db.flush()

        for sid in touched:
            _recompute_analysis(db, sid)

        if stored is None:
            db.add(IngestOffset(file_name=name, offset=result.new_offset))
        elif stored.offset != result.new_offset:
            stored.offset = result.new_offset
            db.add(stored)

    return list(touched)


async def run_ingest_cycle(
    config: Config,
    engine: Engine,
    after_cycle: AfterCycleHook | None = None,
) -> list[str]:
    """One Ingest_Cycle over every ``*.jsonl`` file in ``config.log_dir``.

    A failure in one file is logged and does not stop the other files.
    Returns the ids of Sessions touched in this cycle.
    """
    files = await asyncio.to_thread(lambda: sorted(config.log_dir.glob("*.jsonl")))
    touched: dict[str, None] = {}
    for path in files:
        try:
            for sid in await asyncio.to_thread(_ingest_file, path, engine):
                touched[sid] = None
        except Exception:
            logger.exception("failed to ingest %s", path.name)

    if after_cycle is not None:  # called even when nothing was touched (note backfill)
        try:
            await after_cycle(config, engine, list(touched))
        except Exception:
            logger.exception("after-cycle hook failed")
    return list(touched)


async def ingest_loop(
    config: Config,
    engine: Engine,
    after_cycle: AfterCycleHook | None = None,
) -> None:
    """Run a cycle immediately, then every ``ingest_interval_seconds``, forever."""
    while True:
        try:
            await run_ingest_cycle(config, engine, after_cycle)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ingest cycle failed")
        await asyncio.sleep(config.ingest_interval_seconds)


__all__ = ["AfterCycleHook", "ingest_loop", "run_ingest_cycle"]
