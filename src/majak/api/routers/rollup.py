"""Roll-up: closed-item log grouped by day (the weekly roll-up)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import CurrentUser, DbSession
from majak.models.tables import Item

router = APIRouter(prefix="/rollup", tags=["rollup"])


@router.get("", dependencies=[CurrentUser])
async def rollup(
    from_: date = Query(alias="from"),
    to: date = Query(...),
    session: AsyncSession = DbSession,
) -> dict:
    """Items closed (done/deleted) within [from, to], grouped by status_day."""
    rows = (
        await session.execute(
            select(Item).where(
                Item.status.in_(["done", "deleted"]),
                Item.status_day >= from_,
                Item.status_day <= to,
            ).order_by(Item.status_day)
        )
    ).scalars().all()

    by_day: dict[str, list[dict]] = {}
    for it in rows:
        key = it.status_day.isoformat() if it.status_day else "unknown"
        by_day.setdefault(key, []).append(
            {
                "id": str(it.id),
                "title": it.title,
                "section": it.section,
                "status": it.status,
                "entered_day": it.entered_day.isoformat() if it.entered_day else None,
                "status_at": it.status_at,
            }
        )
    return {"from": from_, "to": to, "days": by_day, "total": len(rows)}
