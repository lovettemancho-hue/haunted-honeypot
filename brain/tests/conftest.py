"""Shared pytest fixtures for the Brain tests."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine

from brain.db import create_db_and_tables, make_engine

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_API_TOKEN = "test-token"


@pytest.fixture
def fixtures_dir() -> Path:
    """Directory holding the sample Class_1 / Class_3 / Class_5 JSONL files."""
    return FIXTURES_DIR


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """SQLite engine on a temp file with all tables created."""
    eng = make_engine(tmp_path / "brain-test.db")
    create_db_and_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """Empty temp Log_Dir."""
    path = tmp_path / "logs"
    path.mkdir()
    return path


@pytest.fixture
def sample_log_dir(log_dir: Path) -> Path:
    """Temp Log_Dir pre-populated with the three sample Session_Logs."""
    for src in FIXTURES_DIR.glob("*.jsonl"):
        shutil.copy(src, log_dir / src.name)
    return log_dir


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_TOKEN}"}


@pytest.fixture
def make_auth_client(
    engine: Engine, log_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], Any]:
    """Return a factory for a TestClient with the bearer token preset.

    The app factory arrives in task 9.3, so imports happen inside the function.
    """

    def _make() -> Any:
        from fastapi.testclient import TestClient

        from brain.config import Config
        from brain.main import create_app  # type: ignore[import-not-found,unused-ignore]

        config = Config(
            log_dir=log_dir,
            api_token=TEST_API_TOKEN,
            database_path=tmp_path / "brain-test.db",
        )
        app = create_app(config=config, engine=engine)
        client = TestClient(app)
        client.headers.update({"Authorization": f"Bearer {TEST_API_TOKEN}"})
        return client

    return _make
