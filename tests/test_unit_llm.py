"""Unit tests for the LLM interface and ScriptedFallback (Requirements 7.3, 7.5)."""

from __future__ import annotations

import importlib.util
import logging
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from trap.ghost.llm import LLMInterface, LLMReply, ScriptedFallback
from trap.models import Session, SessionContext


def _ctx() -> SessionContext:
    session = Session(
        session_id="abc",
        src_ip="203.0.113.7",
        src_port=40000,
        username="root",
        password="root",
        client_version="SSH-2.0-test",
        started_at=datetime.now(UTC),
    )
    # fs and config are not used by the LLM interface under test.
    return SessionContext(
        session=session, fs=cast(Any, None), history=[], config=cast(Any, None)
    )


async def test_scripted_fallback_uses_first_token() -> None:
    result = await ScriptedFallback().respond(_ctx(), "nmap -sV 10.0.0.1")
    assert result == LLMReply("bash: nmap: command not found", "scripted")


async def test_scripted_fallback_single_token() -> None:
    result = await ScriptedFallback().respond(_ctx(), "foo")
    assert result == LLMReply("bash: foo: command not found", "scripted")


async def test_scripted_fallback_ignores_extra_whitespace() -> None:
    result = await ScriptedFallback().respond(_ctx(), "   foo   bar  ")
    assert result == LLMReply("bash: foo: command not found", "scripted")


async def test_scripted_fallback_whitespace_only_uses_whole_string() -> None:
    result = await ScriptedFallback().respond(_ctx(), "   ")
    assert result == LLMReply("bash:    : command not found", "scripted")


def test_llm_interface_is_abstract() -> None:
    with pytest.raises(TypeError):
        LLMInterface()  # type: ignore[abstract]


# The dispatcher is implemented in task 9. These tests exercise the contract
# from design.md ("dispatcher calls llm.respond() for commands not in the
# registry; on exception it logs and returns the command-not-found fallback")
# and are skipped until trap.ghost.dispatcher exists.
_HAS_DISPATCHER = importlib.util.find_spec("trap.ghost.dispatcher") is not None
needs_dispatcher = pytest.mark.skipif(
    not _HAS_DISPATCHER, reason="trap.ghost.dispatcher not implemented yet (task 9)"
)


class _RecordingLLM(LLMInterface):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def respond(self, session_context: SessionContext, command: str) -> LLMReply:
        self.calls.append(command)
        return LLMReply("stitched output", "llm")


class _RaisingLLM(LLMInterface):
    async def respond(self, session_context: SessionContext, command: str) -> LLMReply:
        raise RuntimeError("llm down")


@needs_dispatcher
async def test_dispatcher_calls_llm_for_unregistered_command() -> None:
    from trap.ghost.dispatcher import Dispatcher

    llm = _RecordingLLM()
    out = await Dispatcher(llm).dispatch("frobnicate --now", _ctx())
    assert llm.calls and llm.calls[0].startswith("frobnicate")
    assert "stitched output" in out


@needs_dispatcher
async def test_dispatcher_falls_back_and_logs_when_llm_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from trap.ghost.dispatcher import Dispatcher

    with caplog.at_level(logging.ERROR):
        out = await Dispatcher(_RaisingLLM()).dispatch("frobnicate", _ctx())
    assert out.strip() == "bash: frobnicate: command not found"
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
