"""Google Calendar connector.

Used by the 18:00 job to pull *tomorrow's* meetings into radar entries and to
attach attendee dossiers. Cursor = a sync token (incremental sync) when
available. Reuse the CEO's MCP Calendar connector where available.
"""

from __future__ import annotations

import logging
from datetime import date

from majak.config import settings
from majak.models.schemas import RawInput

logger = logging.getLogger(__name__)


class GoogleCalendarConnector:
    name = "gcal"

    @property
    def configured(self) -> bool:
        return bool(settings.gcal_client_id and settings.gcal_refresh_token)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        # Default fetch is not window-based for calendar; use fetch_day for a
        # specific date (the 18:00 job pulls tomorrow explicitly).
        if not self.configured:
            logger.info("gcal connector not configured; skipping")
            return [], cursor
        raise NotImplementedError("Use fetch_day(target) for calendar pulls.")

    async def fetch_day(self, target: date) -> list[RawInput]:
        """Return one RawInput per meeting on `target` (kind='calendar')."""
        if not self.configured:
            logger.info("gcal connector not configured; skipping calendar pull for %s", target)
            return []

        # Real implementation outline:
        #   1. events.list(calendarId, timeMin=target 00:00, timeMax=target 23:59,
        #        singleEvents=True, orderBy='startTime').
        #   2. RawInput(kind='calendar', connector='gcal', external_id=event_id,
        #        occurred_on=target, occurred_at=start,
        #        title=summary, text=description,
        #        meta={"attendees": [{name, email}], "location": ..., "start": ...}).
        raise NotImplementedError(
            "Calendar fetch not wired; provide OAuth creds or route via MCP."
        )
