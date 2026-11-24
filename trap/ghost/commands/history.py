"""The ``history`` command: lists the commands entered in this session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from trap.ghost.dispatcher import CommandResult

if TYPE_CHECKING:
    from trap.models import SessionContext


async def history(args: list[str], ctx: SessionContext) -> CommandResult:
    """Return ``ctx.history`` as a 1-indexed numbered list, one entry per line."""
    lines = [f"{i:>5}  {cmd}" for i, cmd in enumerate(ctx.history, start=1)]
    return CommandResult(output="\n".join(lines), is_error=False)
