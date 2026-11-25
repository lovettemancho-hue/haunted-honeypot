"""Environment-variable configuration loader for the Trap."""

from __future__ import annotations

import dataclasses
import os
import sys
from collections.abc import Mapping
from pathlib import Path

MAX_INPUT_LINE: int = 4096
_LLM_BACKENDS: frozenset[str] = frozenset({"scripted", "gemini"})


class ConfigError(Exception):
    """Raised internally when a configuration value is invalid."""


@dataclasses.dataclass(frozen=True)
class Config:
    trap_port: int  # TRAP_PORT, default 2222
    host_key_path: Path  # TRAP_HOST_KEY_PATH, required
    credential_file: Path  # TRAP_CREDENTIAL_FILE, required
    log_dir: Path  # TRAP_LOG_DIR, required
    idle_timeout_seconds: int  # TRAP_IDLE_TIMEOUT_SECONDS, default 300
    max_session_seconds: int  # TRAP_MAX_SESSION_SECONDS, default 1800
    max_input_line: int  # hard-coded 4096
    accept_after_attempts: int | None  # TRAP_ACCEPT_AFTER_ATTEMPTS, optional
    llm_backend: str  # TRAP_LLM_BACKEND, default "scripted"
    llm_api_url: str | None  # TRAP_LLM_API_URL, optional
    llm_api_key: str = dataclasses.field(default="", repr=False)  # TRAP_LLM_API_KEY
    llm_model: str = ""  # TRAP_LLM_MODEL, required for gemini
    llm_daily_limit: int = 500  # TRAP_LLM_DAILY_LIMIT, default 500


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} must be an integer (got {raw!r})") from None


def _positive_int(name: str, raw: str) -> int:
    value = _parse_int(name, raw)
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer (got {value})")
    return value


def _required_path(env: Mapping[str, str], name: str) -> Path:
    raw = env.get(name, "").strip()
    if not raw:
        raise ConfigError(f"{name} is required and must not be empty")
    return Path(raw)


def _optional(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name, "").strip()
    return raw or None


def _build_config(env: Mapping[str, str]) -> Config:
    port = _parse_int("TRAP_PORT", env.get("TRAP_PORT", "2222"))
    if not 1 <= port <= 65535:
        raise ConfigError(f"TRAP_PORT must be in [1, 65535] (got {port})")

    host_key_path = _required_path(env, "TRAP_HOST_KEY_PATH")
    credential_file = _required_path(env, "TRAP_CREDENTIAL_FILE")
    log_dir = _required_path(env, "TRAP_LOG_DIR")

    idle = _positive_int(
        "TRAP_IDLE_TIMEOUT_SECONDS", env.get("TRAP_IDLE_TIMEOUT_SECONDS", "300")
    )
    max_session = _positive_int(
        "TRAP_MAX_SESSION_SECONDS", env.get("TRAP_MAX_SESSION_SECONDS", "1800")
    )

    accept_raw = _optional(env, "TRAP_ACCEPT_AFTER_ATTEMPTS")
    accept_after = (
        _positive_int("TRAP_ACCEPT_AFTER_ATTEMPTS", accept_raw)
        if accept_raw is not None
        else None
    )

    llm_backend = _optional(env, "TRAP_LLM_BACKEND") or "scripted"
    llm_api_url = _optional(env, "TRAP_LLM_API_URL")
    if llm_backend not in _LLM_BACKENDS:
        raise ConfigError("TRAP_LLM_BACKEND must be one of: scripted, gemini")
    llm_api_key = env.get("TRAP_LLM_API_KEY", "").strip()
    llm_model = env.get("TRAP_LLM_MODEL", "").strip()
    llm_daily_limit = _positive_int(
        "TRAP_LLM_DAILY_LIMIT", env.get("TRAP_LLM_DAILY_LIMIT", "500")
    )
    if llm_backend == "gemini":
        if not llm_api_key:
            raise ConfigError("TRAP_LLM_API_KEY is required when TRAP_LLM_BACKEND is gemini")
        if not llm_model:
            raise ConfigError("TRAP_LLM_MODEL is required when TRAP_LLM_BACKEND is gemini")

    # Host key directory must be writable (the key may be generated there).
    key_parent = host_key_path.parent
    try:
        key_parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(
            f"cannot create host key directory {key_parent}: {exc.strerror}"
        ) from None
    if not os.access(key_parent, os.W_OK):
        raise ConfigError(f"host key directory {key_parent} is not writable")

    # Log directory is created if absent.
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(
            f"cannot create log directory {log_dir}: {exc.strerror}"
        ) from None

    return Config(
        trap_port=port,
        host_key_path=host_key_path,
        credential_file=credential_file,
        log_dir=log_dir,
        idle_timeout_seconds=idle,
        max_session_seconds=max_session,
        max_input_line=MAX_INPUT_LINE,
        accept_after_attempts=accept_after,
        llm_backend=llm_backend,
        llm_api_url=llm_api_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_daily_limit=llm_daily_limit,
    )


def load_config() -> Config:
    """Load and validate configuration from the environment.

    On any validation failure, writes a descriptive message to stderr and
    exits with status 1. Values are never echoed for secret-bearing settings.
    """
    try:
        return _build_config(os.environ)
    except ConfigError as exc:
        print(f"trap configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
