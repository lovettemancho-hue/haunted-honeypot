"""Unit tests for trap.ghost.logger.EventLogger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trap.ghost.logger import EventLogger
from trap.models import Event


def _event(session_id: str = "abc123", cmd: str = "ls") -> Event:
    return Event(
        session_id=session_id,
        timestamp="2024-01-15T10:23:45.123456Z",
        kind="command",
        payload={"command": cmd},
        generated_by="scripted",
    )


async def test_write_appends_valid_json_lines(tmp_path: Path) -> None:
    async with EventLogger("abc123", tmp_path) as lg:
        await lg.write(_event(cmd="ls"))
        await lg.write(_event(cmd="héllo \u2603"))

    lines = (tmp_path / "abc123.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first, second = (json.loads(x) for x in lines)
    assert first["kind"] == "command"
    assert first["payload"] == {"command": "ls"}
    assert first["session_id"] == "abc123"
    assert first["generated_by"] == "scripted"
    assert second["payload"]["command"] == "héllo \u2603"


async def test_write_appends_to_existing_file(tmp_path: Path) -> None:
    async with EventLogger("abc123", tmp_path) as lg:
        await lg.write(_event(cmd="one"))
    async with EventLogger("abc123", tmp_path) as lg:
        await lg.write(_event(cmd="two"))
    assert len((tmp_path / "abc123.jsonl").read_text().splitlines()) == 2


async def test_creates_missing_log_dir(tmp_path: Path) -> None:
    log_dir = tmp_path / "nested" / "logs"
    async with EventLogger("abc123", log_dir) as lg:
        await lg.write(_event())
    assert (log_dir / "abc123.jsonl").exists()


async def test_write_flushes_after_each_write(tmp_path: Path) -> None:
    async with EventLogger("abc123", tmp_path) as lg:
        await lg.write(_event(cmd="first"))
        # Data must be on disk before close, i.e. flushed per write.
        on_disk = (tmp_path / "abc123.jsonl").read_text(encoding="utf-8")
        assert json.loads(on_disk.splitlines()[0])["payload"] == {"command": "first"}
        await lg.write(_event(cmd="second"))
        assert len((tmp_path / "abc123.jsonl").read_text().splitlines()) == 2


async def test_write_reraises_oserror(tmp_path: Path) -> None:
    lg = EventLogger("abc123", tmp_path)
    async with lg:
        assert lg._file is not None

        class _Broken:
            async def write(self, _: str) -> int:
                raise OSError("disk full")

            async def flush(self) -> None:
                return None

            async def close(self) -> None:
                return None

        real = lg._file
        lg._file = _Broken()  # type: ignore[assignment]
        with pytest.raises(OSError, match="disk full"):
            await lg.write(_event())
        lg._file = real


async def test_write_before_open_raises_oserror(tmp_path: Path) -> None:
    lg = EventLogger("abc123", tmp_path)
    with pytest.raises(OSError):
        await lg.write(_event())


async def test_aexit_closes_file(tmp_path: Path) -> None:
    lg = EventLogger("abc123", tmp_path)
    async with lg:
        f = lg._file
        assert f is not None
        assert not f.closed
    assert f.closed
    assert lg._file is None


async def test_aexit_closes_file_on_exception(tmp_path: Path) -> None:
    lg = EventLogger("abc123", tmp_path)
    with pytest.raises(RuntimeError):
        async with lg:
            f = lg._file
            raise RuntimeError("boom")
    assert f is not None and f.closed


async def test_close_is_idempotent(tmp_path: Path) -> None:
    lg = EventLogger("abc123", tmp_path)
    async with lg:
        pass
    await lg.close()


def test_path_property(tmp_path: Path) -> None:
    assert EventLogger("abc-123_X", tmp_path).path == tmp_path / "abc-123_X.jsonl"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "../evil",
        "..",
        "a/b",
        "a\\b",
        "/etc/passwd",
        "id.with.dots",
        "has space",
        "nul\x00byte",
        "x" * 65,
        "new\nline",
    ],
)
def test_unsafe_session_id_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        EventLogger(bad, tmp_path)


@pytest.mark.parametrize("good", ["a", "0123456789abcdef" * 2, "A-b_9", "x" * 64])
def test_safe_session_id_accepted(tmp_path: Path, good: str) -> None:
    assert EventLogger(good, tmp_path).path.parent == tmp_path
