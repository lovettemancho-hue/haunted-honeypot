"""LLM interface for the Ghost Shell.

Output from any implementation is plain text. It is returned to the attacker
as-is and is never executed or interpreted.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trap.models import SessionContext


class LLMInterface(abc.ABC):
    """Produces a shell response for a command the registry does not handle."""

    @abc.abstractmethod
    async def respond(self, session_context: SessionContext, command: str) -> str:
        """Return plain-text shell output for ``command``."""


class ScriptedFallback(LLMInterface):
    """Deterministic backend: every unknown command is 'command not found'."""

    async def respond(self, session_context: SessionContext, command: str) -> str:
        tokens = command.split()
        cmd = tokens[0] if tokens else command
        return f"bash: {cmd}: command not found"
