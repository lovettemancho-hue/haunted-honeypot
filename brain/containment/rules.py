"""Pure containment rule generation (text only; nothing is applied to any host).

IP addresses and ports reach rule text only through ``brain.containment.validate``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from brain.analysis.attack_map import MINING_PORTS
from brain.containment.validate import is_blockable_ip, validate_port
from brain.models import Severity

KIND_SSHD = "sshd_hardening"
KIND_FAIL2BAN = "fail2ban_jail"
KIND_IP_DROP = "ip_drop"
KIND_PORT_DROP = "mining_port_drop"

_HOST_PORT = re.compile(r"[^\s:/@\"'`;|&()<>]:(\d{1,5})(?![\w:])")


@dataclass(frozen=True)
class SessionForContainment:
    """The per-session facts containment needs."""

    session_id: str
    src_ip: str
    severity: Severity
    had_successful_login: bool
    failed_login_count: int
    mining_ports: frozenset[int] = frozenset()


@dataclass(frozen=True)
class ContainmentRule:
    """One generated rule. ``content`` is shell text with comments."""

    id: str
    kind: str
    title: str
    description: str
    content: str
    evidence_sessions: tuple[str, ...]


def extract_mining_ports(text: str) -> frozenset[int]:
    """Return Mining_Ports used as the port of a ``host:port`` address in ``text``."""
    found: set[int] = set()
    for match in _HOST_PORT.finditer(text):
        port = validate_port(match.group(1))
        if port is not None and port in MINING_PORTS:
            found.add(port)
    return frozenset(found)


def _evidence(ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(ids)))


def _sshd_rule(sessions: list[SessionForContainment]) -> ContainmentRule | None:
    evidence = _evidence(s.session_id for s in sessions if s.had_successful_login)
    if not evidence:
        return None
    content = (
        "# Disable password and root logins over SSH\n"
        "sed -i -E 's/^#?PasswordAuthentication .*/PasswordAuthentication no/' "
        "/etc/ssh/sshd_config\n"
        "sed -i -E 's/^#?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config\n"
        "# Reload with: systemctl reload sshd"
    )
    return ContainmentRule(
        id="sshd-hardening",
        kind=KIND_SSHD,
        title="Harden sshd logins",
        description=(
            "Specimens got in with a guessed password. Turning off password logins "
            "and root logins means guessed passwords no longer work; use SSH keys."
        ),
        content=content,
        evidence_sessions=evidence,
    )


def _fail2ban_rule(sessions: list[SessionForContainment]) -> ContainmentRule | None:
    evidence = _evidence(s.session_id for s in sessions if s.failed_login_count >= 2)
    if not evidence:
        return None
    content = (
        "# Write to /etc/fail2ban/jail.d/sshd.local\n"
        "[sshd]\n"
        "enabled = true\n"
        "maxretry = 3\n"
        "findtime = 10m\n"
        "bantime = 1h"
    )
    return ContainmentRule(
        id="fail2ban-sshd",
        kind=KIND_FAIL2BAN,
        title="Ban repeated SSH guessers with fail2ban",
        description=(
            "Specimens made repeated failed logins. fail2ban temporarily blocks an "
            "address after a few failures, which stops password guessing."
        ),
        content=content,
        evidence_sessions=evidence,
    )


def _ip_rules(sessions: list[SessionForContainment]) -> list[ContainmentRule]:
    by_ip: dict[str, list[str]] = {}
    for s in sessions:
        if s.severity not in (Severity.CLASS_3, Severity.CLASS_5):
            continue
        ip = s.src_ip
        if not is_blockable_ip(ip):
            continue
        by_ip.setdefault(ip, []).append(s.session_id)
    rules: list[ContainmentRule] = []
    for ip in sorted(by_ip):
        tool = "ip6tables" if ":" in ip else "iptables"
        rules.append(
            ContainmentRule(
                id="block-ip-" + ip.replace(":", "_"),
                kind=KIND_IP_DROP,
                title=f"Block specimen {ip}",
                description=(
                    "This address logged in and behaved like an intruder "
                    "(Class 3 or Class 5). Dropping its packets keeps it away."
                ),
                content=f"# Drop all inbound traffic from {ip}\n{tool} -A INPUT -s {ip} -j DROP",
                evidence_sessions=_evidence(by_ip[ip]),
            )
        )
    return rules


def _port_rules(sessions: list[SessionForContainment]) -> list[ContainmentRule]:
    by_port: dict[int, list[str]] = {}
    for s in sessions:
        for raw in s.mining_ports:
            port = validate_port(raw)
            if port is None or port not in MINING_PORTS:
                continue
            by_port.setdefault(port, []).append(s.session_id)
    rules: list[ContainmentRule] = []
    for port in sorted(by_port):
        rules.append(
            ContainmentRule(
                id=f"block-mining-port-{port}",
                kind=KIND_PORT_DROP,
                title=f"Block outbound mining port {port}",
                description=(
                    "Specimens tried to reach a cryptocurrency mining pool on this "
                    "port. Blocking outbound traffic to it stops a miner from working."
                ),
                content=(
                    f"# Drop outbound TCP traffic to port {port}\n"
                    f"iptables -A OUTPUT -p tcp --dport {port} -j DROP"
                ),
                evidence_sessions=_evidence(by_port[port]),
            )
        )
    return rules


def build_rules(sessions: Iterable[SessionForContainment]) -> list[ContainmentRule]:
    """Build containment rules in a deterministic order.

    Order: sshd hardening, fail2ban, per-IP drops (by IP), per-port drops (by port).
    A rule kind is omitted when it has no evidence.
    """
    ordered = sorted(sessions, key=lambda s: s.session_id)
    rules: list[ContainmentRule] = []
    for single in (_sshd_rule(ordered), _fail2ban_rule(ordered)):
        if single is not None:
            rules.append(single)
    rules.extend(_ip_rules(ordered))
    rules.extend(_port_rules(ordered))
    return rules
