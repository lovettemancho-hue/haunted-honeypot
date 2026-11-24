"""Entry point: ``python -m trap``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from trap.config import load_config
from trap.server import start_server

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, stream=sys.stderr)
    # asyncssh's INFO output includes per-connection auth detail; keep it quiet.
    logging.getLogger("asyncssh").setLevel(logging.WARNING)


def main() -> int:
    """Load config, run the trap until interrupted, return the exit status."""
    _configure_logging()
    config = load_config()  # exits with status 1 on invalid configuration
    log = logging.getLogger("trap")
    try:
        with contextlib.suppress(asyncio.CancelledError):
            asyncio.run(start_server(config))
    except KeyboardInterrupt:
        log.info("interrupted, shutting down")
    except OSError as exc:
        # e.g. port already in use, host key unreadable. No secrets in the message.
        log.error("trap failed to start: %s", exc.strerror or type(exc).__name__)
        return 1
    log.info("trap stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
