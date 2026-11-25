"""Integration tests for the Ingest_Cycle.

Validates: Requirements 2.5, 2.6, 2.8, 2.11, 13.1, 13.3
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import select

from brain.analysis.severity import classify_severity
from brain.config import Config
from brain.db import create_db_and_tables, make_engine, session_scope
from brain.ingest.ingestor import run_ingest_cycle
from brain.models import Event, IngestOffset, Severity, Technique
from brain.models import Session as SessionRow


def _config(log_dir: Path) -> Config:
    return Config(log_dir=log_dir, api_token="t")


def _snapshot(engine: Engine) -> dict[str, list[dict[str, object]]]:
    """Every row of every ingest-owned table, as plain dicts, in a stable order."""
    with session_scope(engine) as db:
        return {
            "sessions": [
                r.model_dump() for r in db.exec(select(SessionRow).order_by(SessionRow.id)).all()
            ],
            "events": [
                r.model_dump() for r in db.exec(select(Event).order_by(Event.id)).all()  # type: ignore[arg-type]
            ],
            "techniques": [
                r.model_dump()
                for r in db.exec(select(Technique).order_by(Technique.id)).all()  # type: ignore[arg-type]
            ],
            "offsets": [
                r.model_dump()
                for r in db.exec(select(IngestOffset).order_by(IngestOffset.file_name)).all()
            ],
        }


def _severity(engine: Engine, session_id: str) -> Severity:
    with session_scope(engine) as db:
        ids = frozenset(
            t.attack_id
            for t in db.exec(select(Technique).where(Technique.session_id == session_id)).all()
        )
    return classify_severity("T1078" in ids, ids)


def _count_events(engine: Engine, session_id: str) -> int:
    with session_scope(engine) as db:
        return len(db.exec(select(Event).where(Event.session_id == session_id)).all())


def _ended_at(engine: Engine, session_id: str) -> object:
    with session_scope(engine) as db:
        row = db.get(SessionRow, session_id)
        assert row is not None
        return row.ended_at


@pytest.mark.asyncio
async def test_repeated_cycle_leaves_database_unchanged(
    sample_log_dir: Path, engine: Engine
) -> None:
    config = _config(sample_log_dir)
    await run_ingest_cycle(config, engine)
    first = _snapshot(engine)
    assert first["events"]

    await run_ingest_cycle(config, engine)
    await run_ingest_cycle(config, engine)
    assert _snapshot(engine) == first


@pytest.mark.asyncio
async def test_partial_last_line_ingested_only_after_newline(
    log_dir: Path, engine: Engine, fixtures_dir: Path
) -> None:
    text = (fixtures_dir / "class1_session.jsonl").read_text(encoding="utf-8").rstrip("\n")
    log = log_dir / "partial.jsonl"
    log.write_bytes(text.encode("utf-8"))  # last (session_end) line has no newline yet
    config = _config(log_dir)

    await run_ingest_cycle(config, engine)
    assert _count_events(engine, "sess-class1") == 3
    assert _ended_at(engine, "sess-class1") is None

    with log.open("ab") as handle:
        handle.write(b"\n")
    await run_ingest_cycle(config, engine)
    assert _count_events(engine, "sess-class1") == 4
    assert _ended_at(engine, "sess-class1") is not None


@pytest.mark.asyncio
async def test_truncated_file_is_reingested_from_zero(
    log_dir: Path, engine: Engine, fixtures_dir: Path
) -> None:
    lines = (fixtures_dir / "class3_session.jsonl").read_text(encoding="utf-8").splitlines(True)
    log = log_dir / "sess-class3.jsonl"
    log.write_text("".join(lines), encoding="utf-8")
    config = _config(log_dir)

    await run_ingest_cycle(config, engine)
    assert _count_events(engine, "sess-class3") == len(lines)
    assert _ended_at(engine, "sess-class3") is not None

    kept = lines[:2]
    log.write_text("".join(kept), encoding="utf-8")
    await run_ingest_cycle(config, engine)

    assert _count_events(engine, "sess-class3") == len(kept)
    assert _ended_at(engine, "sess-class3") is None
    with session_scope(engine) as db:
        stored = db.get(IngestOffset, log.name)
        assert stored is not None
        assert stored.offset == log.stat().st_size


@pytest.mark.asyncio
async def test_deleted_database_is_rebuilt_from_logs(
    sample_log_dir: Path, tmp_path: Path
) -> None:
    config = _config(sample_log_dir)
    db_path = tmp_path / "rebuild.db"
    first_engine = make_engine(db_path)
    create_db_and_tables(first_engine)
    await run_ingest_cycle(config, first_engine)
    before = _snapshot(first_engine)
    first_engine.dispose()

    db_path.unlink()
    second_engine = make_engine(db_path)
    create_db_and_tables(second_engine)
    try:
        assert not _snapshot(second_engine)["events"]
        await run_ingest_cycle(config, second_engine)
        assert _snapshot(second_engine) == before
    finally:
        second_engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("sess-class1", Severity.CLASS_1),
        ("sess-class3", Severity.CLASS_3),
        ("sess-class5", Severity.CLASS_5),
    ],
)
async def test_fixture_sessions_yield_expected_severity(
    sample_log_dir: Path, engine: Engine, session_id: str, expected: Severity
) -> None:
    await run_ingest_cycle(_config(sample_log_dir), engine)
    assert _severity(engine, session_id) is expected
