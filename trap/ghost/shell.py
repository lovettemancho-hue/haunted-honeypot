"""Ghost Shell session: MOTD, prompt loop, session limits and event logging.

Attacker input is data only. It is tokenised and answered by the dispatcher
against an in-memory filesystem; nothing here executes or fetches anything.

``TrapServer`` has already opened the ``EventLogger`` and written
``session_start`` and ``login_attempt``. This module never opens or closes the
logger; it writes ``command``, ``response``, ``download_attempt`` and the final
``session_end`` event.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

import asyncssh

from trap.config import Config
from trap.ghost.commands.exit_ import SessionExitRequested
from trap.ghost.commands.navigation import home_dir
from trap.ghost.dispatcher import Dispatcher
from trap.ghost.filesystem import FakeFilesystem
from trap.ghost.logger import EventLogger
from trap.models import Event, GeneratedBy, Session, SessionContext, SessionEndReason

_log = logging.getLogger(__name__)

HOSTNAME = "records-srv-09"

MOTD = (
    "\n"
    f"Welcome to {HOSTNAME}\n"
    "Municipal Records Archive - DECOMMISSIONED. Scheduled for shutdown 2013.\n"
    "Last login: Thu Oct 31 23:47:12 2013 from console (Caretaker H.)\n"
    "Notice: the caretaker has not been seen since. The lights still flicker "
    "in the vault.\n"
    "\n"
)

LINE_TOO_LONG = "bash: line too long"


class _LogFailure(Exception):
    """The session log could not be written (Req 9.5)."""


def build_prompt(username: str, cwd: str) -> str:
    """Return the shell prompt, e.g. ``[root@records-srv-09 ~]# ``."""
    home = home_dir(username)
    if cwd == home:
        display = "~"
    elif cwd.startswith(home + "/"):
        display = "~" + cwd[len(home) :]
    else:
        display = cwd
    sigil = "#" if username == "root" else "$"
    return f"[{username}@{HOSTNAME} {display}]{sigil} "


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _event(
    session_id: str,
    kind: str,
    payload: dict[str, object],
    generated_by: GeneratedBy = "scripted",
) -> Event:
    return Event(
        session_id=session_id,
        timestamp=_now_iso(),
        kind=kind,  # type: ignore[arg-type]
        payload=payload,
        generated_by=generated_by,
    )


def _to_terminal(text: str) -> str:
    """Normalise line endings to ``\\n``.

    asyncssh's line editor converts ``\\n`` to ``\\r\\n`` on pty channels, so
    sending bare ``\\n`` yields correct CRLF there and plain LF elsewhere.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


async def _log_write(logger: EventLogger, event: Event) -> None:
    try:
        await logger.write(event)
    except OSError as exc:
        raise _LogFailure from exc


async def _loop(
    process: asyncssh.SSHServerProcess[str],
    config: Config,
    ctx: SessionContext,
    dispatcher: Dispatcher,
    logger: EventLogger,
) -> SessionEndReason:
    session_id = ctx.session.session_id
    username = ctx.session.username
    while True:
        process.stdout.write(build_prompt(username, ctx.fs.cwd_path()))
        try:
            line = await asyncio.wait_for(
                process.stdin.readline(), timeout=config.idle_timeout_seconds
            )
        except TimeoutError:
            return "idle_timeout"
        except (
            asyncssh.BreakReceived,
            asyncssh.SignalReceived,
            asyncssh.TerminalSizeChanged,
        ):
            process.stdout.write("\n")
            continue
        if not line:  # EOF: client closed its side
            return "disconnect"

        command = line.rstrip("\r\n")
        if len(command) > config.max_input_line:
            process.stdout.write(LINE_TOO_LONG + "\n")
            continue
        if not command.strip():
            continue

        await _log_write(logger, _event(session_id, "command", {"command": command}))
        try:
            output = await dispatcher.dispatch(command, ctx)
        except SessionExitRequested:
            ctx.history.append(command)
            await _drain(ctx, logger)
            return "exit"
        ctx.history.append(command)
        generated_by: GeneratedBy = "llm" if dispatcher.last_generated_by == "llm" else "scripted"
        await _log_write(
            logger,
            _event(session_id, "response", {"output": output}, generated_by),
        )
        await _drain(ctx, logger)
        if output:
            process.stdout.write(_to_terminal(output).rstrip("\n") + "\n")


async def _drain(ctx: SessionContext, logger: EventLogger) -> None:
    pending, ctx.pending_events = ctx.pending_events, []
    for event in pending:
        await _log_write(logger, event)


async def run_shell(
    process: asyncssh.SSHServerProcess[str],
    config: Config,
    session: Session,
    fs: FakeFilesystem,
    dispatcher: Dispatcher,
    logger: EventLogger,
) -> None:
    """Run one interactive session until exit, timeout, disconnect or log failure."""
    home = home_dir(session.username)
    node = fs.resolve(home)
    if node is not None and node.is_dir:
        fs.cd(home)
    ctx = SessionContext(session=session, fs=fs, history=[], config=config)

    reason: SessionEndReason = "disconnect"
    try:
        async with asyncio.timeout(config.max_session_seconds):
            process.stdout.write(_to_terminal(MOTD))
            reason = await _loop(process, config, ctx, dispatcher, logger)
    except TimeoutError:
        reason = "max_duration"
    except _LogFailure:
        reason = "log_error"
        _log.error("session %s: session log write failed, closing", session.session_id)
        with contextlib.suppress(Exception):
            process.stdout.write("Connection closed by remote host: internal error\n")
    except Exception:
        _log.exception("session %s: shell loop failed", session.session_id)
        reason = "disconnect"

    session.ended_at = datetime.now(UTC)
    try:
        await logger.write(_event(session.session_id, "session_end", {"reason": reason}))
    except OSError:
        _log.error("session %s: could not write session_end", session.session_id)
