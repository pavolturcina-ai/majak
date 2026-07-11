"""Slack connector.

Reads with a **user token** when available (``SLACK_USER_TOKEN``), so it can see
the user's DMs, group DMs (mpim), and private channels the user belongs to.
Falls back to the bot token (``SLACK_BOT_TOKEN``) for public/private channels the
bot was invited to. Captures top-level messages *and* thread replies.

Cursor = the newest message ``ts`` seen across watched conversations. Overlap is
harmless — ingestion dedupes on (connector, external_id = "<channel>:<ts>").
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from majak.config import settings
from majak.models.schemas import RawInput

logger = logging.getLogger(__name__)

_BASE = "https://slack.com/api"
_TYPES = "public_channel,private_channel,mpim,im"
_SKIP_SUBTYPES = {"channel_join", "channel_leave", "bot_message"}


class SlackConnector:
    name = "slack"

    @property
    def _token(self) -> str:
        # Prefer the user token (sees DMs / group DMs / the user's channels);
        # fall back to the bot token (channels the bot was invited to).
        return settings.slack_user_token or settings.slack_bot_token

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        if not self.configured:
            logger.info("slack not configured; skipping")
            return [], cursor

        headers = {"Authorization": f"Bearer {self._token}"}
        oldest = cursor or "0"
        raws: list[RawInput] = []
        newest = float(oldest)

        async with httpx.AsyncClient(timeout=30, base_url=_BASE, headers=headers) as client:
            conversations = await self._conversations(client)
            for ch in conversations:
                cid = ch["id"]
                label = self._label(ch)
                for msg in await self._history(client, cid, oldest):
                    newest = self._collect(msg, cid, label, raws, newest)
                    # Pull thread replies for parents that have any.
                    if msg.get("reply_count") and msg.get("thread_ts") == msg.get("ts"):
                        for reply in await self._replies(client, cid, msg["ts"], oldest):
                            if reply.get("ts") == msg.get("ts"):
                                continue  # parent already collected
                            newest = self._collect(reply, cid, label, raws, newest)

        new_cursor = repr(newest) if newest else cursor
        logger.info("slack: %d messages across %d conversations", len(raws), len(conversations))
        return raws, new_cursor

    # ── helpers ──────────────────────────────────────────────────────────────
    def _collect(
        self, msg: dict, cid: str, label: str, raws: list[RawInput], newest: float
    ) -> float:
        if msg.get("subtype") in _SKIP_SUBTYPES:
            return newest
        text = (msg.get("text") or "").strip()
        if not text:
            return newest
        ts = msg["ts"]
        raws.append(
            RawInput(
                kind="slack",
                connector="slack",
                external_id=f"{cid}:{ts}",
                occurred_at=datetime.fromtimestamp(float(ts), tz=UTC),
                text=text,
                title=label,
                meta={
                    "channel": label,
                    "channel_id": cid,
                    "author": msg.get("user"),
                    "thread_ts": msg.get("thread_ts"),
                },
            )
        )
        return max(newest, float(ts))

    @staticmethod
    def _label(ch: dict) -> str:
        if ch.get("is_im"):
            return "DM"
        if ch.get("is_mpim"):
            return ch.get("name") or "group-DM"
        name = ch.get("name")
        return f"#{name}" if name else ch.get("id", "slack")

    async def _conversations(self, client: httpx.AsyncClient) -> list[dict]:
        """All conversations the token's identity is a member of (paginated)."""
        out: list[dict] = []
        cursor = ""
        while True:
            params = {"types": _TYPES, "limit": "200", "exclude_archived": "true"}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get("/users.conversations", params=params)
            body = resp.json()
            if not body.get("ok"):
                logger.warning("slack users.conversations: %s", body.get("error"))
                break
            out.extend(body.get("channels", []))
            cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return out

    async def _history(self, client: httpx.AsyncClient, cid: str, oldest: str) -> list[dict]:
        resp = await client.get(
            "/conversations.history",
            params={"channel": cid, "oldest": oldest, "limit": "100"},
        )
        body = resp.json()
        if not body.get("ok"):
            logger.warning("slack history %s: %s", cid, body.get("error"))
            return []
        return body.get("messages", [])

    async def _replies(
        self, client: httpx.AsyncClient, cid: str, ts: str, oldest: str
    ) -> list[dict]:
        resp = await client.get(
            "/conversations.replies",
            params={"channel": cid, "ts": ts, "oldest": oldest, "limit": "100"},
        )
        body = resp.json()
        if not body.get("ok"):
            logger.warning("slack replies %s/%s: %s", cid, ts, body.get("error"))
            return []
        return body.get("messages", [])
