"""FastAPI app factory for the Brain.

Run with ``uvicorn brain.main:create_app --factory`` or ``python -m brain``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.engine import Engine

from brain.api import containment, sessions, stats
from brain.api.deps import require_token
from brain.config import Config, load_config
from brain.db import create_db_and_tables, make_engine
from brain.ingest.ingestor import ingest_loop
from brain.notes.hook import make_note_hook

logger = logging.getLogger(__name__)


def create_app(
    config: Config | None = None,
    engine: Engine | None = None,
    start_ingest: bool = True,
) -> FastAPI:
    """Build the Brain app.

    ``app.state.config`` and ``app.state.engine`` are set at creation time so
    the app works without running the lifespan. The ingest loop only runs
    inside the lifespan, and only when ``start_ingest`` is true.
    """
    cfg = config if config is not None else load_config()
    if engine is None:
        engine = make_engine(cfg.database_path)
    create_db_and_tables(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task: asyncio.Task[None] | None = None
        if start_ingest:
            task = asyncio.create_task(
                ingest_loop(cfg, engine_, after_cycle=make_note_hook()),
                name="brain-ingest",
            )
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    engine_ = engine
    app = FastAPI(title="Haunted Honeypot Brain", lifespan=lifespan)
    app.state.config = cfg
    app.state.engine = engine
    for module in (stats, sessions, containment):
        app.include_router(module.router, dependencies=[Depends(require_token)])
    return app
