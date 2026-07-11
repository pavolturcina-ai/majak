"""People: list, brief (dossier), resolve, add alias."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import CurrentUser, DbSession
from majak.day.dossier import build_brief
from majak.ingest import people as people_mod
from majak.models.schemas import (
    AliasRequest,
    PersonBrief,
    PersonOut,
    PersonRef,
    ResolvePersonRequest,
)
from majak.models.tables import Person

router = APIRouter(prefix="/people", tags=["people"])


@router.get("", response_model=list[PersonOut], dependencies=[CurrentUser])
async def list_people(session: AsyncSession = DbSession) -> list[PersonOut]:
    rows = (await session.execute(select(Person).order_by(Person.canonical_name))).scalars().all()
    return [_to_out(p) for p in rows]


@router.get("/{person_id}/brief", response_model=PersonBrief, dependencies=[CurrentUser])
async def person_brief(person_id: uuid.UUID, session: AsyncSession = DbSession) -> PersonBrief:
    brief = await build_brief(session, person_id)
    if brief is None:
        raise HTTPException(404, "No such person")
    return brief


@router.post("/resolve", response_model=PersonRef, dependencies=[CurrentUser])
async def resolve_person(
    body: ResolvePersonRequest, session: AsyncSession = DbSession
) -> PersonRef:
    return await people_mod.resolve(
        session, body.raw_name, context=body.context, auto_create=False
    )


@router.post("/{person_id}/aliases", dependencies=[CurrentUser])
async def add_alias(
    person_id: uuid.UUID, body: AliasRequest, session: AsyncSession = DbSession
) -> dict:
    person = await session.get(Person, person_id)
    if person is None:
        raise HTTPException(404, "No such person")
    alias = await people_mod.add_alias(session, person_id, body.alias, kind=body.kind)
    return {"id": str(alias.id), "alias": alias.alias, "kind": alias.kind}


def _to_out(p: Person) -> PersonOut:
    return PersonOut(
        id=p.id,
        canonical_name=p.canonical_name,
        role=p.role,
        org=p.org,
        email=p.email,
        linkedin=p.linkedin,
        tags=list(p.tags or []),
        first_seen=p.first_seen,
        last_seen=p.last_seen,
    )
