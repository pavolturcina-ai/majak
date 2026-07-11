"""Day views: /days, /days/current, /days/{date}, plus the 'all current' list."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import CurrentUser, DbSession
from majak.day.assemble import current_open_items, get_day_view
from majak.models.schemas import DayView, ItemOut
from majak.models.tables import Day

router = APIRouter(prefix="/days", tags=["days"])


@router.get("", dependencies=[CurrentUser])
async def list_days(session: AsyncSession = DbSession) -> list[dict]:
    rows = (await session.execute(select(Day).order_by(Day.date.desc()))).scalars().all()
    return [
        {"date": d.date, "status": d.status, "pulse": d.pulse, "closed_at": d.closed_at}
        for d in rows
    ]


@router.get("/current", response_model=DayView, dependencies=[CurrentUser])
async def current_day(session: AsyncSession = DbSession) -> DayView:
    """The latest open day, else the most recent day."""
    row = (
        await session.execute(
            select(Day).where(Day.status == "open").order_by(Day.date.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        row = (
            await session.execute(select(Day).order_by(Day.date.desc()).limit(1))
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "No days yet")
    view = await get_day_view(session, row.date)
    assert view is not None
    return view


@router.get("/all-current", response_model=list[ItemOut], dependencies=[CurrentUser])
async def all_current(session: AsyncSession = DbSession) -> list[ItemOut]:
    """Every open item across days (leaf rows only)."""
    return await current_open_items(session)


@router.get("/{day}", response_model=DayView, dependencies=[CurrentUser])
async def get_day(day: date, session: AsyncSession = DbSession) -> DayView:
    view = await get_day_view(session, day)
    if view is None:
        raise HTTPException(404, f"No day {day}")
    return view
