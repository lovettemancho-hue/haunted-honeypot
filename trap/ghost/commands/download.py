"""Simulated ``wget`` and ``curl``.

SECURITY: nothing here ever contacts the network. The URL is only parsed as a
string, recorded in a ``download_attempt`` event and used to name an empty
file in the per-session in-memory filesystem.
"""

from __future__ import annotations

import hashlib
import ipaddress
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from trap.ghost.dispatcher import CommandResult
from trap.models import Event

if TYPE_CHECKING:
    from trap.models import SessionContext

_MAX_NAME = 128
_DEFAULT_NAME = "index.html"
# Options that consume the following argument and so must not be taken as URL.
_WGET_VALUE_OPTS = frozenset({"-O", "-P", "-o", "-a", "-t", "-T", "-U", "-e"})
_CURL_VALUE_OPTS = frozenset(
    {"-o", "-H", "-d", "-X", "-A", "-u", "-e", "-m", "-b", "-c", "-F"}
)


def _parse_args(
    args: list[str], value_opts: frozenset[str], out_opt: str
) -> tuple[str | None, str | None]:
    """Return ``(url, output_name)`` from ``args`` (first non-option operand)."""
    url: str | None = None
    out_name: str | None = None
    skip_next = False
    take_out = False
    for arg in args:
        if skip_next:
            if take_out:
                out_name = arg
            skip_next = take_out = False
        elif arg in value_opts:
            skip_next = True
            take_out = arg == out_opt
        elif arg.startswith("-") and len(arg) > 1:
            continue
        elif url is None:
            url = arg
    return url, out_name


def _filename_for(url: str, override: str | None) -> str:
    """Pick a safe single-component filename (last URL path segment)."""
    candidate = override
    if not candidate:
        try:
            path = urlsplit(url).path
        except ValueError:
            path = ""
        candidate = path.rstrip("/").rsplit("/", 1)[-1]
    candidate = candidate.rsplit("/", 1)[-1].strip()
    if candidate in ("", ".", ".."):
        candidate = _DEFAULT_NAME
    return candidate[:_MAX_NAME]


def _host_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        host = None
    return host or "unknown-host"


def _is_raw_ip(host: str) -> bool:
    """True if ``host`` is an IPv4/IPv6 literal (brackets tolerated)."""
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _fake_size(url: str) -> int:
    """Deterministic plausible size (KiB range) derived from the URL."""
    digest = hashlib.sha256(url.encode("utf-8", "replace")).digest()
    return 4096 + int.from_bytes(digest[:3], "big") % 900_000


def _human(size: int) -> str:
    return f"{size / 1024:.0f}K" if size < 1024 * 1024 else f"{size / 1048576:.1f}M"


def _wget_output(url: str, name: str, size: int) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    host = _host_of(url)
    lines = [f"--{now}--  {url}"]
    if _is_raw_ip(host):
        lines.append(f"Connecting to {host}:80... connected.")
    else:
        lines += [
            f"Resolving {host} ({host})... 93.184.216.34",
            f"Connecting to {host} ({host})|93.184.216.34|:80... connected.",
        ]
    return "\n".join(
        [
            *lines,
            "HTTP request sent, awaiting response... 200 OK",
            f"Length: {size} ({_human(size)}) [application/octet-stream]",
            f"Saving to: '{name}'",
            "",
            f"{name}      100%[===================>] {_human(size):>7}"
            "  1.21MB/s    in 0.3s",
            "",
            f"{now} (1.21 MB/s) - '{name}' saved [{size}/{size}]",
        ]
    )


def _curl_output(size: int) -> str:
    return "\n".join(
        [
            "  % Total    % Received % Xferd  Average Speed   Time    Time"
            "     Time  Current",
            "                                 Dload  Upload   Total   Spent"
            "    Left  Speed",
            f"100 {size:>6}  100 {size:>6}    0     0  1284k      0 "
            "--:--:-- --:--:-- --:--:-- 1284k",
        ]
    )


async def _download(
    tool: str,
    args: list[str],
    ctx: SessionContext,
    value_opts: frozenset[str],
    out_opt: str,
) -> CommandResult:
    url, override = _parse_args(args, value_opts, out_opt)
    if url is None:
        msg = (
            "wget: missing URL\nUsage: wget [OPTION]... [URL]..."
            if tool == "wget"
            else "curl: try 'curl --help' for more information"
        )
        return CommandResult(output=msg, is_error=True)

    command = " ".join([tool, *args])
    ctx.pending_events.append(
        Event(
            session_id=ctx.session.session_id,
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            kind="download_attempt",
            payload={"command": command, "url": url},
            generated_by="scripted",
        )
    )

    # curl without -o writes to stdout and leaves no file behind.
    name = _filename_for(url, override)
    size = _fake_size(url)
    if tool == "curl" and override is None:
        return CommandResult(output=_curl_output(size), is_error=False)

    try:
        ctx.fs.create_file(name)
    except (OSError, ValueError) as exc:
        return CommandResult(
            output=f"{tool}: {name}: {type(exc).__name__}", is_error=True
        )
    ctx.downloaded_files.add(name)
    output = _wget_output(url, name, size) if tool == "wget" else _curl_output(size)
    return CommandResult(output=output, is_error=False)


async def wget(args: list[str], ctx: SessionContext) -> CommandResult:
    return await _download("wget", args, ctx, _WGET_VALUE_OPTS, "-O")


async def curl(args: list[str], ctx: SessionContext) -> CommandResult:
    return await _download("curl", args, ctx, _CURL_VALUE_OPTS, "-o")
