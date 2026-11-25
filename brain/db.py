"""SQLModel engine and session factory for the Brain.

The database is a rebuildable cache of the Session_Logs. Queries use the
SQLModel/SQLAlchemy expression API only (parameterized, portable to Postgres).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session as DBSession
from sqlmodel import SQLModel, create_engine

from brain import models  # noqa: F401  (registers tables on SQLModel.metadata)


def make_engine(database_path: Path | str) -> Engine:
    """Create a SQLite engine usable from the API threads and the ingest loop."""
    path = str(database_path)
    url = "sqlite://" if path == ":memory:" else f"sqlite:///{path}"
    return create_engine(url, connect_args={"check_same_thread": False})


def create_db_and_tables(engine: Engine) -> None:
    """Create every Brain table that does not exist yet."""
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[DBSession]:
    """Short-lived DB session: commit on success, roll back on error."""
    with DBSession(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
