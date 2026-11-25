"""Note_Generator: stores one Lab_Note per ended Session (LLM or template)."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from brain.analysis.severity import classify_severity
from brain.config import Config
from brain.db import session_scope
from brain.iocs import extract_url_iocs
from brain.llm import LLMClient
from brain.models import Event, LabNote, Session, Technique
from brain.notes.template import MAX_NOTE_CHARS, SessionSummary, build_template_note

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 30


class _Inputs:
    """Everything read from the DB for one ended Session."""

    def __init__(
        self,
        summary: SessionSummary,
        commands: list[str],
        usernames: list[str],
        passwords: list[str],
        urls: list[str],
    ) -> None:
        self.summary = summary
        self.commands = commands
        self.usernames = usernames
        self.passwords = passwords
        self.urls = urls


def _payload(event: Event) -> dict[str, object]:
    try:
        data = json.loads(event.payload)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _distinct(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _load(session_id: str, engine: Engine) -> str | _Inputs | None:
    """Return the stored note text, the inputs for a new note, or None when
    the Session is unknown or still open."""
    with session_scope(engine) as db:
        note = db.get(LabNote, session_id)
        if note is not None:
            return note.text
        session = db.get(Session, session_id)
        if session is None or session.ended_at is None:
            return None
        events = list(
            db.exec(
                select(Event)
                .where(Event.session_id == session_id)
                .order_by(col(Event.timestamp), col(Event.id))
            ).all()
        )
        attack_ids = [
            t.attack_id
            for t in db.exec(select(Technique).where(Technique.session_id == session_id)).all()
        ]
        src_ip = session.src_ip
        # Detach so commit-time expiry does not invalidate Events read below.
        db.expunge_all()

    commands: list[str] = []
    usernames: list[str] = []
    passwords: list[str] = []
    login_succeeded = False
    for event in events:
        data = _payload(event)
        if event.kind == "command":
            command = data.get("command")
            if isinstance(command, str):
                commands.append(command)
        elif event.kind == "login_attempt":
            username = data.get("username")
            password = data.get("password")
            if isinstance(username, str):
                usernames.append(username)
            if isinstance(password, str):
                passwords.append(password)
            if data.get("success") is True:
                login_succeeded = True

    unique_ids = tuple(dict.fromkeys(attack_ids))
    summary = SessionSummary(
        src_ip=src_ip,
        login_succeeded=login_succeeded,
        command_count=len(commands),
        attack_ids=unique_ids,
        severity=classify_severity(login_succeeded, unique_ids),
    )
    return _Inputs(
        summary,
        commands,
        _distinct(usernames),
        _distinct(passwords),
        extract_url_iocs(events),
    )


def _store(session_id: str, engine: Engine, text: str, generated_by: str) -> str:
    """Insert the note unless another writer stored one first; return the stored text."""
    with session_scope(engine) as db:
        existing = db.get(LabNote, session_id)
        if existing is not None:
            return existing.text
        db.add(
            LabNote(
                session_id=session_id,
                text=text,
                generated_by=generated_by,
                created_at=datetime.now(UTC),
            )
        )
    return text


async def _llm_text(inputs: _Inputs, llm_client: LLMClient) -> str | None:
    """LLM summary truncated to the cap, or None on timeout/error/empty."""
    try:
        text = await asyncio.wait_for(
            llm_client.summarize(inputs.commands, inputs.usernames, inputs.passwords, inputs.urls),
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("LLM note generation timed out; using template")
        return None
    except Exception as exc:
        logger.warning("LLM note generation failed (%s); using template", type(exc).__name__)
        return None
    text = text.strip() if isinstance(text, str) else ""
    return text[:MAX_NOTE_CHARS] if text else None


async def ensure_note(
    session_id: str, config: Config, engine: Engine, llm_client: LLMClient
) -> str:
    """Return the Lab_Note for an ended Session, creating it if needed.

    Returns the stored note without calling the LLM when one exists. Returns
    "" for open or unknown Sessions (no note is stored). Falls back to a
    Template_Note when no API key is set or the LLM errors, times out or
    returns nothing. Never raises.
    """
    try:
        loaded = _load(session_id, engine)
        if loaded is None:
            return ""
        if isinstance(loaded, str):
            return loaded

        text: str | None = None
        generated_by = "template"
        if config.llm_api_key:
            text = await _llm_text(loaded, llm_client)
            if text is not None:
                generated_by = "llm"
        if text is None:
            text = build_template_note(loaded.summary)
        return _store(session_id, engine, text[:MAX_NOTE_CHARS], generated_by)
    except Exception:
        logger.exception("Note generation failed for a session")
        return ""
