"""Note hook wired into the ingest cycle (Requirements 6.1, 6.2, 6.6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain.config import Config
from brain.db import create_db_and_tables, make_engine, session_scope
from brain.ingest.ingestor import run_ingest_cycle
from brain.models import LabNote
from brain.notes.hook import make_note_hook


def _line(sid: str, kind: str, ts: str, payload: dict[str, object]) -> str:
    return json.dumps({"session_id": sid, "timestamp": ts, "kind": kind, "payload": payload})


@pytest.mark.asyncio
async def test_notes_for_ended_sessions_only(tmp_path: Path) -> None:
    lines = [
        _line("a", "session_start", "2024-01-01T00:00:00Z", {"src_ip": "1.2.3.4", "src_port": 1}),
        _line("a", "session_end", "2024-01-01T00:01:00Z", {"reason": "closed"}),
        _line("b", "session_start", "2024-01-01T00:00:00Z", {"src_ip": "1.2.3.5", "src_port": 2}),
    ]
    (tmp_path / "x.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = Config(log_dir=tmp_path, api_token="t")
    engine = make_engine(tmp_path / "b.db")
    create_db_and_tables(engine)

    await run_ingest_cycle(config, engine, make_note_hook())
    with session_scope(engine) as db:
        assert db.get(LabNote, "a") is not None
        assert db.get(LabNote, "b") is None

    # Explicit None keeps working and a later cycle with nothing new is fine.
    await run_ingest_cycle(config, engine, None)
    await run_ingest_cycle(config, engine, make_note_hook())
