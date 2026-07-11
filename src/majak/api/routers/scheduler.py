"""Scheduler trigger endpoints for pg_cron / edge functions.

Guarded by the cron secret (not the user JWT), so the DB-side scheduler can call
them without a user session.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import DbSession, require_cron
from majak.scheduler.jobs import close_and_open_tomorrow, fill_overnight

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.post("/close-and-open", dependencies=[Depends(require_cron)])
async def run_close_and_open(session: AsyncSession = DbSession) -> dict:
    return await close_and_open_tomorrow(session)


@router.post("/fill-overnight", dependencies=[Depends(require_cron)])
async def run_fill_overnight(session: AsyncSession = DbSession) -> dict:
    return await fill_overnight(session)
