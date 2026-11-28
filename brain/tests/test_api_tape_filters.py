"""Tape triage: list filters, summary counts and reviewed marks."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from brain.api import sessions
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
    app.include_router(sessions.router, dependencies=[Depends(require_token)])
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def _all(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    r = client.get("/api/sessions", params=params)
    assert r.status_code == 200, r.text
    data: list[dict[str, Any]] = r.json()
    return data


def test_unfiltered_list_is_unchanged_and_has_reviewed_flag(client: TestClient) -> None:
    items = _all(client)
    assert len(items) == 3
    assert all(i["reviewed"] is False for i in items)
    starts = [i["started_at"] for i in items]
    assert starts == sorted(starts, reverse=True)


def test_order_oldest(client: TestClient) -> None:
    starts = [i["started_at"] for i in _all(client, order="oldest")]
    assert starts == sorted(starts)


def test_severity_filter_and_combination(client: TestClient) -> None:
    for code, label in (("1", "Class 1"), ("3", "Class 3"), ("5", "Class 5")):
        items = _all(client, severity=code)
        assert items and all(i["severity"]["label"] == label for i in items)
    both = _all(client, severity="5,3")
    assert {i["severity"]["label"] for i in both} == {"Class 3", "Class 5"}


def test_bad_severity_is_rejected(client: TestClient) -> None:
    assert client.get("/api/sessions", params={"severity": "2"}).status_code == 422


def test_logged_in_filter(client: TestClient) -> None:
    yes = _all(client, logged_in="true")
    no = _all(client, logged_in="false")
    assert {i["severity"]["label"] for i in yes} == {"Class 3", "Class 5"}
    assert {i["severity"]["label"] for i in no} == {"Class 1"}


def test_ip_text_technique_and_date_filters(client: TestClient) -> None:
    items = _all(client)
    target = items[0]
    assert [i["id"] for i in _all(client, ip=target["src_ip"])] == [
        i["id"] for i in items if i["src_ip"] == target["src_ip"]
    ]
    part = target["src_ip"].split(".")[0]
    assert target["id"] in {i["id"] for i in _all(client, q=part)}
    assert _all(client, q="no-such-thing") == []
    tech = next(t for i in items for t in i["techniques"])
    assert all(tech in i["techniques"] for i in _all(client, technique=tech))
    assert _all(client, since="2999-01-01T00:00:00Z") == []
    assert len(_all(client, until="2999-01-01T00:00:00Z")) == 3


def test_paging_applies_after_derived_filters(client: TestClient) -> None:
    logged_in = _all(client, logged_in="true")
    page1 = _all(client, logged_in="true", limit=1, offset=0)
    page2 = _all(client, logged_in="true", limit=1, offset=1)
    assert [p["id"] for p in page1 + page2] == [i["id"] for i in logged_in]


def test_summary_counts(client: TestClient) -> None:
    s = client.get("/api/sessions/summary").json()
    assert s["total"] == 3 and s["unreviewed"] == 3
    assert s["by_severity"] == {"Class 1": 1, "Class 3": 1, "Class 5": 1}
    assert s["first_seen"] <= s["last_seen"]
    # The severity counts ignore the severity filter; the total does not.
    f = client.get("/api/sessions/summary", params={"severity": "5"}).json()
    assert f["total"] == 1 and f["by_severity"]["Class 3"] == 1
    assert sum(s["by_technique"].values()) >= 1


def test_review_single_and_filter(client: TestClient) -> None:
    sid = _all(client)[0]["id"]
    r = client.put(f"/api/sessions/{sid}/review", json={"reviewed": True})
    assert r.status_code == 200 and r.json() == {"updated": 1, "reviewed": True}
    # Idempotent.
    assert client.put(f"/api/sessions/{sid}/review", json={"reviewed": True}).status_code == 200
    assert client.get(f"/api/sessions/{sid}").json()["reviewed"] is True
    assert [i["id"] for i in _all(client, reviewed="true")] == [sid]
    assert sid not in {i["id"] for i in _all(client, reviewed="false")}
    assert client.get("/api/sessions/summary").json()["unreviewed"] == 2
    client.put(f"/api/sessions/{sid}/review", json={"reviewed": False})
    assert client.get(f"/api/sessions/{sid}").json()["reviewed"] is False


def test_review_unknown_session_404(client: TestClient) -> None:
    assert client.put("/api/sessions/nope/review", json={"reviewed": True}).status_code == 404


def test_bulk_review_ignores_unknown_ids_and_caps_size(client: TestClient) -> None:
    ids = [i["id"] for i in _all(client)]
    r = client.post("/api/sessions/review", json={"ids": [*ids, "nope"], "reviewed": True})
    assert r.json() == {"updated": 3, "reviewed": True}
    assert client.get("/api/sessions/summary").json()["unreviewed"] == 0
    r = client.post("/api/sessions/review", json={"ids": ids, "reviewed": False})
    assert client.get("/api/sessions/summary").json()["unreviewed"] == 3
    too_many = client.post("/api/sessions/review", json={"ids": ["x"] * 501, "reviewed": True})
    assert too_many.status_code == 422


def test_repeat_count_counts_tapes_from_the_same_ip(client: TestClient) -> None:
    items = _all(client)
    for i in items:
        same = sum(1 for j in items if j["src_ip"] == i["src_ip"])
        assert i["repeat_count"] == same


def test_search_treats_like_wildcards_literally(client: TestClient) -> None:
    assert _all(client, q="%") == []
    assert _all(client, q="_") == []
    assert _all(client, q="\\") == []
