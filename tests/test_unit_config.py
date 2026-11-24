"""Unit tests for trap.config.load_config.

Validates: Requirements 1.6
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from trap.config import MAX_INPUT_LINE, Config, load_config

ALL_VARS = (
    "TRAP_PORT",
    "TRAP_HOST_KEY_PATH",
    "TRAP_CREDENTIAL_FILE",
    "TRAP_LOG_DIR",
    "TRAP_IDLE_TIMEOUT_SECONDS",
    "TRAP_MAX_SESSION_SECONDS",
    "TRAP_ACCEPT_AFTER_ATTEMPTS",
    "TRAP_LLM_BACKEND",
    "TRAP_LLM_API_URL",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Clean environment containing only the required variables."""
    for name in ALL_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRAP_HOST_KEY_PATH", str(tmp_path / "keys" / "host_key"))
    monkeypatch.setenv("TRAP_CREDENTIAL_FILE", str(tmp_path / "creds.txt"))
    monkeypatch.setenv("TRAP_LOG_DIR", str(tmp_path / "logs"))
    return monkeypatch


def test_defaults(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = load_config()
    assert cfg.trap_port == 2222
    assert cfg.idle_timeout_seconds == 300
    assert cfg.max_session_seconds == 1800
    assert cfg.max_input_line == MAX_INPUT_LINE == 4096
    assert cfg.accept_after_attempts is None
    assert cfg.llm_backend == "scripted"
    assert cfg.llm_api_url is None
    assert cfg.host_key_path == tmp_path / "keys" / "host_key"
    assert cfg.credential_file == tmp_path / "creds.txt"
    assert cfg.log_dir == tmp_path / "logs"


def test_all_values_overridden(env: pytest.MonkeyPatch) -> None:
    env.setenv("TRAP_PORT", "4000")
    env.setenv("TRAP_IDLE_TIMEOUT_SECONDS", "10")
    env.setenv("TRAP_MAX_SESSION_SECONDS", "20")
    env.setenv("TRAP_ACCEPT_AFTER_ATTEMPTS", "5")
    env.setenv("TRAP_LLM_BACKEND", "openai")
    env.setenv("TRAP_LLM_API_URL", "https://llm.example/v1")
    cfg = load_config()
    assert cfg.trap_port == 4000
    assert cfg.idle_timeout_seconds == 10
    assert cfg.max_session_seconds == 20
    assert cfg.accept_after_attempts == 5
    assert cfg.llm_backend == "openai"
    assert cfg.llm_api_url == "https://llm.example/v1"


@pytest.mark.parametrize("port", ["1", "65535"])
def test_port_boundaries_accepted(env: pytest.MonkeyPatch, port: str) -> None:
    env.setenv("TRAP_PORT", port)
    assert load_config().trap_port == int(port)


def test_directories_created(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    load_config()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "keys").is_dir()


def test_config_is_frozen(env: pytest.MonkeyPatch) -> None:
    cfg = load_config()
    assert isinstance(cfg, Config)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.trap_port = 1  # type: ignore[misc]


@pytest.mark.parametrize("port", ["abc", "", "22.5", "0", "-1", "66000", "65536"])
def test_invalid_port_exits(env: pytest.MonkeyPatch, port: str) -> None:
    env.setenv("TRAP_PORT", port)
    with pytest.raises(SystemExit) as exc:
        load_config()
    assert exc.value.code == 1


@pytest.mark.parametrize("name", ["TRAP_HOST_KEY_PATH", "TRAP_CREDENTIAL_FILE", "TRAP_LOG_DIR"])
@pytest.mark.parametrize("mode", ["empty", "blank", "missing"])
def test_required_paths_exit(env: pytest.MonkeyPatch, name: str, mode: str) -> None:
    if mode == "missing":
        env.delenv(name)
    else:
        env.setenv(name, "" if mode == "empty" else "   ")
    with pytest.raises(SystemExit) as exc:
        load_config()
    assert exc.value.code == 1


@pytest.mark.parametrize(
    "name",
    [
        "TRAP_IDLE_TIMEOUT_SECONDS",
        "TRAP_MAX_SESSION_SECONDS",
        "TRAP_ACCEPT_AFTER_ATTEMPTS",
    ],
)
@pytest.mark.parametrize("value", ["abc", "1.5", "0", "-5"])
def test_invalid_positive_ints_exit(env: pytest.MonkeyPatch, name: str, value: str) -> None:
    env.setenv(name, value)
    with pytest.raises(SystemExit) as exc:
        load_config()
    assert exc.value.code == 1


def test_error_message_written_to_stderr(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.setenv("TRAP_PORT", "0")
    with pytest.raises(SystemExit):
        load_config()
    assert "TRAP_PORT" in capsys.readouterr().err
