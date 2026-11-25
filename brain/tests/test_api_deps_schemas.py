"""Tests for the auth dependency and response schemas (Requirements 5.4, 8.2-8.6)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from brain.api.deps import require_token
from brain.config import Config
from brain.models import Severity
from brain.schemas import SessionDetail, SeverityInfo


def _client(token: str = "s3cret") -> TestClient:
    app = FastAPI()
    app.state.config = Config(log_dir=Path("."), api_token=token)

    @app.get("/x", dependencies=[Depends(require_token)])
    async def x() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "s3cret"},
        {"Authorization": "Basic s3cret"},
        {"Authorization": "Bearer nope"},
    ],
)
def test_rejects_bad_auth(headers: dict[str, str]) -> None:
    response = _client().get("/x", headers=headers)
    assert response.status_code == 401
    assert "ok" not in response.text


def test_accepts_valid_token() -> None:
    assert _client().get("/x", headers={"Authorization": "Bearer s3cret"}).status_code == 200


# Feature: brain, Property 20: wrong tokens never authenticate
# **Validates: Requirements 8.2, 8.3**
@given(st.text(max_size=40).filter(lambda t: t != "s3cret" and t.isascii() and t.strip() == t))
def test_wrong_token_is_401(token: str) -> None:
    response = _client().get("/x", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_severity_label_and_description() -> None:
    info = SeverityInfo.from_severity(Severity.CLASS_5)
    assert info.label == "Class 5"
    assert info.description


# Feature: brain, Property 21: every returned IOC is defanged
# **Validates: Requirements 8.6**
@given(st.lists(st.from_regex(r"https?://[a-z0-9.]{1,20}/[a-z]{0,5}", fullmatch=True), max_size=5))
def test_detail_iocs_defanged(urls: list[str]) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    detail = SessionDetail(
        id="a",
        src_ip="1.2.3.4",
        src_port=1,
        username=None,
        password=None,
        client_version="v",
        started_at=now,
        ended_at=None,
        end_reason=None,
        severity=SeverityInfo.from_severity(Severity.CLASS_1),
        open=True,
        events=[],
        techniques=[],
        lab_note=None,
        iocs=urls,
    )
    for ioc in detail.iocs:
        assert "http://" not in ioc and "https://" not in ioc
        assert "." not in ioc.replace("[.]", "")
