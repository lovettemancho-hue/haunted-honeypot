"""Property test for invalid-line handling in the Session_Log reader.

Feature: brain, Property 3: Invalid lines are skipped without raising, valid
lines are preserved in order.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from brain.ingest.reader import read_new_events

_text = st.text(alphabet=st.characters(exclude_categories=["Cs"]), max_size=20)
_json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | _text,
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(_text, children, max_size=3),
    max_leaves=6,
)

_valid_record = st.fixed_dictionaries(
    {
        "session_id": st.text(alphabet="0123456789abcdef", min_size=1, max_size=32),
        "timestamp": st.datetimes().map(lambda d: d.isoformat()),
        "kind": st.sampled_from(["login_attempt", "command", "response", "download_attempt"]),
        "payload": _json_values,
    }
)


def _good_record() -> dict[str, Any]:
    return {
        "session_id": "abc",
        "timestamp": "2024-01-01T00:00:00",
        "kind": "command",
        "payload": {},
    }


def _without(field: str) -> str:
    record = _good_record()
    del record[field]
    return json.dumps(record)


_INVALID_LINES = [
    "",
    "   ",
    "not json at all",
    "{",
    '{"session_id": "abc", "timestamp": ',
    "[1, 2, 3]",
    "null",
    '"a string"',
    "42",
    _without("session_id"),
    _without("timestamp"),
    _without("kind"),
    _without("payload"),
    json.dumps({**_good_record(), "timestamp": "not-a-date"}),
    json.dumps({**_good_record(), "timestamp": 12345}),
    json.dumps({**_good_record(), "kind": ""}),
    json.dumps({**_good_record(), "session_id": ""}),
    json.dumps({**_good_record(), "session_id": 7}),
]

_line = st.one_of(
    _valid_record.map(lambda r: (True, json.dumps(r), r)),
    st.sampled_from(_INVALID_LINES).map(lambda s: (False, s, None)),
)


@settings(max_examples=100, deadline=None)
@given(lines=st.lists(_line, max_size=30))
def test_invalid_lines_skipped_valid_preserved_in_order(
    lines: list[tuple[bool, str, dict[str, Any] | None]],
) -> None:
    """**Validates: Requirements 2.7**"""
    content = "".join(text + "\n" for _, text, _ in lines).encode("utf-8")

    result = read_new_events(content, 0)  # must not raise

    assert len(result.parsed_lines) == len(lines)
    assert result.new_offset == len(content)

    # Line numbers are 1-indexed and sequential.
    assert [p.line_number for p in result.parsed_lines] == list(range(1, len(lines) + 1))

    # Invalid lines are reported at exactly the right 1-indexed positions.
    expected_invalid = [i for i, (ok, _, _) in enumerate(lines, start=1) if not ok]
    actual_invalid = [p.line_number for p in result.parsed_lines if p.event is None]
    assert actual_invalid == expected_invalid
    assert all(p.raw_error for p in result.parsed_lines if p.event is None)

    # Valid events are exactly the valid lines, in original order.
    expected_records = [rec for ok, _, rec in lines if ok and rec is not None]
    events = [p.event for p in result.parsed_lines if p.event is not None]
    assert len(events) == len(expected_records)
    for event, record in zip(events, expected_records, strict=True):
        assert event.session_id == record["session_id"]
        assert event.kind == record["kind"]
        assert event.timestamp == datetime.fromisoformat(record["timestamp"])
        assert json.loads(event.payload) == record["payload"]
