"""The ``exit`` command: signals the shell loop to close the session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trap.ghost.dispatcher import CommandResult

if TYPE_CHECKING:
    from trap.models import SessionContext


class SessionExitRequested(Exception):  # noqa: N818 - name fixed by design
    """Sentinel raised by ``exit``; caught by ``shell.py`` to close the session."""


async def exit_command(args: list[str], ctx: SessionContext) -> CommandResult:
    """Raise :class:`SessionExitRequested`; never returns normally."""
    raise SessionExitRequested
