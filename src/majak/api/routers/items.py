"""Items: edit, status (done/reopen/delete), list-tag, reorder — all audited."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import CurrentUser, DbSession
from majak.day.assemble import _item_out, assemble_day
from majak.day.lifecycle import record_event, set_status
from majak.models.schemas import (
    ItemOut,
    ItemPatch,
    ListTag,
    ReorderRequest,
    StatusChange,
)
from majak.models.tables import Item

router = APIRouter(prefix="/items", tags=["items"])

_EDITABLE = ("title", "description", "section", "rail", "owners", "chips", "order_index")


@router.get("", response_model=list[ItemOut], dependencies=[CurrentUser])
async def list_items(
    status: str | None = None,
    section: str | None = None,
    session: AsyncSession = DbSession,
) -> list[ItemOut]:
    stmt = select(Item)
    if status:
        stmt = stmt.where(Item.status == status)
    if section:
        stmt = stmt.where(Item.section == section)
    stmt = stmt.order_by(Item.entered_day.desc(), Item.order_index)
    rows = (await session.execute(stmt)).scalars().all()
    return [await _item_out(session, it) for it in rows]


@router.get("/{item_id}", response_model=ItemOut, dependencies=[CurrentUser])
async def get_item(item_id: uuid.UUID, session: AsyncSession = DbSession) -> ItemOut:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "No such item")
    return await _item_out(session, item)


@router.patch("/{item_id}", response_model=ItemOut, dependencies=[CurrentUser])
async def edit_item(
    item_id: uuid.UUID, patch: ItemPatch, session: AsyncSession = DbSession
) -> ItemOut:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "No such item")

    before = {f: getattr(item, f) for f in _EDITABLE}
    changes = patch.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(item, field, value)
    after = {f: getattr(item, f) for f in _EDITABLE}

    await record_event(
        session, item.id, "edit", before=_jsonable(before), after=_jsonable(after),
        on_day=item.entered_day,
    )
    if item.entered_day:
        await assemble_day(session, item.entered_day)
    return await _item_out(session, item)


@router.post("/{item_id}/status", response_model=ItemOut, dependencies=[CurrentUser])
async def change_status(
    item_id: uuid.UUID, body: StatusChange, session: AsyncSession = DbSession
) -> ItemOut:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "No such item")
    if body.status == "deleted" and not body.reason:
        raise HTTPException(422, "A reason is required to delete an item")
    try:
        await set_status(session, item, body.status, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if item.entered_day:
        await assemble_day(session, item.entered_day)
    return await _item_out(session, item)


@router.post("/{item_id}/list", response_model=ItemOut, dependencies=[CurrentUser])
async def tag_list(
    item_id: uuid.UUID, body: ListTag, session: AsyncSession = DbSession
) -> ItemOut:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "No such item")
    before = {"list_kind": item.list_kind}
    item.list_kind = body.kind
    await record_event(
        session, item.id, "tag", before=before, after={"list_kind": body.kind},
        on_day=item.entered_day,
    )
    return await _item_out(session, item)


@router.post("/reorder", dependencies=[CurrentUser])
async def reorder(body: ReorderRequest, session: AsyncSession = DbSession) -> dict:
    for index, item_id in enumerate(body.ordered_ids):
        item = await session.get(Item, item_id)
        if item is not None:
            item.order_index = index
    return {"reordered": len(body.ordered_ids)}


def _jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        out[k] = v.isoformat() if isinstance(v, date) else v
    return out
