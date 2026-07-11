"""Fathom connector — meeting recordings + transcripts.

Cursor = ISO timestamp of the most recent recording ingested. Reuse the CEO's
MCP Fathom connector where available; this direct-API path is the fallback.
"""

from __future__ import annotations

import logging

from majak.config import settings
from majak.models.schemas import RawInput

logger = logging.getLogger(__name__)


class FathomConnector:
    name = "fathom"

    @property
    def configured(self) -> bool:
        return bool(settings.fathom_api_key)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        if not self.configured:
            logger.info("fathom connector not configured; skipping")
            return [], cursor

        # Real implementation outline:
        #   1. list_meetings(created_after=cursor).
        #   2. get_meeting_transcript(recording_id) -> timestamped lines.
        #   3. RawInput(kind='fathom', connector='fathom', external_id=recording_id,
        #        occurred_at=call_started_at, text=transcript, url=share_url,
        #        meta={"attendees": [{name,email}], "summary": summary}).
        #   4. new cursor = max(created_at).
        raise NotImplementedError(
            "Fathom direct-API fetch not wired; provide an API key or route via MCP."
        )
