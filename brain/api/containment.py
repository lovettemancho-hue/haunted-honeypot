"""GET /api/containment (Requirement 11)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session as DBSession
from sqlmodel import select

from brain.analysis.severity import classify_severity
from brain.api._common import (
    attack_ids_by_session,
    get_db,
    payload_dict,
    successful_login_ids,
)
from brain.containment.rules import (
    SessionForContainment,
    build_rules,
    extract_mining_ports,
)
from brain.containment.script import render_script
from brain.models import Event
from brain.models import Session as SessionRow
from brain.schemas import ContainmentRuleOut

router = APIRouter()


def _sessions_for_containment(db: DBSession) -> list[SessionForContainment]:
    rows = db.exec(select(SessionRow)).all()
    ids = [r.id for r in rows]
    captured = successful_login_ids(db, ids)
    techniques = attack_ids_by_session(db, ids)

    failed: dict[str, int] = {}
    ports: dict[str, set[int]] = {}
    events = db.exec(
        select(Event.session_id, Event.kind, Event.payload).where(
            Event.kind.in_(["login_attempt", "command", "download_attempt"])  # type: ignore[attr-defined]
        )
    ).all()
    for sid, kind, raw in events:
        data = payload_dict(raw)
        if kind == "login_attempt":
            if data.get("success") is False:
                failed[sid] = failed.get(sid, 0) + 1
            continue
        field = "command" if kind == "command" else "url"
        text = data.get(field)
        if isinstance(text, str):
            found = extract_mining_ports(text)
            if found:
                ports.setdefault(sid, set()).update(found)

    return [
        SessionForContainment(
            session_id=r.id,
            src_ip=r.src_ip,
            severity=classify_severity(r.id in captured, set(techniques.get(r.id, []))),
            had_successful_login=r.id in captured,
            failed_login_count=failed.get(r.id, 0),
            mining_ports=frozenset(ports.get(r.id, set())),
        )
        for r in rows
    ]


@router.get("/api/containment", response_model=None)
def get_containment(
    db: Annotated[DBSession, Depends(get_db)],
    format: Annotated[Literal["json", "script"], Query()] = "json",  # noqa: A002
) -> Response | list[ContainmentRuleOut]:
    rules = build_rules(_sessions_for_containment(db))
    if format == "script":
        return Response(
            content=render_script(rules),
            media_type="text/plain",
            headers={"Content-Disposition": 'attachment; filename="containment.sh"'},
        )
    return [
        ContainmentRuleOut(
            id=r.id,
            kind=r.kind,
            title=r.title,
            description=r.description,
            content=r.content,
            evidence_sessions=list(r.evidence_sessions),
        )
        for r in rules
    ]
