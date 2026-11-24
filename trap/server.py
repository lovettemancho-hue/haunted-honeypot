"""The Trap: an asyncssh server that accepts weak logins and hands off to the Ghost Shell.

Attacker input is data only. Nothing here executes, evaluates or fetches
anything the attacker sends; credentials are compared against an in-memory set.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import asyncssh

from trap.auth.credentials import parse_credentials
from trap.auth.tracker import AttemptTracker
from trap.config import Config
from trap.ghost.dispatcher import Dispatcher, build_default_dispatcher
from trap.ghost.filesystem import FakeFilesystem, FakeNode, load_template
from trap.ghost.llm import ScriptedFallback
from trap.ghost.logger import EventLogger
from trap.models import Event, GeneratedBy, Session, SessionEndReason

_log = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).parent / "ghost" / "fs_template.yaml"
_DEFAULT_MAX_ATTEMPTS_PER_IP = 101

# Seam for the Ghost Shell session coroutine (``trap.ghost.shell.run_shell``).
# Tests inject a stub; the default is resolved lazily so this module does not
# depend on shell.py at import time.
ShellHandler = Callable[
    [
        asyncssh.SSHServerProcess[str],
        Config,
        Session,
        FakeFilesystem,
        Dispatcher,
        EventLogger,
    ],
    Awaitable[None],
]


def default_shell_handler() -> ShellHandler:
    """Resolve ``trap.ghost.shell.run_shell`` on first use."""
    module = importlib.import_module("trap.ghost.shell")
    return cast(ShellHandler, module.run_shell)


@dataclass
class _Shared:
    """State shared by all connections of one server instance."""

    config: Config
    creds: frozenset[tuple[str, str]]
    tracker: AttemptTracker
    template: FakeNode
    shell_handler: ShellHandler | None  # None -> resolve default lazily
    servers: dict[object, TrapServer] = field(default_factory=dict)


# Strong references so fire-and-forget close tasks are not garbage collected.
_background: set[asyncio.Task[None]] = set()


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _event(
    session_id: str,
    kind: str,
    payload: dict[str, object],
    generated_by: GeneratedBy = "scripted",
) -> Event:
    return Event(
        session_id=session_id,
        timestamp=_utc_now_iso(),
        kind=kind,  # type: ignore[arg-type]
        payload=payload,
        generated_by=generated_by,
    )


class TrapServer(asyncssh.SSHServer):
    """One instance per inbound connection."""

    def __init__(self, shared: _Shared) -> None:
        self._shared = shared
        self._conn: asyncssh.SSHServerConnection | None = None
        self._session_id: str = uuid.uuid4().hex
        self._logger: EventLogger | None = None
        self._open_task: asyncio.Task[None] | None = None
        self._shell_took_over: bool = False
        self._shell_started: bool = False
        self._src_ip: str = ""
        self._src_port: int = 0
        self._username: str = ""
        self._password: str = ""
        self._started_at: datetime = datetime.now(UTC)

    # -- helpers ---------------------------------------------------------

    def _client_version(self) -> str:
        if self._conn is None:
            return ""
        # Not yet known inside connection_made (version exchange follows).
        return str(self._conn.get_extra_info("client_version") or "")

    async def _open_logger_and_start(self) -> None:
        """Open the session log and write ``session_start`` (Req 9.5 on failure)."""
        try:
            logger = EventLogger(self._session_id, self._shared.config.log_dir)
            await logger.__aenter__()
            self._logger = logger
            await logger.write(
                _event(
                    self._session_id,
                    "session_start",
                    {
                        "src_ip": self._src_ip,
                        "src_port": self._src_port,
                        "client_version": self._client_version(),
                    },
                )
            )
        except OSError:
            _log.error("session %s: cannot open session log, closing", self._session_id)
            if self._logger is not None:
                with contextlib.suppress(OSError):
                    await self._logger.close()
                self._logger = None
            if self._conn is not None:
                self._conn.abort()

    async def _write(self, event: Event) -> bool:
        """Write an event; return False if no logger or the write failed."""
        if self._open_task is not None:
            await self._open_task
        if self._logger is None:
            return False
        try:
            await self._logger.write(event)
        except OSError:
            return False
        return True

    async def _finish_disconnected(self) -> None:
        reason: SessionEndReason = "disconnect"
        try:
            await self._write(_event(self._session_id, "session_end", {"reason": reason}))
        finally:
            if self._logger is not None:
                with contextlib.suppress(OSError):
                    await self._logger.close()

    # -- asyncssh callbacks ---------------------------------------------

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self._conn = conn
        self._shared.servers[conn] = self
        peer = conn.get_extra_info("peername")
        if isinstance(peer, tuple) and len(peer) >= 2:
            self._src_ip = str(peer[0])
            self._src_port = int(peer[1])
        self._started_at = datetime.now(UTC)
        self._open_task = asyncio.ensure_future(self._open_logger_and_start())

    def connection_lost(self, exc: Exception | None) -> None:
        if self._conn is not None:
            self._shared.servers.pop(self._conn, None)
        if self._shell_took_over and self._shell_started:
            return  # the shell closes the logger
        task = asyncio.ensure_future(self._finish_disconnected())
        _background.add(task)
        task.add_done_callback(_background.discard)

    def password_auth_supported(self) -> bool:
        return True

    async def validate_password(self, username: str, password: str) -> bool:
        return await self.password_auth_requested(username, password)

    async def password_auth_requested(self, username: str, password: str) -> bool:
        """Decide and log one password attempt.

        Async (unlike the sync signature sketched in the design) because the
        ``login_attempt`` event is written through the async logger.
        """
        shared = self._shared
        tracker = shared.tracker
        tracker.record_attempt(self._src_ip)

        accepted = (username, password) in shared.creds
        threshold = shared.config.accept_after_attempts
        if (
            not accepted
            and threshold is not None
            and tracker.should_accept(self._src_ip, threshold)
        ):
            accepted = True

        if accepted:
            self._username = username
            self._password = password
            self._shell_took_over = True

        ok = await self._write(
            _event(
                self._session_id,
                "login_attempt",
                {
                    "src_ip": self._src_ip,
                    "src_port": self._src_port,
                    "username": username,
                    "password": password,
                    "client_version": self._client_version(),
                    "success": accepted,
                },
            )
        )
        if not ok:
            # Non-fatal per Req 2.5.
            _log.error("session %s: login_attempt event not logged", self._session_id)
        return accepted

    async def handle_process(self, process: asyncssh.SSHServerProcess[str]) -> None:
        shared = self._shared
        if self._open_task is not None:
            await self._open_task
        logger = self._logger
        if logger is None or not self._shell_took_over:
            process.exit(1)
            return
        self._shell_started = True
        session = Session(
            session_id=self._session_id,
            src_ip=self._src_ip,
            src_port=self._src_port,
            username=self._username,
            password=self._password,
            client_version=self._client_version(),
            started_at=self._started_at,
        )
        fs = FakeFilesystem(shared.template)
        dispatcher = build_default_dispatcher(ScriptedFallback())
        try:
            handler = shared.shell_handler or default_shell_handler()
            await handler(process, shared.config, session, fs, dispatcher, logger)
        except Exception:
            _log.exception("session %s: shell crashed", self._session_id)
        finally:
            with contextlib.suppress(OSError):
                await logger.close()
            process.exit(0)


def _load_host_key(path: Path) -> asyncssh.SSHKey:
    """Load the Ed25519 host key, generating and persisting it if absent."""
    if path.exists():
        return asyncssh.read_private_key(str(path))
    key = asyncssh.generate_private_key("ssh-ed25519")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key.export_private_key())
    return key


async def _process_factory_for(shared: _Shared, process: asyncssh.SSHServerProcess[str]) -> None:
    """Route a new shell process to the TrapServer that owns its connection."""
    server = shared.servers.get(process.channel.get_connection())
    if server is None:
        process.exit(1)
        return
    await server.handle_process(process)


async def create_trap_server(
    config: Config, shell_handler: ShellHandler | None = None
) -> asyncssh.SSHAcceptor:
    """Create the listening server without blocking (used by tests)."""
    creds = frozenset(parse_credentials(config.credential_file.read_text(encoding="utf-8")))
    max_per_ip = (
        config.accept_after_attempts + 1
        if config.accept_after_attempts is not None
        else _DEFAULT_MAX_ATTEMPTS_PER_IP
    )
    shared = _Shared(
        config=config,
        creds=creds,
        tracker=AttemptTracker(max_attempts_per_ip=max_per_ip),
        template=load_template(_TEMPLATE_PATH),
        shell_handler=shell_handler,
    )
    host_key = _load_host_key(config.host_key_path)
    return await asyncssh.create_server(
        lambda: TrapServer(shared),
        "",
        config.trap_port,
        process_factory=lambda p: _process_factory_for(shared, p),
        server_host_keys=[host_key],
        # Password auth only; everything else stays at asyncssh's defaults (off).
    )


async def start_server(config: Config, shell_handler: ShellHandler | None = None) -> None:
    """Start the Trap and serve until cancelled."""
    acceptor = await create_trap_server(config, shell_handler)
    _log.info("trap listening on port %d", config.trap_port)
    try:
        await acceptor.wait_closed()
    finally:
        acceptor.close()
