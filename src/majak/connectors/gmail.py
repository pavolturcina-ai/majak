"""Gmail connector.

Delta-sync uses the newest message's internalDate as the cursor; overlap is
harmless because ingestion dedupes on (connector, external_id). Reads full RFC822
via format=raw so the existing `.eml` normalizer handles parsing.
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime

import httpx

from majak.config import settings
from majak.connectors._google import access_token
from majak.models.schemas import RawInput

logger = logging.getLogger(__name__)

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailConnector:
    name = "gmail"

    @property
    def configured(self) -> bool:
        return bool(settings.gmail_client_id and settings.gmail_refresh_token)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        if not self.configured:
            logger.info("gmail not configured; skipping")
            return [], cursor

        token = await access_token(
            settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token
        )
        headers = {"Authorization": f"Bearer {token}"}
        # cursor = epoch seconds of the newest message seen; first run = last 1 day.
        parts = [f"after:{cursor}" if cursor else "newer_than:1d", "-in:chats -in:spam -in:trash"]
        # Optional operator filter (e.g. "is:starred", "in:inbox is:unread").
        if settings.gmail_query.strip():
            parts.append(settings.gmail_query.strip())
        query = " ".join(parts)

        raws: list[RawInput] = []
        newest = int(cursor) if cursor else 0
        async with httpx.AsyncClient(timeout=30) as client:
            listing = await client.get(
                f"{_BASE}/messages",
                params={"q": query, "maxResults": "50"},
                headers=headers,
            )
            listing.raise_for_status()
            for meta in listing.json().get("messages", []):
                mid = meta["id"]
                msg = await client.get(
                    f"{_BASE}/messages/{mid}", params={"format": "raw"}, headers=headers
                )
                msg.raise_for_status()
                data = msg.json()
                raw_bytes = base64.urlsafe_b64decode(data["raw"])
                internal_ms = int(data.get("internalDate", "0"))
                occurred = datetime.fromtimestamp(internal_ms / 1000, tz=UTC)
                newest = max(newest, internal_ms // 1000)
                raws.append(
                    RawInput(
                        kind="email",
                        connector="gmail",
                        external_id=mid,
                        occurred_at=occurred,
                        file_bytes=raw_bytes,
                        file_name=f"{mid}.eml",
                        mime="message/rfc822",
                        url=f"https://mail.google.com/mail/u/0/#all/{mid}",
                        meta={"thread_id": data.get("threadId")},
                    )
                )

        new_cursor = str(newest) if newest else cursor
        logger.info("gmail: %d messages", len(raws))
        return raws, new_cursor
