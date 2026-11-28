"""GET /api/sessions, /api/sessions/summary, /api/sessions/{id} and the
reviewed-mark endpoints (Requirement 10, tape triage).

Filters are applied in SQL where the column exists (IP, text search, dates,
technique, reviewed). Severity and "logged in" are derived values, so those
filters are applied in Python over the candidate ids before paging.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, or_
from sqlmodel import Session as DBSession
from sqlmodel import col, delete, select

from brain.analysis.severity import classify_severity
from brain.api._common import (
    attack_ids_by_session,
    get_db,
    payload_dict,
    successful_login_ids,
)
from brain.iocs import extract_url_iocs
from brain.models import Event, LabNote, Review, Severity, Technique
from brain.models import Session as SessionRow
from brain.schemas import (
    BulkReviewIn,
    EventOut,
    ReviewIn,
    ReviewOut,
    SessionDetail,
    SessionListItem,
    SessionSummary,
    SeverityInfo,
    TechniqueOut,
)

router = APIRouter()

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
_CHUNK = 500  # keep IN (...) lists well under SQLite's parameter limit

_SEVERITY_BY_CODE: dict[str, Severity] = {
    "1": Severity.CLASS_1,
    "3": Severity.CLASS_3,
    "5": Severity.CLASS_5,
}


@dataclass(frozen=True)
class TapeFilters:
    q: str | None = None
    ip: str | None = None
    severity: frozenset[Severity] = frozenset()
    technique: str | None = None
    logged_in: bool | None = None
    reviewed: bool | None = None
    since: datetime | None = None
    until: datetime | None = None
    order: Literal["newest", "oldest"] = "newest"


def tape_filters(
    q: Annotated[str | None, Query(max_length=100)] = None,
    ip: Annotated[str | None, Query(max_length=64)] = None,
    severity: Annotated[str | None, Query(max_length=10, pattern=r"^[135](,[135])*$")] = None,
    technique: Annotated[str | None, Query(max_length=20)] = None,
    logged_in: bool | None = None,
    reviewed: bool | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    order: Literal["newest", "oldest"] = "newest",
) -> TapeFilters:
    """Query parameters shared by the list and summary endpoints.

    ``severity`` is a comma list of class numbers, e.g. ``5,3``.
    """
    codes = severity.split(",") if severity else []
    return TapeFilters(
        q=q.strip() or None if q else None,
        ip=ip.strip() or None if ip else None,
        severity=frozenset(_SEVERITY_BY_CODE[c] for c in codes),
        technique=technique.strip() or None if technique else None,
        logged_in=logged_in,
        reviewed=reviewed,
        since=_aware_utc(since),
        until=_aware_utc(until),
        order=order,
    )


def _aware_utc(value: datetime | None) -> datetime | None:
    """Timestamps are stored timezone-aware; a naive query value means UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _chunks(ids: Sequence[str]) -> list[Sequence[str]]:
    return [ids[i : i + _CHUNK] for i in range(0, len(ids), _CHUNK)]


def _captured(db: DBSession, ids: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for chunk in _chunks(ids):
        out |= successful_login_ids(db, chunk)
    return out


def _attacks(db: DBSession, ids: Sequence[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for chunk in _chunks(ids):
        out.update(attack_ids_by_session(db, chunk))
    return out


def _reviewed(db: DBSession, ids: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for chunk in _chunks(ids):
        stmt = select(Review.session_id).where(col(Review.session_id).in_(chunk))
        out |= set(db.exec(stmt).all())
    return out


def _candidate_ids(
    db: DBSession, f: TapeFilters, *, skip_technique: bool = False
) -> list[str]:
    """Ids matching every SQL-expressible filter, in display order."""
    stmt = select(SessionRow.id)
    if f.ip:
        stmt = stmt.where(SessionRow.src_ip == f.ip)
    if f.q:
        pattern = f"%{f.q}%"
        stmt = stmt.where(
            or_(col(SessionRow.src_ip).like(pattern), col(SessionRow.username).like(pattern))
        )
    if f.since is not None:
        stmt = stmt.where(col(SessionRow.started_at) >= f.since)
    if f.until is not None:
        stmt = stmt.where(col(SessionRow.started_at) < f.until)
    if f.technique and not skip_technique:
        stmt = stmt.where(
            exists().where(
                col(Technique.session_id) == col(SessionRow.id),
                col(Technique.attack_id) == f.technique,
            )
        )
    if f.reviewed is not None:
        has_review = exists().where(col(Review.session_id) == col(SessionRow.id))
        stmt = stmt.where(has_review if f.reviewed else ~has_review)
    started = col(SessionRow.started_at)
    if f.order == "oldest":
        stmt = stmt.order_by(started.asc(), col(SessionRow.id))
    else:
        stmt = stmt.order_by(started.desc(), col(SessionRow.id))
    return list(db.exec(stmt).all())


@dataclass(frozen=True)
class _Derived:
    captured: set[str]
    attacks: dict[str, list[str]]

    def severity(self, sid: str) -> Severity:
        return classify_severity(sid in self.captured, set(self.attacks.get(sid, [])))


def _derive(db: DBSession, ids: Sequence[str]) -> _Derived:
    return _Derived(captured=_captured(db, ids), attacks=_attacks(db, ids))


def _apply_derived(
    ids: list[str], d: _Derived, f: TapeFilters, *, skip_severity: bool = False
) -> list[str]:
    out = ids
    if f.logged_in is not None:
        out = [i for i in out if (i in d.captured) == f.logged_in]
    if f.severity and not skip_severity:
        out = [i for i in out if d.severity(i) in f.severity]
    return out


def _needs_derived(f: TapeFilters) -> bool:
    return bool(f.severity) or f.logged_in is not None


@router.get("/api/sessions", response_model=list[SessionListItem])
def list_sessions(
    db: Annotated[DBSession, Depends(get_db)],
    filters: Annotated[TapeFilters, Depends(tape_filters)],
    limit: Annotated[int, Query(ge=0)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SessionListItem]:
    limit = min(limit, MAX_LIMIT)
    ids = _candidate_ids(db, filters)
    if _needs_derived(filters):
        ids = _apply_derived(ids, _derive(db, ids), filters)
    page_ids = ids[offset : offset + limit]
    if not page_ids:
        return []
    page_rows = db.exec(select(SessionRow).where(col(SessionRow.id).in_(page_ids))).all()
    rows = {r.id: r for r in page_rows}
    derived = _derive(db, page_ids)
    reviewed = _reviewed(db, page_ids)
    items: list[SessionListItem] = []
    for sid in page_ids:
        row = rows[sid]
        items.append(
            SessionListItem(
                id=row.id,
                src_ip=row.src_ip,
                src_port=row.src_port,
                username=row.username,
                started_at=row.started_at,
                ended_at=row.ended_at,
                severity=SeverityInfo.from_severity(derived.severity(sid)),
                open=row.ended_at is None,
                techniques=derived.attacks.get(sid, []),
                reviewed=sid in reviewed,
            )
        )
    return items


@router.get("/api/sessions/summary", response_model=SessionSummary)
def sessions_summary(
    db: Annotated[DBSession, Depends(get_db)],
    filters: Annotated[TapeFilters, Depends(tape_filters)],
) -> SessionSummary:
    """Totals for the current filters, plus per-severity and per-technique counts."""
    all_tech_ids = _candidate_ids(db, filters, skip_technique=True)
    derived = _derive(db, all_tech_ids)

    # Per-technique counts: every filter except the technique filter.
    by_technique: dict[str, int] = {}
    for sid in _apply_derived(all_tech_ids, derived, filters):
        for attack_id in set(derived.attacks.get(sid, [])):
            by_technique[attack_id] = by_technique.get(attack_id, 0) + 1

    ids = (
        _candidate_ids(db, filters)
        if filters.technique
        else all_tech_ids
    )
    # Per-severity counts: every filter except the severity filter.
    by_severity = {sev.label: 0 for sev in Severity}
    for sid in _apply_derived(ids, derived, filters, skip_severity=True):
        by_severity[derived.severity(sid).label] += 1

    matching = _apply_derived(ids, derived, filters)
    reviewed = _reviewed(db, matching)
    first_seen = last_seen = None
    if matching:
        bounds = db.exec(
            select(func.min(SessionRow.started_at), func.max(SessionRow.started_at)).where(
                col(SessionRow.id).in_(matching[:_CHUNK])
            )
        ).one()
        if len(matching) > _CHUNK:
            for chunk in _chunks(matching)[1:]:
                lo, hi = db.exec(
                    select(func.min(SessionRow.started_at), func.max(SessionRow.started_at)).where(
                        col(SessionRow.id).in_(chunk)
                    )
                ).one()
                bounds = (min(bounds[0], lo), max(bounds[1], hi))
        first_seen, last_seen = bounds
    return SessionSummary(
        total=len(matching),
        unreviewed=len(matching) - len(reviewed),
        by_severity=by_severity,
        by_technique=dict(sorted(by_technique.items(), key=lambda kv: (-kv[1], kv[0]))),
        first_seen=first_seen,
        last_seen=last_seen,
    )


def _set_reviewed(db: DBSession, ids: Sequence[str], reviewed: bool) -> int:
    existing = set(
        db.exec(select(SessionRow.id).where(col(SessionRow.id).in_(list(ids)))).all()
    ) if ids else set()
    if not existing:
        return 0
    if reviewed:
        already = _reviewed(db, list(existing))
        now = datetime.now(UTC)
        for sid in existing - already:
            db.add(Review(session_id=sid, reviewed_at=now))
    else:
        db.exec(delete(Review).where(col(Review.session_id).in_(list(existing))))
    db.commit()
    return len(existing)


@router.put("/api/sessions/{session_id}/review", response_model=ReviewOut)
def review_session(
    session_id: str, body: ReviewIn, db: Annotated[DBSession, Depends(get_db)]
) -> ReviewOut:
    if db.get(SessionRow, session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return ReviewOut(updated=_set_reviewed(db, [session_id], body.reviewed), reviewed=body.reviewed)


@router.post("/api/sessions/review", response_model=ReviewOut)
def review_sessions(body: BulkReviewIn, db: Annotated[DBSession, Depends(get_db)]) -> ReviewOut:
    """Mark up to 500 tapes at once (e.g. "mark all shown as reviewed")."""
    return ReviewOut(updated=_set_reviewed(db, body.ids, body.reviewed), reviewed=body.reviewed)


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
        reviewed=db.get(Review, session_id) is not None,
    )
