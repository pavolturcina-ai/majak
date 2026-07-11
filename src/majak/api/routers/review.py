"""Review queue: list + resolve (confirm person / merge / dismiss).

Confirming an ambiguous person stores the raw spelling as a confirmed_typo alias
so resolution never asks about it again (the alias-learning loop).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import CurrentUser, DbSession
from majak.ingest import people as people_mod
from majak.models.schemas import ReviewResolveRequest
from majak.models.tables import Person, ReviewQueue
from majak.util.text import normalize_name
from majak.util.time import now_local

router = APIRouter(prefix="/review-queue", tags=["review"])


@router.get("", dependencies=[CurrentUser])
async def list_review(
    status: str = "pending", session: AsyncSession = DbSession
) -> list[dict]:
    rows = (
        await session.execute(
            select(ReviewQueue).where(ReviewQueue.status == status).order_by(ReviewQueue.created_at)
        )
    ).scalars().all()
    return [
        {"id": str(r.id), "kind": r.kind, "payload": r.payload, "created_at": r.created_at}
        for r in rows
    ]


@router.post("/{review_id}/resolve", dependencies=[CurrentUser])
async def resolve_review(
    review_id: uuid.UUID, body: ReviewResolveRequest, session: AsyncSession = DbSession
) -> dict:
    row = await session.get(ReviewQueue, review_id)
    if row is None:
        raise HTTPException(404, "No such review item")
    if row.status != "pending":
        raise HTTPException(409, f"Already {row.status}")

    result: dict = {"id": str(review_id)}

    if body.dismiss:
        row.status = "dismissed"
    elif row.kind == "person_ambiguous":
        result.update(await _resolve_person_ambiguous(session, row, body))
        row.status = "resolved"
    else:
        row.status = "resolved"
        result["note"] = body.note

    row.resolved_at = now_local()
    return {**result, "status": row.status}


async def _resolve_person_ambiguous(
    session: AsyncSession, row: ReviewQueue, body: ReviewResolveRequest
) -> dict:
    payload = row.payload or {}
    raw_name = payload.get("raw_name", "")

    if body.create_new:
        person = Person(canonical_name=raw_name, normalized_name=normalize_name(raw_name))
        session.add(person)
        await session.flush()
        return {"created_person_id": str(person.id)}

    if body.person_id is not None:
        person = await session.get(Person, body.person_id)
        if person is None:
            raise HTTPException(404, "Chosen person not found")
        # Learn the spelling so this never asks again.
        alias = await people_mod.add_alias(
            session, person.id, raw_name, kind="confirmed_typo"
        )
        # If the ambiguity auto-created a placeholder person, fold it in as an alias too.
        created = payload.get("created_person_id")
        if created and created != str(person.id):
            placeholder = await session.get(Person, uuid.UUID(created))
            if placeholder is not None:
                await people_mod.add_alias(
                    session, person.id, placeholder.canonical_name, kind="variant"
                )
        return {"linked_person_id": str(person.id), "alias_id": str(alias.id)}

    raise HTTPException(422, "Provide person_id, create_new, or dismiss")
