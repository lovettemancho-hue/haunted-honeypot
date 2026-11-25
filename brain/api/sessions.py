"""GET /api/sessions and GET /api/sessions/{id} (Requirement 10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session as DBSession
from sqlmodel import select

from brain.analysis.severity import classify_severity
from brain.api._common import (
    attack_ids_by_session,
    get_db,
    payload_dict,
    successful_login_ids,
)
from brain.iocs import extract_url_iocs
from brain.models import Event, LabNote, Technique
from brain.models import Session as SessionRow
from brain.schemas import (
    EventOut,
    SessionDetail,
    SessionListItem,
    SeverityInfo,
    TechniqueOut,
)

router = APIRouter()

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@router.get("/api/sessions", response_model=list[SessionListItem])
def list_sessions(
    db: Annotated[DBSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=0)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SessionListItem]:
    limit = min(limit, MAX_LIMIT)
    rows = db.exec(
        select(SessionRow)
        .order_by(SessionRow.started_at.desc(), SessionRow.id)  # type: ignore[attr-defined]
        .offset(offset)
        .limit(limit)
    ).all()
    ids = [r.id for r in rows]
    captured = successful_login_ids(db, ids)
    techniques = attack_ids_by_session(db, ids)
    items: list[SessionListItem] = []
    for row in rows:
        attack_ids = techniques.get(row.id, [])
        severity = classify_severity(row.id in captured, set(attack_ids))
        items.append(
            SessionListItem(
                id=row.id,
                src_ip=row.src_ip,
                src_port=row.src_port,
                username=row.username,
                started_at=row.started_at,
                ended_at=row.ended_at,
                severity=SeverityInfo.from_severity(severity),
                open=row.ended_at is None,
                techniques=attack_ids,
            )
        )
    return items


@router.get("/api/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, db: Annotated[DBSession, Depends(get_db)]) -> SessionDetail:
    row = db.get(SessionRow, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    events = list(
        db.exec(
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(Event.timestamp, Event.id)  # type: ignore[arg-type]
        ).all()
    )
    techniques = list(
        db.exec(select(Technique).where(Technique.session_id == session_id).order_by(Technique.id))  # type: ignore[arg-type]
        .all()
    )
    note = db.get(LabNote, session_id)
    captured = successful_login_ids(db, [session_id])
    severity = classify_severity(session_id in captured, {t.attack_id for t in techniques})
    return SessionDetail(
        id=row.id,
        src_ip=row.src_ip,
        src_port=row.src_port,
        username=row.username,
        password=row.password,
        client_version=row.client_version,
        started_at=row.started_at,
        ended_at=row.ended_at,
        end_reason=row.end_reason,
        severity=SeverityInfo.from_severity(severity),
        open=row.ended_at is None,
        events=[
            EventOut(
                id=e.id or 0,
                timestamp=e.timestamp,
                kind=e.kind,
                payload=payload_dict(e.payload),
                generated_by=e.generated_by,
            )
            for e in events
        ],
        techniques=[
            TechniqueOut(
                attack_id=t.attack_id, name=t.name, evidence_event_id=t.evidence_event_id
            )
            for t in techniques
        ],
        lab_note=note.text if note is not None else None,
        iocs=extract_url_iocs(events),
    )
