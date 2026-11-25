"""App factory wiring: auth on every /api route and ingest task lifecycle."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from brain import main as main_module
from brain.config import Config
from brain.main import create_app

TOKEN = "t0ken"


def _config(log_dir: Path, tmp_path: Path) -> Config:
    return Config(log_dir=log_dir, api_token=TOKEN, database_path=tmp_path / "x.db")


def test_all_api_routes_require_token(engine: Engine, log_dir: Path, tmp_path: Path) -> None:
    app = create_app(config=_config(log_dir, tmp_path), engine=engine, start_ingest=False)
    paths = [p for p in app.openapi()["paths"] if p.startswith("/api")]
    assert "/api/stats" in paths and "/api/containment" in paths
    client = TestClient(app)
    for path in paths:
        url = path.replace("{session_id}", "nope").replace("{id}", "nope")
        assert client.get(url).status_code == 401
        bad = client.get(url, headers={"Authorization": "Bearer wrong"})
        assert bad.status_code == 401
    ok = client.get("/api/stats", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200


def test_ingest_task_cancelled_on_shutdown(
    engine: Engine, log_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state: dict[str, bool] = {"started": False, "cancelled": False}

    async def fake_loop(*_args: object, **_kwargs: object) -> None:
        state["started"] = True
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(main_module, "ingest_loop", fake_loop)
    app = create_app(config=_config(log_dir, tmp_path), engine=engine)
    with TestClient(app):
        pass
    assert state == {"started": True, "cancelled": True}


def test_no_ingest_when_disabled(
    engine: Engine, log_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []

    async def fake_loop(*_args: object, **_kwargs: object) -> None:
        called.append(True)

    monkeypatch.setattr(main_module, "ingest_loop", fake_loop)
    app = create_app(config=_config(log_dir, tmp_path), engine=engine, start_ingest=False)
    with TestClient(app):
        pass
    assert not called
