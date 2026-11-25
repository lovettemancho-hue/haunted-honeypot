"""Smoke tests for the stats, sessions and containment routers."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from brain.api import containment, sessions, stats
from brain.api.deps import require_token
from brain.config import Config
from brain.ingest.ingestor import run_ingest_cycle

TOKEN = "test-token"


@pytest.fixture
def client(engine: Engine, sample_log_dir: Path, tmp_path: Path) -> Iterator[TestClient]:
    config = Config(log_dir=sample_log_dir, api_token=TOKEN, database_path=tmp_path / "x.db")
    asyncio.run(run_ingest_cycle(config, engine))
    app = FastAPI()
    app.state.engine = engine
    app.state.config = config
    for module in (stats, sessions, containment):
        app.include_router(module.router, dependencies=[Depends(require_token)])
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def test_stats(client: TestClient) -> None:
    body = client.get("/api/stats").json()
    assert body["attempts"] > 0
    assert 0 <= body["threat_level"] <= 10


def test_requires_token(client: TestClient) -> None:
    assert client.get("/api/stats", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_sessions_list_and_pagination(client: TestClient) -> None:
    items = client.get("/api/sessions").json()
    assert len(items) == 3
    starts = [i["started_at"] for i in items]
    assert starts == sorted(starts, reverse=True)
    assert {"open", "techniques", "severity"} <= items[0].keys()
    assert len(client.get("/api/sessions?limit=1&offset=1").json()) == 1
    for bad in ("limit=-1", "offset=-1", "limit=abc", "offset=x"):
        assert client.get(f"/api/sessions?{bad}").status_code == 422


def test_session_detail(client: TestClient) -> None:
    sid = client.get("/api/sessions").json()[0]["id"]
    body = client.get(f"/api/sessions/{sid}").json()
    stamps = [e["timestamp"] for e in body["events"]]
    assert stamps == sorted(stamps)
    assert body["lab_note"] is None
    assert all("http://" not in ioc and "https://" not in ioc for ioc in body["iocs"])
    missing = client.get("/api/sessions/nope")
    assert missing.status_code == 404
    assert "detail" in missing.json()


def test_containment_json_and_script(client: TestClient) -> None:
    rules = client.get("/api/containment").json()
    assert rules
    assert {"id", "kind", "title", "description", "content", "evidence_sessions"} <= rules[0].keys()
    resp = client.get("/api/containment?format=script")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.headers["content-disposition"] == 'attachment; filename="containment.sh"'
    assert client.get("/api/containment?format=xml").status_code == 422
