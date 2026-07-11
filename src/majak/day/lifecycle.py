"""Day lifecycle: ensure days exist, record status events, carry items forward.

Invariants (his explicit requirements):
- `entered_day` = when an item FIRST appeared; it never changes.
- Status changes record `status_at` (timestamp) + `status_day` (the day changed).
- Carrying an unfinished item forward creates a NEW row linked via `carry_from`
  to the origin, so the whole chain is traceable (entered 9.7. → carried → done 11.7.).
- Every mutation writes an `item_events` row.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.models.tables import Day, Item, ItemEvent, ItemPerson, ItemSource
from majak.util.time import now_local


async def ensure_day(session: AsyncSession, day: date, *, status: str = "draft") -> Day:
    row = await session.get(Day, day)
    if row is None:
        row = Day(date=day, status=status)
        session.add(row)
        await session.flush()
    return row


async def open_day(session: AsyncSession, day: date) -> Day:
    row = await ensure_day(session, day, status="open")
    if row.status != "closed":
        row.status = "open"
        if row.opened_at is None:
            row.opened_at = now_local()
    return row


async def close_day(session: AsyncSession, day: date) -> Day:
    row = await ensure_day(session, day)
    row.status = "closed"
    row.closed_at = now_local()
    return row


async def record_event(
    session: AsyncSession,
    item_id: uuid.UUID,
    event_type: str,
    *,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
    on_day: date | None = None,
    actor: str = "pavol",
) -> ItemEvent:
    ev = ItemEvent(
        item_id=item_id,
        type=event_type,
        before=before,
        after=after,
        reason=reason,
        on_day=on_day,
        actor=actor,
    )
    session.add(ev)
    await session.flush()
    return ev


async def set_status(
    session: AsyncSession,
    item: Item,
    status: str,
    *,
    reason: str | None = None,
    on_day: date | None = None,
    actor: str = "pavol",
) -> Item:
    """Change an item's status, stamping when + on which day, and audit it."""
    if status == "deleted" and not reason:
        raise ValueError("A reason is required to delete an item.")

    on_day = on_day or now_local().date()
    before = {"status": item.status, "status_at": _iso(item.status_at), "status_day": _iso(item.status_day)}

    item.status = status
    item.status_at = now_local()
    item.status_day = on_day

    event_type = {"done": "done", "open": "reopen", "deleted": "delete"}.get(status, "edit")
    await record_event(
        session,
        item.id,
        event_type,
        before=before,
        after={"status": status, "status_day": on_day.isoformat()},
        reason=reason,
        on_day=on_day,
        actor=actor,
    )
    return item


async def leaf_ids(session: AsyncSession) -> set[uuid.UUID]:
    """IDs that have been superseded by a later carry row (i.e. are non-leaves).

    A carry chain's *leaf* is the current representation of an item; its parents
    are historical snapshots. A row is a non-leaf if some other row's
    `carry_from` points at it.
    """
    rows = (
        await session.execute(select(Item.carry_from).where(Item.carry_from.is_not(None)))
    ).all()
    return {r[0] for r in rows}


async def carry_unfinished(
    session: AsyncSession, from_day: date, to_day: date
) -> list[uuid.UUID]:
    """Carry every still-open *leaf* item into `to_day`.

    Creates a new row per carried item with `entered_day = to_day` and
    `carry_from` = the immediate parent (the previous day's row). The chain's
    ROOT keeps the true first-appearance day, so walking `carry_from` recovers
    'entered 9.7. → carried → done 11.7.'. Idempotent per (parent, to_day).
    """
    superseded = await leaf_ids(session)

    open_items = (
        await session.execute(
            select(Item).where(Item.status == "open", Item.entered_day <= from_day)
        )
    ).scalars().all()

    # (parent_id -> child.entered_day) already present, for idempotency.
    existing_children = {
        (row.carry_from, row.entered_day)
        for row in (
            await session.execute(select(Item).where(Item.carry_from.is_not(None)))
        ).scalars().all()
    }

    carried: list[uuid.UUID] = []
    for origin in open_items:
        if origin.id in superseded:
            continue  # not a leaf — a newer row already represents it
        if (origin.id, to_day) in existing_children:
            continue  # already carried into to_day

        new_item = Item(
            entered_day=to_day,
            section=origin.section,
            title=origin.title,
            description=origin.description,
            rail=origin.rail,
            owners=list(origin.owners or []),
            chips=list(origin.chips or []),
            list_kind=origin.list_kind,
            carry_from=origin.id,
            status="open",
            order_index=origin.order_index,
        )
        session.add(new_item)
        await session.flush()

        await _copy_links(session, origin.id, new_item.id)
        await record_event(
            session,
            new_item.id,
            "carry",
            before={"from_item": str(origin.id), "from_day": from_day.isoformat()},
            after={"to_day": to_day.isoformat(), "root_entered_day": _iso(origin.entered_day)},
            on_day=to_day,
        )
        carried.append(new_item.id)

    return carried


async def carry_root(session: AsyncSession, item: Item) -> date | None:
    """Walk `carry_from` to the chain root and return its `entered_day`."""
    seen: set[uuid.UUID] = set()
    current = item
    while current.carry_from is not None and current.carry_from not in seen:
        seen.add(current.carry_from)
        parent = await session.get(Item, current.carry_from)
        if parent is None:
            break
        current = parent
    return current.entered_day


async def _copy_links(session: AsyncSession, src_item: uuid.UUID, dst_item: uuid.UUID) -> None:
    """Copy grounding (item_sources) and people links to the carried item."""
    src_sources = (
        await session.execute(select(ItemSource).where(ItemSource.item_id == src_item))
    ).scalars().all()
    for s in src_sources:
        session.add(
            ItemSource(
                item_id=dst_item,
                source_id=s.source_id,
                locator=s.locator,
                quote=s.quote,
                url=s.url,
            )
        )
    src_people = (
        await session.execute(select(ItemPerson).where(ItemPerson.item_id == src_item))
    ).scalars().all()
    for p in src_people:
        session.add(ItemPerson(item_id=dst_item, person_id=p.person_id))
    await session.flush()


def next_day(day: date) -> date:
    return day + timedelta(days=1)


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
