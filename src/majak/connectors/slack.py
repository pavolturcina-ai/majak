"""Slack connector.

Cursor = the newest message `ts` seen across watched channels (the channels the
bot is a member of). Overlap is harmless — ingestion dedupes on
(connector, external_id = "<channel>:<ts>").
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from majak.config import settings
from majak.models.schemas import RawInput

logger = logging.getLogger(__name__)

_BASE = "https://slack.com/api"


class SlackConnector:
    name = "slack"

    @property
    def configured(self) -> bool:
        return bool(settings.slack_bot_token)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        if not self.configured:
            logger.info("slack not configured; skipping")
            return [], cursor

        headers = {"Authorization": f"Bearer {settings.slack_bot_token}"}
        oldest = cursor or "0"
        raws: list[RawInput] = []
        newest = float(oldest)

        async with httpx.AsyncClient(timeout=30, base_url=_BASE, headers=headers) as client:
            channels = await self._channels(client)
            for ch in channels:
                cid = ch["id"]
                cname = ch.get("name", cid)
                resp = await client.get(
                    "/conversations.history",
                    params={"channel": cid, "oldest": oldest, "limit": "100"},
                )
                body = resp.json()
                if not body.get("ok"):
                    logger.warning("slack history %s: %s", cname, body.get("error"))
                    continue
                for msg in body.get("messages", []):
                    if msg.get("subtype") in {"channel_join", "channel_leave", "bot_message"}:
                        continue
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    ts = msg["ts"]
                    newest = max(newest, float(ts))
                    occurred = datetime.fromtimestamp(float(ts), tz=UTC)
                    raws.append(
                        RawInput(
                            kind="slack",
                            connector="slack",
                            external_id=f"{cid}:{ts}",
                            occurred_at=occurred,
                            text=text,
                            title=f"#{cname}",
                            meta={"channel": cname, "channel_id": cid, "author": msg.get("user")},
                        )
                    )

        new_cursor = repr(newest) if newest else cursor
        logger.info("slack: %d messages across %d channels", len(raws), len(channels))
        return raws, new_cursor

    async def _channels(self, client: httpx.AsyncClient) -> list[dict]:
        resp = await client.get(
            "/conversations.list",
            params={"types": "public_channel,private_channel", "limit": "200", "exclude_archived": "true"},
        )
        body = resp.json()
        if not body.get("ok"):
            logger.warning("slack conversations.list: %s", body.get("error"))
            return []
        return [c for c in body.get("channels", []) if c.get("is_member")]
