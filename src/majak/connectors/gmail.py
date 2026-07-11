"""Gmail connector.

Delta-sync uses Gmail's historyId as the cursor when available, else a date
window. Reuse the CEO's existing MCP Gmail connector where available; this
direct-API path is the fallback. Returns empty (no-op) when unconfigured so the
scheduler runs cleanly without credentials.
"""

from __future__ import annotations

import logging

from majak.config import settings
from majak.models.schemas import RawInput

logger = logging.getLogger(__name__)


class GmailConnector:
    name = "gmail"

    @property
    def configured(self) -> bool:
        return bool(settings.gmail_client_id and settings.gmail_refresh_token)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        if not self.configured:
            logger.info("gmail connector not configured; skipping")
            return [], cursor

        # Real implementation outline (kept as a clean seam):
        #   1. Exchange refresh token for an access token.
        #   2. users.history.list(startHistoryId=cursor) OR
        #      users.messages.list(q="newer_than:1d -in:chats") on first run.
        #   3. For each message: users.messages.get(format='raw') -> RawInput(
        #        kind='email', connector='gmail', external_id=message_id,
        #        occurred_at=internalDate, file_bytes=raw_rfc822, mime='message/rfc822').
        #   4. new cursor = latest historyId.
        raise NotImplementedError(
            "Gmail direct-API fetch not wired; provide OAuth creds or route via MCP."
        )
