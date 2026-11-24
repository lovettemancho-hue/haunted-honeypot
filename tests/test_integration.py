"""End-to-end smoke test: real asyncssh client against the real Trap."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import asyncssh

from trap.config import MAX_INPUT_LINE, Config
from trap.server import create_trap_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _make_config(tmp_path: Path) -> Config:
    creds = tmp_path / "creds.txt"
    creds.write_text("root:root\n", encoding="utf-8")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return Config(
        trap_port=_free_port(),
        host_key_path=tmp_path / "host_key",
        credential_file=creds,
        log_dir=log_dir,
        idle_timeout_seconds=30,
        max_session_seconds=60,
        max_input_line=MAX_INPUT_LINE,
        accept_after_attempts=None,
        llm_backend="scripted",
        llm_api_url=None,
    )


async def _run_command(process: asyncssh.SSHClientProcess[str], command: str) -> list[str]:
    """Send one command and return its output lines (echo and prompt removed)."""
    process.stdin.write(command + "\n")
    chunk = str(await process.stdout.readuntil("# "))
    lines = chunk.replace("\r\n", "\n").split("\n")
    assert lines[-1].endswith("# ")  # trailing prompt
    lines = lines[:-1]
    if lines and lines[0].endswith(command):  # pty line editor echo
        lines = lines[1:]
    return lines


async def _session(config: Config) -> tuple[str, list[str], list[str]]:
    async with asyncssh.connect(
        "127.0.0.1",
        config.trap_port,
        username="root",
        password="root",
        known_hosts=None,
    ) as conn:
        process = await conn.create_process(term_type="xterm")
        motd = str(await process.stdout.readuntil("# "))
        pwd_out = await _run_command(process, "pwd")
        whoami_out = await _run_command(process, "whoami")
        process.stdin.write("exit\n")
        await process.wait_closed()
        return motd, pwd_out, whoami_out


async def test_ssh_session_end_to_end(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    acceptor = await create_trap_server(config)
    try:
        motd, pwd_out, whoami_out = await asyncio.wait_for(_session(config), timeout=15)
    finally:
        acceptor.close()
        await asyncio.wait_for(acceptor.wait_closed(), timeout=15)

    assert "records-srv-09" in motd
    assert pwd_out == ["/root"]
    assert whoami_out == ["root"]
    # Allow the server a moment to flush the final events.
    log_files: list[Path] = []
    for _ in range(50):
        log_files = list(config.log_dir.glob("*.jsonl"))
        if log_files and '"session_end"' in log_files[0].read_text(encoding="utf-8"):
            break
        await asyncio.sleep(0.1)
    assert len(log_files) == 1
    events = [
        json.loads(line) for line in log_files[0].read_text(encoding="utf-8").splitlines() if line
    ]
    kinds = [e["kind"] for e in events]
    assert "session_start" in kinds
    assert "login_attempt" in kinds
    commands = [e["payload"] for e in events if e["kind"] == "command"]
    assert len(commands) >= 1
    assert kinds[-1] == "session_end"
    assert events[-1]["payload"]["reason"] == "exit"
