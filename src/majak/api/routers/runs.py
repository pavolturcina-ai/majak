"""Job runs: history of the scheduled runs (Behy) for observability."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import CurrentUser, DbSession
from majak.models.tables import JobRun

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", dependencies=[CurrentUser])
async def list_runs(limit: int = 50, session: AsyncSession = DbSession) -> list[dict]:
    rows = (
        await session.execute(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "job": r.job,
            "on_day": r.on_day,
            "status": r.status,
            "stats": r.stats,
            "error": r.error,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
        }
        for r in rows
    ]
