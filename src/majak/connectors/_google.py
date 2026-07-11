"""Shared Google OAuth helper for the Gmail + Calendar connectors."""

from __future__ import annotations

import httpx

_TOKEN_URL = "https://oauth2.googleapis.com/token"


async def access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange a long-lived refresh token for a short-lived access token."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
