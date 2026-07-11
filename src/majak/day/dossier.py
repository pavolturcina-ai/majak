"""Pre-meeting dossier for a person.

Identity + every source they appear in + open items involving them + recent
interactions + LLM-suggested questions. Calendar meetings attach this for
attendees (see scheduler).
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.day.assemble import _item_out
from majak.llm.client import get_llm
from majak.llm.prompts import DOSSIER_QUESTIONS_V1
from majak.models.schemas import PersonBrief, PersonOut
from majak.models.tables import Item, ItemPerson, Person, Source, SourceParticipant

logger = logging.getLogger(__name__)


async def build_brief(session: AsyncSession, person_id: uuid.UUID) -> PersonBrief | None:
    person = await session.get(Person, person_id)
    if person is None:
        return None

    # Sources this person appears in.
    part_rows = (
        await session.execute(
            select(SourceParticipant).where(SourceParticipant.person_id == person_id)
        )
    ).scalars().all()
    source_ids = [p.source_id for p in part_rows]
    sources = []
    topics: set[str] = set()
    if source_ids:
        src_rows = (
            await session.execute(select(Source).where(Source.id.in_(source_ids)))
        ).scalars().all()
        for s in sorted(src_rows, key=lambda x: x.occurred_at or x.created_at, reverse=True):
            sources.append(
                {
                    "id": str(s.id),
                    "kind": s.kind,
                    "title": s.title,
                    "occurred_on": s.occurred_on.isoformat() if s.occurred_on else None,
                    "url": s.url,
                }
            )
            topics.update(s.topic_tags or [])

    # Open items involving them.
    item_link_rows = (
        await session.execute(select(ItemPerson).where(ItemPerson.person_id == person_id))
    ).scalars().all()
    item_ids = [r.item_id for r in item_link_rows]
    open_items = []
    if item_ids:
        items = (
            await session.execute(
                select(Item).where(Item.id.in_(item_ids), Item.status == "open")
            )
        ).scalars().all()
        open_items = [await _item_out(session, it) for it in items]

    person_out = PersonOut(
        id=person.id,
        canonical_name=person.canonical_name,
        role=person.role,
        org=person.org,
        email=person.email,
        linkedin=person.linkedin,
        tags=list(person.tags or []),
        first_seen=person.first_seen,
        last_seen=person.last_seen,
    )

    questions = await _suggest_questions(person_out, open_items, sources[:5])

    return PersonBrief(
        person=person_out,
        sources=sources,
        open_items=open_items,
        topics=sorted(topics),
        last_interactions=sources[:5],
        suggested_questions=questions,
    )


async def _suggest_questions(person: PersonOut, open_items: list, recent: list) -> list[str]:
    llm = get_llm()
    if llm.available:
        try:
            data = await llm.complete_json(
                DOSSIER_QUESTIONS_V1.format(
                    person_json=person.model_dump_json(),
                    open_items_json=json.dumps(
                        [{"title": i.title, "section": i.section} for i in open_items],
                        ensure_ascii=False,
                    ),
                    recent_json=json.dumps(recent, ensure_ascii=False),
                ),
                route="synth",
                max_tokens=500,
            )
            if isinstance(data, list):
                return [str(q) for q in data][:5]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Dossier question generation failed: %s", exc)

    # Heuristic fallback: turn open items into follow-up prompts.
    return [f"Aký je stav: {i.title}?" for i in open_items[:5]] or [
        "Na čom aktuálne pracujeme spolu?"
    ]
