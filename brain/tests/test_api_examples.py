"""Example-based API tests (Requirements 8.7, 8.8, 9.8, 10.7, 11.2, 11.3, 13.6, 13.8)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session as DBSession

from brain.models import Event, Session

Factory = Callable[[], Any]

ENDPOINTS = [
    "/api/stats",
    "/api/sessions",
    "/api/sessions/some-id",
    "/api/containment",
    "/api/containment?format=script",
]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_missing_token_returns_401(make_auth_client: Factory, path: str) -> None:
    client = make_auth_client()
    client.headers.pop("Authorization")
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize(
    "header", ["Bearer wrong-token", "Basic test-token", "test-token", "Bearer "]
)
def test_invalid_token_returns_401(make_auth_client: Factory, path: str, header: str) -> None:
    client = make_auth_client()
    assert client.get(path, headers={"Authorization": header}).status_code == 401


def test_unknown_session_returns_404_json(make_auth_client: Factory) -> None:
    resp = make_auth_client().get("/api/sessions/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_empty_database_stats(make_auth_client: Factory) -> None:
    resp = make_auth_client().get("/api/stats")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["attempts"] == 0
    assert body["unique_ips"] == 0
    assert body["captured"] == 0
    assert body["longest_session_seconds"] == 0
    assert body["threat_level"] == 0
    assert body["top_passwords"] == []
    assert body["technique_counts"] in ([], {})


def test_empty_database_containment_and_sessions(make_auth_client: Factory) -> None:
    client = make_auth_client()
    resp = client.get("/api/containment")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == []
    sessions = client.get("/api/sessions")
    assert sessions.status_code == 200
    assert sessions.json() == []


def test_containment_script_is_plain_text_attachment(make_auth_client: Factory) -> None:
    resp = make_auth_client().get("/api/containment", params={"format": "script"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert ".sh" in disposition


def test_containment_invalid_format_is_422(make_auth_client: Factory) -> None:
    assert make_auth_client().get("/api/containment?format=xml").status_code == 422


def test_url_ioc_is_defanged(make_auth_client: Factory, engine: Engine) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    with DBSession(engine) as db:
        db.add(
            Session(
                id="s1",
                src_ip="203.0.113.7",
                src_port=4444,
                client_version="SSH-2.0-test",
                started_at=now,
            )
        )
        db.add(
            Event(
                session_id="s1",
                timestamp=now,
                kind="download_attempt",
                payload=json.dumps({"url": "http://evil.example.com/x.sh"}),
                generated_by="scripted",
            )
        )
        db.commit()
    resp = make_auth_client().get("/api/sessions/s1")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    iocs = resp.json()["iocs"]
    assert iocs == ["hxxp://evil[.]example[.]com/x[.]sh"]
