"""Fathom connector — meeting recordings + transcripts.

Cursor = ISO timestamp of the most recent recording ingested. Only the current
day is pulled: the first run floors at the start of today (local tz); later runs
advance via the cursor. Overlap is harmless (dedupe on external_id).

NOTE: Fathom's public API is versioned and its exact paths/auth may change.
The endpoint + auth-header constants below are isolated so they are trivial to
adjust after the first live test (the scheduler logs a clear error per
connector). Verify against the current Fathom API docs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from majak.config import settings
from majak.models.schemas import RawInput
from majak.util.time import now_local

logger = logging.getLogger(__name__)

# ── Adjust these to match the current Fathom API if the first test 404s/401s ──
FATHOM_BASE = "https://api.fathom.ai/external/v1"
FATHOM_LIST = "/meetings"           # list recordings/meetings
FATHOM_TRANSCRIPT = "/meetings/{id}/transcript"
AUTH_HEADER = "X-Api-Key"           # some deployments use "Authorization: Bearer"


class FathomConnector:
    name = "fathom"

    @property
    def configured(self) -> bool:
        return bool(settings.fathom_api_key)

    def _headers(self) -> dict[str, str]:
        if AUTH_HEADER.lower() == "authorization":
            return {"Authorization": f"Bearer {settings.fathom_api_key}"}
        return {AUTH_HEADER: settings.fathom_api_key}

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        if not self.configured:
            logger.info("fathom not configured; skipping")
            return [], cursor

        headers = self._headers()
        # Current day only: floor at start of today (local); later runs use cursor.
        day_start = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        params: dict[str, str] = {"limit": "25", "created_after": cursor or day_start.isoformat()}

        raws: list[RawInput] = []
        newest = cursor
        async with httpx.AsyncClient(timeout=45, base_url=FATHOM_BASE, headers=headers) as client:
            resp = await client.get(FATHOM_LIST, params=params)
            resp.raise_for_status()
            payload = resp.json()
            meetings = payload.get("items") or payload.get("meetings") or payload.get("data") or []

            for m in meetings:
                mid = str(m.get("id") or m.get("recording_id") or "")
                if not mid:
                    continue
                started = m.get("started_at") or m.get("created_at") or m.get("scheduled_start_time")
                transcript = m.get("transcript")
                if not transcript:
                    transcript = await self._transcript(client, mid)
                if not transcript:
                    continue
                attendees = [
                    {"name": a.get("name") or a.get("display_name") or a.get("email", ""),
                     "email": a.get("email")}
                    for a in (m.get("attendees") or m.get("participants") or [])
                ]
                raws.append(
                    RawInput(
                        kind="fathom",
                        connector="fathom",
                        external_id=mid,
                        title=m.get("title") or m.get("meeting_title") or "Fathom meeting",
                        occurred_at=_parse_dt(started),
                        url=m.get("share_url") or m.get("url"),
                        text=transcript,
                        meta={"attendees": attendees, "summary": m.get("summary")},
                    )
                )
                if started and (newest is None or started > newest):
                    newest = started

        logger.info("fathom: %d meetings", len(raws))
        return raws, newest

    async def _transcript(self, client: httpx.AsyncClient, mid: str) -> str:
        try:
            resp = await client.get(FATHOM_TRANSCRIPT.format(id=mid))
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, str):
                return data
            # Common shapes: {transcript: "..."} or {segments:[{speaker,text,timestamp}]}
            if isinstance(data, dict):
                if data.get("transcript"):
                    return data["transcript"]
                segments = data.get("segments") or data.get("lines") or []
                return "\n".join(
                    f"{s.get('timestamp', '')}\n{s.get('speaker', '')}\n{s.get('text', '')}".strip()
                    for s in segments
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("fathom transcript %s failed: %s", mid, exc)
        return ""


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (ValueError, OverflowError):
            return None
