"""Build the day view (pulse + sections) from items.

`get_day_view` is the read model used by the API. `assemble_day` (re)generates
the pulse/summary after ingest — LLM when available, heuristic otherwise.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.llm.client import get_llm
from majak.llm.prompts import PULSE_V1
from majak.models.schemas import DayView, GroundingOut, ItemOut
from majak.models.tables import Day, Item, ItemPerson, ItemSource

logger = logging.getLogger(__name__)

SECTION_ORDER = ["top", "decision", "good", "threat", "deleg", "quick", "radar"]


async def get_day_view(session: AsyncSession, day: date, *, include_deleted: bool = False) -> DayView | None:
    """Return the full day view: pulse + sections + items + grounding + people."""
    day_row = await session.get(Day, day)
    if day_row is None:
        return None

    stmt = select(Item).where(Item.entered_day == day)
    if not include_deleted:
        stmt = stmt.where(Item.status != "deleted")
    stmt = stmt.order_by(Item.section, Item.order_index, Item.created_at)
    items = (await session.execute(stmt)).scalars().all()

    sections: dict[str, list[ItemOut]] = {s: [] for s in SECTION_ORDER}
    for item in items:
        sections[item.section].append(await _item_out(session, item))

    return DayView(
        date=day_row.date,
        status=day_row.status,
        pulse=day_row.pulse,
        summary=day_row.summary,
        opened_at=day_row.opened_at,
        closed_at=day_row.closed_at,
        sections=sections,
    )


async def current_open_items(session: AsyncSession) -> list[ItemOut]:
    """The 'all current' view — every open *leaf* item across days.

    Excludes rows that a later carry row has superseded, so a task carried across
    several days shows once (its newest representation), not once per day.
    """
    from majak.day.lifecycle import leaf_ids

    superseded = await leaf_ids(session)
    items = (
        await session.execute(
            select(Item).where(Item.status == "open").order_by(Item.section, Item.order_index)
        )
    ).scalars().all()
    return [await _item_out(session, it) for it in items if it.id not in superseded]


async def _item_out(session: AsyncSession, item: Item) -> ItemOut:
    grounding = (
        await session.execute(select(ItemSource).where(ItemSource.item_id == item.id))
    ).scalars().all()
    people = (
        await session.execute(select(ItemPerson).where(ItemPerson.item_id == item.id))
    ).scalars().all()
    return ItemOut(
        id=item.id,
        entered_day=item.entered_day,
        section=item.section,
        title=item.title,
        description=item.description,
        rail=item.rail,
        owners=list(item.owners or []),
        chips=list(item.chips or []),
        list_kind=item.list_kind,
        carry_from=item.carry_from,
        status=item.status,
        status_at=item.status_at,
        status_day=item.status_day,
        order_index=item.order_index,
        people=[p.person_id for p in people],
        grounding=[
            GroundingOut(source_id=g.source_id, quote=g.quote, locator=g.locator or None, url=g.url)
            for g in grounding
        ],
    )


async def assemble_day(session: AsyncSession, day: date) -> Day:
    """Regenerate pulse + summary for a day from its current items."""
    day_row = await session.get(Day, day)
    if day_row is None:
        from majak.day.lifecycle import ensure_day

        day_row = await ensure_day(session, day)

    items = (
        await session.execute(
            select(Item).where(Item.entered_day == day, Item.status != "deleted")
        )
    ).scalars().all()

    if not items:
        day_row.pulse = day_row.pulse or "Zatiaľ žiadne položky."
        return day_row

    grouped: dict[str, list[dict]] = {}
    for it in items:
        grouped.setdefault(it.section, []).append({"title": it.title, "rail": it.rail})

    llm = get_llm()
    if llm.available:
        try:
            data = await llm.complete_json(
                PULSE_V1.format(day=day.isoformat(), items_json=json.dumps(grouped, ensure_ascii=False)),
                route="synth",
                max_tokens=500,
            )
            day_row.pulse = data.get("pulse") or day_row.pulse
            day_row.summary = data.get("summary") or day_row.summary
            return day_row
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM pulse failed, using heuristic: %s", exc)

    day_row.pulse, day_row.summary = _heuristic_pulse(grouped)
    return day_row


def _heuristic_pulse(grouped: dict[str, list[dict]]) -> tuple[str, str]:
    n_threat = len(grouped.get("threat", []))
    n_dec = len(grouped.get("decision", []))
    n_good = len(grouped.get("good", []))
    n_top = len(grouped.get("top", []))
    pulse = f"{n_top} priorít · {n_threat} hrozieb · {n_dec} rozhodnutí · {n_good} dobrých správ"
    parts = []
    if n_top:
        parts.append(f"{n_top} vecí na akciu")
    if n_threat:
        parts.append(f"{n_threat} rizík na sledovanie")
    if n_dec:
        parts.append(f"{n_dec} rozhodnutí")
    if n_good:
        parts.append(f"{n_good} pozitívnych signálov")
    summary = "Dnešný deň: " + ", ".join(parts) + "." if parts else "Dnešný deň bez zásadných udalostí."
    return pulse, summary
