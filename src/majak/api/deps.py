"""FastAPI dependencies: DB session + single-user auth.

Auth verifies a Supabase-issued JWT (HS256 with SUPABASE_JWT_SECRET) and checks
the email matches the single configured user. In dev (no secret set), a bearer
token equal to the cron secret is accepted so the app is usable locally.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from majak.config import settings
from majak.db import get_session

logger = logging.getLogger(__name__)


async def db_session() -> AsyncIterator[AsyncSession]:
    async for s in get_session():
        yield s


class Principal:
    def __init__(self, email: str) -> None:
        self.email = email


async def current_user(authorization: str | None = Header(default=None)) -> Principal:
    token = _bearer(authorization)

    # Dev fallback: allow the cron/dev secret when JWT verification isn't set up.
    if not settings.supabase_jwt_secret:
        if token and token == settings.cron_secret:
            return Principal(email=settings.auth_single_user_email)
        raise _unauthorized("JWT secret not configured; present the dev token")

    email = _verify_jwt(token)
    if email is None or email.lower() != settings.auth_single_user_email.lower():
        raise _unauthorized("Not the authorized user")
    return Principal(email=email)


async def require_cron(authorization: str | None = Header(default=None)) -> None:
    """Guard for /scheduler/* — the pg_cron / edge caller presents the secret."""
    token = _bearer(authorization)
    if not token or token != settings.cron_secret:
        raise _unauthorized("Invalid cron secret")


def _bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return header


def _verify_jwt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        import jwt  # PyJWT ships with the supabase client

        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_aud": False},
        )
        return payload.get("email") or payload.get("user_metadata", {}).get("email")
    except Exception as exc:  # noqa: BLE001
        logger.warning("JWT verification failed: %s", exc)
        return None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


CurrentUser = Depends(current_user)
DbSession = Depends(db_session)
