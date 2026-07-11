"""Timezone helpers — MAJÁK operates in Europe/Bratislava."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from majak.config import settings

LOCAL_TZ = ZoneInfo(settings.tz)


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def today_local() -> date:
    return now_local().date()


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def local_date_of(dt: datetime) -> date:
    return to_local(dt).date()
