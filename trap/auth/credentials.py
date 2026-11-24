"""Credential list parsing (pure, no I/O)."""

from __future__ import annotations


def parse_credentials(text: str) -> list[tuple[str, str]]:
    """Parse ``username:password`` lines into pairs.

    Splits on the first colon only, so passwords may contain colons. Blank
    lines, lines starting with ``#`` and lines without a colon are skipped.
    """
    pairs: list[tuple[str, str]] = []
    for line in text.split("\n"):
        line = line.removesuffix("\r")
        if not line.strip() or line.startswith("#"):
            continue
        username, sep, password = line.partition(":")
        if not sep or not username:
            continue
        pairs.append((username, password))
    return pairs


def serialise_credentials(pairs: list[tuple[str, str]]) -> str:
    """Serialise pairs into the credential file format."""
    return "".join(f"{u}:{p}\n" for u, p in pairs)
