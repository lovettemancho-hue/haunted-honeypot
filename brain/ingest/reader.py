"""Pure offset reader for Session_Log content (no I/O, no DB access).

Given the full bytes of a ``*.jsonl`` file and a stored byte offset, return the
Complete_Lines (newline-terminated) from that offset onward, parsed into
``Event`` objects. A trailing partial line is left unread and excluded from
``new_offset``. Invalid lines never raise; they yield a ``ParsedLine`` with
``event=None`` and a ``raw_error`` message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from brain.models import Event

_REQUIRED_FIELDS = ("session_id", "timestamp", "kind", "payload")


@dataclass(frozen=True)
class ParsedLine:
    event: Event | None  # None when the line was invalid JSON / missing fields
    line_number: int
    raw_error: str | None  # populated when event is None


@dataclass(frozen=True)
class ReadResult:
    parsed_lines: list[ParsedLine]
    new_offset: int


def _parse_line(raw: bytes, line_number: int) -> ParsedLine:
    def fail(message: str) -> ParsedLine:
        return ParsedLine(event=None, line_number=line_number, raw_error=message)

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return fail(f"invalid JSON: {type(exc).__name__}")

    if not isinstance(data, dict):
        return fail("line is not a JSON object")

    missing = [name for name in _REQUIRED_FIELDS if name not in data]
    if missing:
        return fail("missing fields: " + ", ".join(missing))

    session_id = data["session_id"]
    kind = data["kind"]
    if not isinstance(session_id, str) or not session_id:
        return fail("session_id must be a non-empty string")
    if not isinstance(kind, str) or not kind:
        return fail("kind must be a non-empty string")

    raw_ts = data["timestamp"]
    if not isinstance(raw_ts, str):
        return fail("timestamp must be an ISO-8601 string")
    try:
        timestamp = datetime.fromisoformat(raw_ts)
    except ValueError:
        return fail("timestamp is not valid ISO-8601")

    generated_by = data.get("generated_by")
    if not isinstance(generated_by, str) or not generated_by:
        generated_by = "scripted"

    try:
        payload = json.dumps(data["payload"], ensure_ascii=False)
    except (TypeError, ValueError):
        return fail("payload is not JSON-serialisable")

    event = Event(
        session_id=session_id,
        timestamp=timestamp,
        kind=kind,
        payload=payload,
        generated_by=generated_by,
    )
    return ParsedLine(event=event, line_number=line_number, raw_error=None)


def read_new_events(content: bytes, offset: int, start_line_number: int = 1) -> ReadResult:
    """Return every Complete_Line from ``offset`` onward plus the new offset.

    ``start_line_number`` is the 1-indexed line number of the line beginning at
    ``offset``. ``new_offset`` is the byte position after the last Complete_Line
    consumed; a trailing line without a newline is left unread. If ``offset``
    exceeds ``len(content)`` nothing is read and ``offset`` is returned
    unchanged (truncation handling belongs to the caller).
    """
    if offset < 0:
        offset = 0
    if offset > len(content):
        return ReadResult(parsed_lines=[], new_offset=offset)

    parsed: list[ParsedLine] = []
    pos = offset
    line_number = start_line_number
    while True:
        newline = content.find(b"\n", pos)
        if newline == -1:
            break
        parsed.append(_parse_line(content[pos:newline], line_number))
        pos = newline + 1
        line_number += 1
    return ReadResult(parsed_lines=parsed, new_offset=pos)
