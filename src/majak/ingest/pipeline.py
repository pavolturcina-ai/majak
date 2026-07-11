"""The ingestion pipeline — one entry point for ANY input.

ingest(raw) runs the same 8 steps for scheduled connector items, manual text,
files, and images:

  1. Normalize  → clean text
  2. Classify   → kind, occurred_on, title, topic_tags
  3. People     → resolve participants (non-blocking review on ambiguity)
  4. Extract    → grounded units (verbatim quote + locator + source_id)
  5. Merge      → carry-over linking against open items (no duplicates)
  6. Review     → low-confidence extracts queued
  7. Commit     → sources, files, people, items, item_sources, embeddings, events
  8. Assemble   → rebuild pulse + sections for the affected day

Every extracted item is grounded; nothing is invented; people are never
silently merged. Idempotent on (connector, external_id).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.day.assemble import assemble_day
from majak.day.lifecycle import ensure_day, record_event
from majak.ingest import classify as classify_mod
from majak.ingest import extract as extract_mod
from majak.ingest import merge as merge_mod
from majak.ingest import normalize as normalize_mod
from majak.ingest import people as people_mod
from majak.llm.embeddings import get_embedder
from majak.models.schemas import ExtractedUnit, IngestResult, PersonRef, RawInput
from majak.models.tables import (
    Item,
    ItemPerson,
    ItemSource,
    ReviewQueue,
    Source,
    SourceChunk,
    SourceFile,
    SourceParticipant,
)
from majak.util.text import chunk_text
from majak.util.time import today_local

logger = logging.getLogger(__name__)

# Units below this confidence are surfaced for review (but still committed).
REVIEW_CONFIDENCE = 0.5


async def ingest(session: AsyncSession, raw: RawInput) -> IngestResult:
    result = IngestResult()

    # Idempotency: same (connector, external_id) is ingested once.
    if raw.external_id:
        existing = (
            await session.execute(
                select(Source).where(
                    Source.connector == raw.connector, Source.external_id == raw.external_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            result.source_id = existing.id
            result.skipped_duplicate = True
            result.day = existing.occurred_on
            result.notes.append("duplicate (connector, external_id) — skipped")
            return result

    # 1. Normalize
    norm = await normalize_mod.normalize(raw)

    # 2. Classify
    cls = await classify_mod.classify(raw, norm)
    day = cls.occurred_on or today_local()
    result.day = day

    # 7a. Commit the source first so extraction/grounding can reference it.
    source = Source(
        kind=cls.kind,
        title=cls.title,
        occurred_on=day,
        occurred_at=raw.occurred_at,
        connector=raw.connector,
        external_id=raw.external_id,
        url=raw.url,
        topic_tags=cls.topic_tags,
        raw_text=norm.text,
        storage_path=raw.meta.get("storage_path"),
        meta={**raw.meta, "title_source": "classify"},
    )
    session.add(source)
    await session.flush()
    result.source_id = source.id

    if raw.file_bytes is not None or raw.image_bytes is not None:
        session.add(
            SourceFile(
                source_id=source.id,
                storage_path=raw.meta.get("storage_path"),
                mime=raw.mime,
                ocr_text=norm.ocr_text,
            )
        )

    await ensure_day(session, day, status="open")

    # Semantic chunks (embeddings optional — skipped offline).
    await _embed_source(session, source.id, norm.text)

    # 3. People — resolve participants (speaker labels) + calendar attendees.
    participant_refs = await _resolve_participants(session, raw, norm, source.id, day)
    result.resolved_people.extend(participant_refs)

    # 4. Extract grounded units.
    units = await extract_mod.extract_units(session, source.id, norm)

    # 5 + 7b. Merge / carry-over + commit items.
    for unit in units:
        item_id, carried = await _commit_unit(session, unit, source.id, day, result)
        if carried:
            result.carried_item_ids.append(item_id)
        else:
            result.created_item_ids.append(item_id)

        # 6. Review low-confidence extracts.
        if unit.confidence < REVIEW_CONFIDENCE:
            rid = await _queue_low_confidence(session, source.id, unit, item_id)
            result.review_ids.append(rid)

    # 8. Assemble the affected day.
    await assemble_day(session, day)

    return result


# ── Step helpers ──────────────────────────────────────────────────────────────
async def _resolve_participants(
    session: AsyncSession, raw: RawInput, norm, source_id: uuid.UUID, day: date
) -> list[PersonRef]:
    """Resolve speakers (transcripts) and attendee emails (calendar)."""
    refs: list[PersonRef] = []
    seen: set[str] = set()

    speakers = {seg.get("speaker") for seg in norm.segments if seg.get("speaker")}
    attendees = raw.meta.get("attendees", [])  # list of {name?, email?}

    for name in speakers:
        if name and name.lower() not in seen:
            seen.add(name.lower())
            ref = await people_mod.resolve(
                session, name, context=norm.text[:400], source_id=source_id, seen_on=day
            )
            refs.append(ref)
            await _link_participant(session, source_id, ref)

    for att in attendees:
        name = att.get("name") or att.get("email", "")
        email = att.get("email")
        if name and name.lower() not in seen:
            seen.add(name.lower())
            ref = await people_mod.resolve(
                session, name, email=email, source_id=source_id, seen_on=day
            )
            refs.append(ref)
            await _link_participant(session, source_id, ref)

    return refs


async def _link_participant(session: AsyncSession, source_id: uuid.UUID, ref: PersonRef) -> None:
    if ref.person_id is None:
        return
    exists = await session.get(SourceParticipant, {"source_id": source_id, "person_id": ref.person_id})
    if exists is None:
        session.add(
            SourceParticipant(
                source_id=source_id,
                person_id=ref.person_id,
                raw_name=ref.raw_name,
                confidence=ref.confidence,
            )
        )


async def _commit_unit(
    session: AsyncSession,
    unit: ExtractedUnit,
    source_id: uuid.UUID,
    day: date,
    result: IngestResult,
) -> tuple[uuid.UUID, bool]:
    """Create or carry-link an item for this unit. Returns (item_id, is_carry)."""
    match = await merge_mod.find_carry_over(session, unit)

    if match and match.item.entered_day == day:
        # Same item, same day, another source: merge grounding onto the existing row.
        item = match.item
        await _attach_grounding(session, item.id, source_id, unit)
        await _attach_people(session, item.id, unit, source_id, day)
        result.notes.append(f"merged into existing item {item.id} (score {match.score})")
        return item.id, True

    carry_from = match.item.id if match else None
    is_carry = carry_from is not None

    item = Item(
        entered_day=day,
        section=unit.section,
        title=unit.title,
        description=unit.description,
        rail=unit.rail,
        owners=list(unit.owners),
        chips=list(unit.chips),
        carry_from=carry_from,
        status="open",
    )
    session.add(item)
    await session.flush()

    await _attach_grounding(session, item.id, source_id, unit)
    await _attach_people(session, item.id, unit, source_id, day)

    await record_event(
        session,
        item.id,
        "carry" if is_carry else "create",
        after={"section": unit.section, "title": unit.title, "carry_from": str(carry_from) if carry_from else None},
        on_day=day,
    )
    if is_carry:
        result.notes.append(f"carried from {carry_from} (score {match.score})")
    return item.id, is_carry


async def _attach_grounding(
    session: AsyncSession, item_id: uuid.UUID, source_id: uuid.UUID, unit: ExtractedUnit
) -> None:
    for g in unit.grounding:
        locator = g.locator or ""
        exists = await session.get(
            ItemSource, {"item_id": item_id, "source_id": source_id, "locator": locator}
        )
        if exists is None:
            session.add(
                ItemSource(
                    item_id=item_id,
                    source_id=source_id,
                    locator=locator,
                    quote=g.quote,
                    url=g.url,
                )
            )


async def _attach_people(
    session: AsyncSession,
    item_id: uuid.UUID,
    unit: ExtractedUnit,
    source_id: uuid.UUID,
    day: date,
) -> None:
    for raw_name in unit.people:
        ref = await people_mod.resolve(
            session, raw_name, source_id=source_id, seen_on=day, auto_create=True
        )
        if ref.person_id is not None:
            link = await session.get(
                ItemPerson, {"item_id": item_id, "person_id": ref.person_id}
            )
            if link is None:
                session.add(ItemPerson(item_id=item_id, person_id=ref.person_id))


async def _embed_source(session: AsyncSession, source_id: uuid.UUID, text: str) -> None:
    chunks = chunk_text(text)
    if not chunks:
        return
    embedder = get_embedder()
    vectors = await embedder.embed(chunks) if embedder.available else [None] * len(chunks)
    for chunk, vec in zip(chunks, vectors, strict=False):
        session.add(SourceChunk(source_id=source_id, chunk=chunk, embedding=vec))


async def _queue_low_confidence(
    session: AsyncSession, source_id: uuid.UUID, unit: ExtractedUnit, item_id: uuid.UUID
) -> uuid.UUID:
    row = ReviewQueue(
        kind="low_confidence_extract",
        payload={
            "source_id": str(source_id),
            "item_id": str(item_id),
            "title": unit.title,
            "section": unit.section,
            "confidence": unit.confidence,
        },
        status="pending",
    )
    session.add(row)
    await session.flush()
    return row.id
