"""Bearer-token authentication dependency (Requirements 8.2, 8.3, 8.4)."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from brain.config import Config

_BEARER_PREFIX = "Bearer "


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_token(request: Request) -> None:
    """Raise 401 unless the request carries ``Authorization: Bearer <API_Token>``.

    The configuration is read from ``request.app.state.config``; the token is
    compared in constant time with ``secrets.compare_digest``.
    """
    header = request.headers.get("authorization")
    if header is None or not header.startswith(_BEARER_PREFIX):
        raise _unauthorized()
    presented = header[len(_BEARER_PREFIX) :]
    config: Config = request.app.state.config
    # Compare bytes so non-ASCII input cannot raise TypeError.
    if not secrets.compare_digest(presented.encode("utf-8"), config.api_token.encode("utf-8")):
        raise _unauthorized()
