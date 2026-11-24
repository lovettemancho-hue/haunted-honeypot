"""Async JSON Lines event writer: one ``{log_dir}/{session_id}.jsonl`` per session."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from pathlib import Path
from types import TracebackType

import aiofiles
from aiofiles.threadpool.text import AsyncTextIOWrapper

from trap.models import Event

_log = logging.getLogger(__name__)

_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class EventLogger:
    """Append-only session log. Use as ``async with EventLogger(...) as lg``."""

    def __init__(self, session_id: str, log_dir: Path) -> None:
        # The id becomes a filename, so refuse anything that could escape log_dir.
        if not _SAFE_SESSION_ID.match(session_id):
            raise ValueError("invalid session_id")
        self._session_id = session_id
        self._log_dir = log_dir
        self._path = log_dir / f"{session_id}.jsonl"
        self._file: AsyncTextIOWrapper | None = None

    @property
    def path(self) -> Path:
        return self._path

    async def __aenter__(self) -> EventLogger:
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._file = await aiofiles.open(
                self._path, mode="a", encoding="utf-8"
            )
        except OSError:
            _log.exception("cannot open session log for %s", self._session_id)
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def write(self, event: Event) -> None:
        """Append one event as a JSON line and flush. Re-raises ``OSError``."""
        if self._file is None:
            raise OSError("event logger is not open")
        line = json.dumps(dataclasses.asdict(event), ensure_ascii=False, default=str)
        try:
            await self._file.write(line + "\n")
            await self._file.flush()
        except OSError:
            _log.exception("session log write failed for %s", self._session_id)
            raise

    async def close(self) -> None:
        """Flush and close the file. Safe to call more than once."""
        f, self._file = self._file, None
        if f is None:
            return
        try:
            await f.flush()
        finally:
            await f.close()
