"""Pure rendering of containment rules into a reviewable shell script (text only).

Nothing here runs or applies anything. Output is static template text, sanitized
single-line rule titles/descriptions, and rule content that ``rules.py`` built
from validated IP and port literals. Usernames, passwords and attacker commands
never reach this module.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from brain.containment.rules import KIND_FAIL2BAN, ContainmentRule

_HEADER = (
    "#!/bin/sh\n"
    "# Haunted Honeypot containment script\n"
    "# Generated text only. Nothing has been applied. Read every line, then run\n"
    "# it yourself as root on the server you want to protect.\n"
    "set -eu\n"
)

_MAX_COMMENT = 300
_UNSAFE = re.compile(r"[^\x20-\x7e]+")  # newlines, control and non-ASCII characters


def _comment_text(text: str) -> str:
    """Flatten ``text`` to one printable ASCII line that is safe after ``# ``."""
    return _UNSAFE.sub(" ", text).strip()[:_MAX_COMMENT]


def _content_lines(rule: ContainmentRule) -> list[str]:
    lines = [ln for ln in rule.content.splitlines() if ln.strip()]
    if rule.kind != KIND_FAIL2BAN:
        return lines
    # fail2ban content is an INI file: write it with a quoted heredoc so
    # nothing in it is expanded or run by the shell.
    comments = [ln for ln in lines if ln.startswith("#")]
    body = [ln for ln in lines if not ln.startswith("#")]
    target = "/etc/fail2ban/jail.d/sshd.local"
    return [
        *comments,
        f"cat > {target} <<'HONEYPOT_EOF'",
        *body,
        "HONEYPOT_EOF",
    ]


def render_script(rules: Iterable[ContainmentRule]) -> str:
    """Render ``rules`` as a deterministic shell script string."""
    parts = [_HEADER]
    for index, rule in enumerate(rules, start=1):
        block = [
            f"# --- Rule {index}: {_comment_text(rule.title)}",
            f"# {_comment_text(rule.description)}",
            *_content_lines(rule),
        ]
        parts.append("\n".join(block) + "\n")
    return "\n".join(parts)
