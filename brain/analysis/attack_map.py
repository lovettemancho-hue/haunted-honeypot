"""Pure MITRE ATT&CK mapping for one Session's Events (Requirement 4).

Input type: ``brain.models.Event`` rows (``payload`` is JSON-encoded text),
already ordered by timestamp. Nothing is read from the database here and the
Events' ``id`` may still be ``None`` (not yet stored), so evidence is reported
as ``evidence_event_index``: the position of the evidence Event in the list
that was passed in. Callers translate the index to ``Event.id`` when they
write Technique rows.

Text matching is done by tokenizing with a single linear scan and comparing
whole tokens (or token basenames/prefixes). No regular expressions are used,
so arbitrary attacker input cannot cause catastrophic backtracking.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from brain.models import Event

MINING_PORTS: frozenset[int] = frozenset({3333, 4444, 5555, 7777, 14444, 45700})

_SYSINFO_WORDS = frozenset({"uname", "whoami", "id", "hostname"})
_DELETE_COMMANDS = frozenset({"rm", "unlink", "shred", "truncate"})
_HISTORY_BASENAMES = frozenset({".bash_history", ".zsh_history", ".sh_history", ".history"})
_SEPARATORS = frozenset(";|&\n\r()`{}")
_QUOTES = frozenset("'\"")


@dataclass(frozen=True)
class TechniqueHit:
    """A detected technique and the index of its first qualifying Event."""

    attack_id: str
    name: str
    evidence_event_index: int


@dataclass(frozen=True)
class _View:
    """Decoded, per-Event data the rules look at."""

    kind: str
    success: bool | None
    command_text: str
    url: str
    command_segments: tuple[tuple[str, ...], ...]


def _tokenize(text: str) -> list[list[str]]:
    """Split shell-like text into segments of tokens in one linear pass.

    Segments end at ``; | & ( ) ` { }`` or a newline. Whitespace separates
    tokens, quote characters are dropped, and ``>`` / ``>>`` become their own
    tokens so redirections can be recognised.
    """
    segments: list[list[str]] = []
    tokens: list[str] = []
    buf: list[str] = []

    def flush_token() -> None:
        if buf:
            tokens.append("".join(buf))
            buf.clear()

    def flush_segment() -> None:
        flush_token()
        if tokens:
            segments.append(tokens.copy())
            tokens.clear()

    for ch in text:
        if ch in _SEPARATORS:
            flush_segment()
        elif ch.isspace():
            flush_token()
        elif ch in _QUOTES:
            continue
        elif ch == ">":
            flush_token()
            if tokens and tokens[-1] == ">" and not buf:
                tokens[-1] = ">>"
            else:
                tokens.append(">")
        else:
            buf.append(ch)
    flush_segment()
    return segments


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _decode(event: Event) -> _View:
    try:
        data = json.loads(event.payload)
    except (ValueError, TypeError):
        data = None
    payload: dict[str, object] = data if isinstance(data, dict) else {}
    command = payload.get("command")
    url = payload.get("url")
    success = payload.get("success")
    command_text = command if isinstance(command, str) else ""
    return _View(
        kind=event.kind,
        success=success if isinstance(success, bool) else None,
        command_text=command_text,
        url=url if isinstance(url, str) else "",
        command_segments=tuple(tuple(seg) for seg in _tokenize(command_text)),
    )


def _tokens(view: _View) -> list[str]:
    return [tok for seg in view.command_segments for tok in seg]


def _is_command(view: _View) -> bool:
    return view.kind == "command"


def _is_log_or_history_path(path: str) -> bool:
    if path == "/var/log" or path.startswith("/var/log/"):
        return True
    return _basename(path) in _HISTORY_BASENAMES


def _port_of_host_address(token: str) -> int | None:
    """Return the port of a ``host:port`` / ``scheme://host:port/...`` token."""
    rest = token
    scheme_end = rest.find("://")
    if scheme_end != -1:
        rest = rest[scheme_end + 3 :]
    rest = rest.split("/", 1)[0]
    rest = rest.rsplit("@", 1)[-1]
    host, sep, port = rest.rpartition(":")
    if not sep or not host or not port.isascii() or not port.isdigit():
        return None
    if len(port) > 5:
        return None
    return int(port)


def _has_mining_port(text: str) -> bool:
    for seg in _tokenize(text):
        for tok in seg:
            if _port_of_host_address(tok) in MINING_PORTS:
                return True
    return False


# --- rules: each takes one decoded Event and says whether it qualifies ------


def _sysinfo(view: _View) -> bool:
    if not _is_command(view):
        return False
    for tok in _tokens(view):
        if tok in _SYSINFO_WORDS or tok == "/proc/cpuinfo":
            return True
        if "/" in tok and _basename(tok) in _SYSINFO_WORDS:
            return True
    return False


def _ingress_tool(view: _View) -> bool:
    if view.kind == "download_attempt":
        return True
    return _is_command(view) and any(_basename(tok) in {"wget", "curl"} for tok in _tokens(view))


def _cron(view: _View) -> bool:
    if not _is_command(view):
        return False
    for tok in _tokens(view):
        if _basename(tok) == "crontab" or "/etc/cron" in tok or "/var/spool/cron" in tok:
            return True
    return False


def _mining(view: _View) -> bool:
    if view.kind not in {"command", "download_attempt"}:
        return False
    lowered = (view.command_text + "\n" + view.url).lower()
    if "xmrig" in lowered or "stratum" in lowered:
        return True
    return _has_mining_port(view.command_text) or _has_mining_port(view.url)


def _cover_tracks(view: _View) -> bool:
    if not _is_command(view):
        return False
    for seg in view.command_segments:
        for i, tok in enumerate(seg):
            if tok == ">" and i + 1 < len(seg) and _is_log_or_history_path(seg[i + 1]):
                return True
            base = _basename(tok)
            if base in _DELETE_COMMANDS and any(_is_log_or_history_path(t) for t in seg[i + 1 :]):
                return True
            if (
                base == "history"
                and i + 1 < len(seg)
                and seg[i + 1].startswith("-")
                and "c" in seg[i + 1]
            ):
                return True
    return False


def _authorized_keys(view: _View) -> bool:
    return _is_command(view) and any(tok.endswith("authorized_keys") for tok in _tokens(view))


_CONTENT_RULES: tuple[tuple[str, str, Callable[[_View], bool]], ...] = (
    ("T1082", "System Information Discovery", _sysinfo),
    ("T1105", "Ingress Tool Transfer", _ingress_tool),
    ("T1059.004", "Unix Shell", _is_command),
    ("T1053.003", "Cron", _cron),
    ("T1496", "Resource Hijacking", _mining),
    ("T1070.004", "File Deletion", _cover_tracks),
    ("T1098.004", "SSH Authorized Keys", _authorized_keys),
)


def map_techniques(events: Sequence[Event]) -> list[TechniqueHit]:
    """Map one Session's Events (ordered by timestamp) to ATT&CK techniques.

    Each ``attack_id`` appears at most once, with the first qualifying Event
    as evidence (the second failed login for T1110). The result is ordered by
    rule (T1110, T1078, T1082, T1105, T1059.004, T1053.003, T1496, T1070.004,
    T1098.004) and is deterministic for the same input.
    """
    views = [_decode(e) for e in events]
    hits: list[TechniqueHit] = []

    failed = [i for i, v in enumerate(views) if v.kind == "login_attempt" and v.success is False]
    if len(failed) >= 2:
        hits.append(TechniqueHit("T1110", "Brute Force", failed[1]))

    for i, v in enumerate(views):
        if v.kind == "login_attempt" and v.success is True:
            hits.append(TechniqueHit("T1078", "Valid Accounts", i))
            break

    for attack_id, name, rule in _CONTENT_RULES:
        for i, v in enumerate(views):
            if rule(v):
                hits.append(TechniqueHit(attack_id, name, i))
                break

    order = {
        aid: n
        for n, aid in enumerate(
            (
                "T1110",
                "T1078",
                "T1082",
                "T1105",
                "T1059.004",
                "T1053.003",
                "T1496",
                "T1070.004",
                "T1098.004",
            )
        )
    }
    hits.sort(key=lambda h: order[h.attack_id])
    return hits
