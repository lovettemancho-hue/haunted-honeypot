"""Command dispatcher and chain tokeniser for the Ghost Shell.

Attacker input is data only: it is tokenised in pure Python and looked up in a
registry of handlers. Nothing here spawns processes or evaluates code.

``generated_by`` tracking (used by ``shell.py`` when logging the response
event): every :class:`CommandResult` carries ``generated_by`` (``"scripted"``
by default; for unhandled commands it is the ``source`` of the
``LLMReply`` returned by ``LLMInterface.respond``). After
each :meth:`Dispatcher.dispatch` call, :attr:`Dispatcher.last_generated_by` is
``"llm"`` if any part of that input was answered by the LLM, else
``"scripted"``. Use one dispatcher per session so the attribute is not shared.
"""

from __future__ import annotations

import logging
import posixpath
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trap.ghost.llm import LLMInterface
    from trap.models import SessionContext

logger = logging.getLogger(__name__)

# Upper bound on LLM text returned to the attacker (security: length-capped).
MAX_LLM_OUTPUT_CHARS = 4096


@dataclass
class CommandResult:
    """Output of one command. ``is_error`` is used by the ``&&`` operator."""

    output: str
    is_error: bool
    generated_by: str = "scripted"  # "scripted" | "llm"


HandlerFn = Callable[[list[str], "SessionContext"], Awaitable[CommandResult]]


class Dispatcher:
    """Registry of command handlers plus the ``;`` / ``&&`` / ``|`` chain runner."""

    def __init__(self, llm: LLMInterface) -> None:
        self._llm = llm
        self._handlers: dict[str, HandlerFn] = {}
        self.last_generated_by: str = "scripted"

    def register(self, name: str, handler: HandlerFn) -> None:
        self._handlers[name] = handler

    # ------------------------------------------------------------------ chain

    def _tokenise_chain(self, raw: str) -> list[tuple[str, list[str]]]:
        """Split ``raw`` into ``(operator, tokens)`` segments.

        The operator is ``";"``, ``"&&"`` or ``"|"`` (how the segment is joined
        to the previous one) and ``""`` for the first segment. Quotes (single
        or double) group words and hide operators; an unterminated quote runs
        to the end of input. Segments with no tokens are dropped.
        """
        segments: list[tuple[str, list[str]]] = []
        tokens: list[str] = []
        word: list[str] = []
        in_word = False
        quote = ""
        pending_op = ""

        def end_word() -> None:
            nonlocal in_word
            if in_word:
                tokens.append("".join(word))
                word.clear()
                in_word = False

        def end_segment(next_op: str) -> None:
            nonlocal tokens, pending_op
            end_word()
            if tokens:
                segments.append((pending_op, tokens))
                tokens = []
                pending_op = next_op
            elif not segments:
                pending_op = ""
            else:
                # Empty segment (e.g. ";;"): the latest operator wins.
                pending_op = next_op

        i = 0
        n = len(raw)
        while i < n:
            ch = raw[i]
            if quote:
                if ch == quote:
                    quote = ""
                else:
                    word.append(ch)
            elif ch in ("'", '"'):
                quote = ch
                in_word = True
            elif ch.isspace():
                end_word()
            elif ch == ";":
                end_segment(";")
            elif ch == "&" and raw[i + 1 : i + 2] == "&":
                end_segment("&&")
                i += 1
            elif ch == "|":
                end_segment("|")
            else:
                word.append(ch)
                in_word = True
            i += 1
        end_segment("")
        return segments

    async def dispatch(self, raw_input: str, ctx: SessionContext) -> str:
        """Run one line of attacker input and return the text to show.

        Never raises, except :class:`SessionExitRequested` (from ``exit``),
        which propagates so the shell can close the session.
        """
        self.last_generated_by = "scripted"
        outputs: list[str] = []
        prev_error = False
        skipped = False
        last_index: int | None = None  # index in ``outputs`` of previous segment

        for op, tokens in self._tokenise_chain(raw_input):
            if op in ("", ";"):
                skipped = False
            elif op == "&&":
                if skipped or prev_error:
                    skipped = True
                    continue
            elif op == "|" and skipped:
                continue

            run_tokens = tokens
            if op == "|" and last_index is not None:
                left = outputs[last_index]
                run_tokens = [*tokens, left] if left else tokens
                outputs[last_index] = ""

            result = await self._dispatch_single(run_tokens, ctx)
            if result.generated_by == "llm":
                self.last_generated_by = "llm"
            prev_error = result.is_error
            if op == "|" and last_index is not None:
                outputs[last_index] = result.output
            else:
                outputs.append(result.output)
                last_index = len(outputs) - 1

        return "\n".join(o for o in outputs if o)

    # ----------------------------------------------------------------- single

    async def _dispatch_single(
        self, tokens: list[str], ctx: SessionContext
    ) -> CommandResult:
        # Imported lazily: exit_ imports CommandResult from this module.
        from trap.ghost.commands.exit_ import SessionExitRequested

        if not tokens:
            return CommandResult(output="", is_error=False)
        name = tokens[0]

        # Path execution is checked before the registry.
        if name.startswith(("./", "/")):
            base = posixpath.basename(name.rstrip("/"))
            if base in ctx.downloaded_files:
                return CommandResult("Segmentation fault (core dumped)", True)
            return CommandResult(f"bash: {name}: No such file or directory", True)

        handler = self._handlers.get(name)
        if handler is not None:
            try:
                return await handler(tokens[1:], ctx)
            except SessionExitRequested:
                raise
            except Exception:
                logger.exception("handler for %r raised", name)
                return CommandResult(output="", is_error=True)

        fallback = f"bash: {name}: command not found"
        try:
            reply = await self._llm.respond(ctx, " ".join(tokens))
        except Exception:
            logger.error("LLM respond failed for %r", name, exc_info=True)
            return CommandResult(fallback, True)
        return CommandResult(
            output=str(reply.text)[:MAX_LLM_OUTPUT_CHARS],
            is_error=False,
            generated_by=reply.source,
        )


def build_default_dispatcher(llm: LLMInterface) -> Dispatcher:
    """Create a :class:`Dispatcher` with all built-in command handlers.

    Command modules are imported here (not at module level) because they
    import ``CommandResult`` from this module.
    """
    from trap.ghost.commands.download import curl, wget
    from trap.ghost.commands.exit_ import exit_command
    from trap.ghost.commands.files import cat, chmod, mkdir, rm, touch
    from trap.ghost.commands.history import history
    from trap.ghost.commands.info import echo, hostname, id_, uname, whoami
    from trap.ghost.commands.navigation import cd, ls, pwd

    dispatcher = Dispatcher(llm)
    for name, handler in (
        ("pwd", pwd),
        ("cd", cd),
        ("ls", ls),
        ("cat", cat),
        ("touch", touch),
        ("rm", rm),
        ("mkdir", mkdir),
        ("chmod", chmod),
        ("whoami", whoami),
        ("id", id_),
        ("uname", uname),
        ("hostname", hostname),
        ("echo", echo),
        ("history", history),
        ("wget", wget),
        ("curl", curl),
        ("exit", exit_command),
    ):
        dispatcher.register(name, handler)
    return dispatcher
