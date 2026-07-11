"""Slack connector.

Cursor = the latest message `ts` seen per watched channel (stored in
sync_state.meta). Reuse the CEO's MCP Slack connector where available; this
direct-API path is the fallback.
"""

from __future__ import annotations

import logging

from majak.config import settings
from majak.models.schemas import RawInput

logger = logging.getLogger(__name__)


class SlackConnector:
    name = "slack"

    @property
    def configured(self) -> bool:
        return bool(settings.slack_bot_token)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        if not self.configured:
            logger.info("slack connector not configured; skipping")
            return [], cursor

        # Real implementation outline:
        #   1. conversations.list -> channels to watch (or a configured allowlist).
        #   2. conversations.history(oldest=cursor) per channel; join threads.
        #   3. RawInput(kind='slack', connector='slack', external_id=f"{channel}:{ts}",
        #        occurred_at=ts, text=message_text, url=permalink,
        #        meta={"channel": channel, "author": user}).
        #   4. new cursor = max(ts) across channels.
        raise NotImplementedError(
            "Slack direct-API fetch not wired; provide a bot token or route via MCP."
        )
