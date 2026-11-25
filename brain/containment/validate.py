"""Literal validation for values that may appear in containment rules.

Pure functions. Attacker-supplied IPs and ports must pass through these before
reaching any rule or script text.
"""

from __future__ import annotations

import ipaddress

_MIN_PORT = 1
_MAX_PORT = 65535
_MAX_PORT_DIGITS = 5


def validate_ip(value: str) -> str | None:
    """Return ``value`` unchanged if it is an IPv4 or IPv6 literal, else None.

    IPv6 scope IDs (``fe80::1%eth0``) are rejected so that no free-form text
    can ride along with an address.
    """
    if not isinstance(value, str) or not value or "%" in value:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def is_blockable_ip(value: str) -> bool:
    """Return True only for a valid, globally routable IP literal.

    Loopback, private, link-local, reserved, multicast, unspecified and other
    non-global addresses (including IPv4-mapped forms of them) are never blockable,
    so a generated rule cannot cut off the operator's own network.
    """
    if validate_ip(value) is None:
        return False
    addr = ipaddress.ip_address(value)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return not (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or not addr.is_global
    )


def validate_port(value: int | str) -> int | None:
    """Return the port as an int if it is an integer in [1, 65535], else None.

    Booleans, floats and strings that are not plain ASCII digits are rejected.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        if not value.isascii() or not value.isdigit() or len(value) > _MAX_PORT_DIGITS:
            return None
        port = int(value)
    else:
        return None
    if _MIN_PORT <= port <= _MAX_PORT:
        return port
    return None
