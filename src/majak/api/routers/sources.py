"""Sources: list + full transcript for the 'Podklady & pokrytie' panel."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import CurrentUser, DbSession
from majak.models.tables import Source, SourceParticipant

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", dependencies=[CurrentUser])
async def list_sources(
    limit: int = 100, session: AsyncSession = DbSession
) -> list[dict]:
    rows = (
        await session.execute(
            select(Source).order_by(Source.occurred_at.desc().nullslast()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(s.id),
            "kind": s.kind,
            "title": s.title,
            "occurred_on": s.occurred_on,
            "connector": s.connector,
            "url": s.url,
            "topic_tags": s.topic_tags,
        }
        for s in rows
    ]


@router.get("/{source_id}", dependencies=[CurrentUser])
async def get_source(source_id: uuid.UUID, session: AsyncSession = DbSession) -> dict:
    s = await session.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "No such source")
    participants = (
        await session.execute(
            select(SourceParticipant).where(SourceParticipant.source_id == source_id)
        )
    ).scalars().all()
    return {
        "id": str(s.id),
        "kind": s.kind,
        "title": s.title,
        "occurred_on": s.occurred_on,
        "occurred_at": s.occurred_at,
        "connector": s.connector,
        "url": s.url,
        "topic_tags": s.topic_tags,
        "raw_text": s.raw_text,
        "meta": s.meta,
        "participants": [
            {"person_id": str(p.person_id), "raw_name": p.raw_name, "confidence": p.confidence}
            for p in participants
        ],
    }
