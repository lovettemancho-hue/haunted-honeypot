"""``python -m brain`` entry point."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "brain.main:create_app",
        factory=True,
        host=os.environ.get("BRAIN_HOST", "0.0.0.0"),  # noqa: S104  # nosec B104 - container
        port=int(os.environ.get("BRAIN_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
