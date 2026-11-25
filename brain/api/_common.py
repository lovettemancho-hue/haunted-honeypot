"""Shared helpers for the API routers (DB session dependency, severity lookup)."""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator
from typing import Any

from fastapi import Request
from sqlmodel import Session as DBSession
from sqlmodel import select

from brain.models import Event, Technique


def get_db(request: Request) -> Iterator[DBSession]:
    """Yield a short-lived DB session bound to ``request.app.state.engine``."""
    with DBSession(request.app.state.engine) as session:
        yield session


def payload_dict(raw: str) -> dict[str, Any]:
    """Decode a stored JSON payload; anything that is not an object becomes ``{}``."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def successful_login_ids(db: DBSession, session_ids: Collection[str]) -> set[str]:
    """Ids among ``session_ids`` that have a successful login_attempt event."""
    if not session_ids:
        return set()
    rows = db.exec(
        select(Event.session_id, Event.payload).where(
            Event.kind == "login_attempt", Event.session_id.in_(session_ids)  # type: ignore[attr-defined]
        )
    ).all()
    return {sid for sid, raw in rows if payload_dict(raw).get("success") is True}


def attack_ids_by_session(db: DBSession, session_ids: Collection[str]) -> dict[str, list[str]]:
    """Technique attack_ids per session id, in storage order."""
    if not session_ids:
        return {}
    rows = db.exec(
        select(Technique.session_id, Technique.attack_id)
        .where(Technique.session_id.in_(session_ids))  # type: ignore[attr-defined]
        .order_by(Technique.id)  # type: ignore[arg-type]
    ).all()
    result: dict[str, list[str]] = {}
    for sid, attack_id in rows:
        result.setdefault(sid, []).append(attack_id)
    return result
