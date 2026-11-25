"""Environment-variable configuration for the Brain service."""

from __future__ import annotations

import dataclasses
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_PATH = "brain.db"
DEFAULT_LLM_MODEL = "gemini-1.5-flash"
INGEST_INTERVAL_SECONDS = 10


@dataclasses.dataclass(frozen=True)
class Config:
    """Typed Brain configuration. Secrets are excluded from ``repr``."""

    log_dir: Path
    api_token: str = dataclasses.field(repr=False)
    database_path: Path = Path(DEFAULT_DATABASE_PATH)
    llm_api_key: str | None = dataclasses.field(default=None, repr=False)
    llm_model: str = DEFAULT_LLM_MODEL
    ingest_interval_seconds: int = INGEST_INTERVAL_SECONDS


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.strip():
        logger.error("Required environment variable %s is not set or empty", name)
        sys.exit(1)
    return value


def load_config() -> Config:
    """Build a Config from environment variables only.

    Exits the process with status 1 (logging only the variable name) if
    ``BRAIN_LOG_DIR`` or ``BRAIN_API_TOKEN`` is missing or empty.
    """
    log_dir = _require("BRAIN_LOG_DIR")
    api_token = _require("BRAIN_API_TOKEN")
    database_path = os.environ.get("BRAIN_DATABASE_PATH", "").strip() or DEFAULT_DATABASE_PATH
    llm_api_key = os.environ.get("BRAIN_LLM_API_KEY", "").strip() or None
    llm_model = os.environ.get("BRAIN_LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL
    return Config(
        log_dir=Path(log_dir),
        api_token=api_token,
        database_path=Path(database_path),
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        ingest_interval_seconds=INGEST_INTERVAL_SECONDS,
    )
