"""Property tests for the offset-based Session_Log reader."""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from brain.ingest.reader import read_new_events

_KINDS = [
    "session_start",
    "login_attempt",
    "command",
    "response",
    "download_attempt",
    "session_end",
]

_line_dicts = st.fixed_dictionaries(
    {
        "session_id": st.text(
            alphabet=st.characters(min_codepoint=48, max_codepoint=122, categories=["L", "N"]),
            min_size=1,
            max_size=12,
        ),
        "timestamp": st.datetimes().map(lambda d: d.isoformat()),
        "kind": st.sampled_from(_KINDS),
        "payload": st.dictionaries(st.text(max_size=8), st.text(max_size=40), max_size=3),
    }
)

# A trailing partial line: arbitrary bytes that contain no newline.
_partials = st.binary(max_size=40).map(lambda b: b.replace(b"\n", b""))


def _encode(line: dict[str, Any]) -> bytes:
    # json.dumps escapes newlines inside strings, so each line is exactly one physical line.
    return json.dumps(line).encode("utf-8") + b"\n"


@st.composite
def _content_with_offset(draw: st.DrawFn) -> tuple[list[dict[str, Any]], bytes, int, int, int, int]:
    lines = draw(st.lists(_line_dicts, max_size=15))
    partial = draw(_partials)
    split = draw(st.integers(min_value=0, max_value=len(lines)))
    start_line = draw(st.integers(min_value=1, max_value=1000))
    encoded = [_encode(line) for line in lines]
    content = b"".join(encoded) + partial
    offset = sum(len(e) for e in encoded[:split])
    complete_end = sum(len(e) for e in encoded)
    return lines, content, offset, split, complete_end, start_line


@given(_content_with_offset())
def test_offset_read_returns_exactly_new_complete_lines(
    data: tuple[list[dict[str, Any]], bytes, int, int, int, int],
) -> None:
    """Feature: brain, Property 1: Offset-based reads return exactly the new complete lines

    **Validates: Requirements 2.2, 2.5, 2.8**
    """
    lines, content, offset, split, complete_end, start_line = data

    result = read_new_events(content, offset, start_line)

    expected = lines[split:]
    assert len(result.parsed_lines) == len(expected)
    for i, (parsed, want) in enumerate(zip(result.parsed_lines, expected, strict=True)):
        assert parsed.event is not None
        assert parsed.raw_error is None
        assert parsed.line_number == start_line + i
        assert parsed.event.session_id == want["session_id"]
        assert parsed.event.kind == want["kind"]
        assert json.loads(parsed.event.payload) == want["payload"]
    # new_offset sits right after the last complete line; the partial tail is excluded.
    assert result.new_offset == complete_end


@given(_content_with_offset(), st.integers(min_value=1, max_value=10_000))
def test_stored_offset_beyond_content_resets_to_zero(
    data: tuple[list[dict[str, Any]], bytes, int, int, int, int],
    extra: int,
) -> None:
    """Feature: brain, Property 1: Offset-based reads return exactly the new complete lines

    A stored offset larger than the content is reset to 0 by the caller (truncation),
    after which every complete line is returned.

    **Validates: Requirements 2.2, 2.8**
    """
    lines, content, _offset, _split, complete_end, _start = data

    stored = len(content) + extra
    offset = 0 if stored > len(content) else stored
    result = read_new_events(content, offset)

    assert [p.event.session_id for p in result.parsed_lines if p.event] == [
        line["session_id"] for line in lines
    ]
    assert result.new_offset == complete_end


@given(_content_with_offset())
def test_reingest_without_new_complete_lines_is_noop(
    data: tuple[list[dict[str, Any]], bytes, int, int, int, int],
) -> None:
    """Feature: brain, Property 2: Re-ingesting with no new complete lines is a no-op

    **Validates: Requirements 2.6**
    """
    _lines, content, offset, _split, _end, _start = data

    first = read_new_events(content, offset)
    second = read_new_events(content, first.new_offset)

    assert second.parsed_lines == []
    assert second.new_offset == first.new_offset
