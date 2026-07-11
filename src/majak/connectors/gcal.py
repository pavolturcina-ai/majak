"""Google Calendar connector.

Used by the 18:00 job to pull a specific day's meetings into radar entries and
attendee dossiers. Reads events via the Calendar v3 API with an OAuth refresh
token. `fetch_since` is unused (calendar is pulled per-day via `fetch_day`).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import httpx

from majak.config import settings
from majak.connectors._google import access_token
from majak.models.schemas import RawInput
from majak.util.time import LOCAL_TZ

logger = logging.getLogger(__name__)

_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"


class GoogleCalendarConnector:
    name = "gcal"

    @property
    def configured(self) -> bool:
        return bool(settings.gcal_client_id and settings.gcal_refresh_token)

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        # Calendar is pulled per-day by the 18:00 job, not window-based.
        return [], cursor

    async def fetch_day(self, target: date) -> list[RawInput]:
        if not self.configured:
            logger.info("gcal not configured; skipping calendar pull for %s", target)
            return []

        token = await access_token(
            settings.gcal_client_id, settings.gcal_client_secret, settings.gcal_refresh_token
        )
        time_min = datetime.combine(target, time.min, tzinfo=LOCAL_TZ)
        time_max = datetime.combine(target, time.max, tzinfo=LOCAL_TZ)

        params = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "50",
        }
        url = _EVENTS_URL.format(cal=settings.gcal_calendar_id)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {token}"}
            )
            resp.raise_for_status()
            events = resp.json().get("items", [])

        raws: list[RawInput] = []
        for ev in events:
            if ev.get("status") == "cancelled":
                continue
            start = ev.get("start", {})
            start_at = start.get("dateTime") or start.get("date")
            attendees = [
                {"name": a.get("displayName") or a.get("email", ""), "email": a.get("email")}
                for a in ev.get("attendees", [])
                if not a.get("resource")
            ]
            raws.append(
                RawInput(
                    kind="calendar",
                    connector="gcal",
                    external_id=ev.get("id"),
                    title=ev.get("summary") or "(bez názvu)",
                    occurred_on=target,
                    occurred_at=_parse_dt(start_at),
                    url=ev.get("htmlLink"),
                    text=ev.get("description") or "",
                    meta={
                        "attendees": attendees,
                        "location": ev.get("location"),
                        "organizer": ev.get("organizer", {}).get("email"),
                        "start": start_at,
                    },
                )
            )
        logger.info("gcal: %d events on %s", len(raws), target)
        return raws


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if len(value) == 10:  # all-day 'YYYY-MM-DD'
            return datetime.fromisoformat(value + "T00:00:00").replace(tzinfo=LOCAL_TZ)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_ = timedelta  # kept for readability of window math above
