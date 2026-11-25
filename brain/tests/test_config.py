"""Tests for brain.config (Requirements 1.3, 1.4, 1.5, 1.7)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from brain.config import Config, load_config

SECRET_TOKEN = "super-secret-token-xyz"
SECRET_KEY = "super-secret-llm-key-abc"


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BRAIN_LOG_DIR",
        "BRAIN_API_TOKEN",
        "BRAIN_DATABASE_PATH",
        "BRAIN_LLM_API_KEY",
        "BRAIN_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BRAIN_LOG_DIR", "/data/logs")
    monkeypatch.setenv("BRAIN_API_TOKEN", SECRET_TOKEN)
    cfg = load_config()
    assert cfg.log_dir == Path("/data/logs")
    assert cfg.llm_model == "gemini-1.5-flash"
    assert cfg.llm_api_key is None
    assert cfg.ingest_interval_seconds == 10


def test_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BRAIN_LOG_DIR", "/l")
    monkeypatch.setenv("BRAIN_API_TOKEN", "t")
    monkeypatch.setenv("BRAIN_DATABASE_PATH", "/d/b.db")
    monkeypatch.setenv("BRAIN_LLM_API_KEY", "k")
    monkeypatch.setenv("BRAIN_LLM_MODEL", "m")
    cfg = load_config()
    assert cfg.database_path == Path("/d/b.db")
    assert cfg.llm_api_key == "k"
    assert cfg.llm_model == "m"


@pytest.mark.parametrize("missing", ["BRAIN_LOG_DIR", "BRAIN_API_TOKEN"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_required_exits_and_logs_name_only(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    missing: str,
    value: str | None,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BRAIN_LOG_DIR", "/data/logs")
    monkeypatch.setenv("BRAIN_API_TOKEN", SECRET_TOKEN)
    monkeypatch.setenv("BRAIN_LLM_API_KEY", SECRET_KEY)
    if value is None:
        monkeypatch.delenv(missing)
    else:
        monkeypatch.setenv(missing, value)
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        load_config()
    assert exc.value.code == 1
    assert missing in caplog.text
    assert SECRET_TOKEN not in caplog.text
    assert SECRET_KEY not in caplog.text


def test_repr_hides_secrets() -> None:
    cfg = Config(log_dir=Path("/l"), api_token=SECRET_TOKEN, llm_api_key=SECRET_KEY)
    text = repr(cfg)
    assert SECRET_TOKEN not in text
    assert SECRET_KEY not in text
    assert "api_token" not in text
    assert "llm_api_key" not in text
