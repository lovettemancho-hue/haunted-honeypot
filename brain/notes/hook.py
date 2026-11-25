"""After-cycle hook: generate Lab_Notes for ended Sessions that have none."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from brain.config import Config
from brain.db import session_scope
from brain.ingest.ingestor import AfterCycleHook
from brain.llm import LLMClient
from brain.models import LabNote, Session
from brain.notes.generator import ensure_note

logger = logging.getLogger(__name__)


def _sessions_missing_notes(engine: Engine) -> list[str]:
    """Ids of ended Sessions with no stored Lab_Note (includes earlier cycles)."""
    with session_scope(engine) as db:
        stmt = (
            select(Session.id)
            .outerjoin(LabNote, col(LabNote.session_id) == col(Session.id))
            .where(col(Session.ended_at).is_not(None), col(LabNote.session_id).is_(None))
            .order_by(col(Session.ended_at))
        )
        return list(db.exec(stmt).all())


async def generate_notes_after_cycle(
    config: Config,
    engine: Engine,
    touched_session_ids: Sequence[str],
    llm_client: LLMClient | None = None,
) -> None:
    """Call ``ensure_note`` for every ended Session lacking a note.

    ``touched_session_ids`` is unused: all ended Sessions without a note are
    selected so earlier misses are backfilled. A failure on one Session is
    logged and does not stop the others.
    """
    client = llm_client if llm_client is not None else LLMClient(config)
    try:
        pending = _sessions_missing_notes(engine)
    except Exception:
        logger.exception("could not list Sessions missing notes")
        return
    for session_id in pending:
        try:
            await ensure_note(session_id, config, engine, client)
        except Exception:
            logger.exception("note generation failed for session %s", session_id)


def make_note_hook(llm_client: LLMClient | None = None) -> AfterCycleHook:
    """Build an ``AfterCycleHook`` for ``run_ingest_cycle`` / ``ingest_loop``.

    Pass the result as ``after_cycle``; callers passing ``None`` get no notes.
    """

    async def hook(config: Config, engine: Engine, touched: Sequence[str]) -> None:
        await generate_notes_after_cycle(config, engine, touched, llm_client)

    return hook
