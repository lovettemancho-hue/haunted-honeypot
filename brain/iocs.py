"""Pure IOC extraction and defanging (Requirements 8.6, 10.6)."""

from __future__ import annotations

import json
import re

from brain.models import Event

# Single character-class run after a literal prefix: linear-time matching.
_URL_RE = re.compile(r"https?://[^\s'\"<>|;&()`\\]+", re.IGNORECASE)
_SCHEME_RE = re.compile(r"http(s?)://", re.IGNORECASE)
_TRAILING = ".,:!?]}"


def _payload_dict(event: Event) -> dict[str, object]:
    try:
        data = json.loads(event.payload)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def extract_url_iocs(events: list[Event]) -> list[str]:
    """Distinct URLs (first-seen order) from download_attempt.url payloads
    and from URL-shaped substrings in command text."""
    seen: set[str] = set()
    result: list[str] = []

    def add(url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            result.append(url)

    for event in events:
        payload = _payload_dict(event)
        if event.kind == "download_attempt":
            url = payload.get("url")
            if isinstance(url, str):
                add(url.strip())
        elif event.kind == "command":
            command = payload.get("command")
            if isinstance(command, str):
                for match in _URL_RE.finditer(command):
                    add(match.group(0).rstrip(_TRAILING))
    return result


def defang(value: str) -> str:
    """http:// -> hxxp://, https:// -> hxxps://, every '.' -> '[.]'."""
    value = _SCHEME_RE.sub(lambda m: "hxxp" + m.group(1) + "://", value)
    return value.replace(".", "[.]")
