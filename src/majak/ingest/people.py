"""People extraction, resolution, confirm-queue, and alias learning.

Resolution flow (per the spec):
  score >= PERSON_MATCH_LINK      -> link
  PERSON_MATCH_REVIEW..LINK       -> do not guess; queue person_ambiguous, continue
  < PERSON_MATCH_REVIEW           -> create a new person (also surfaced for review)

When the CEO confirms an ambiguous match, the raw spelling is stored as a
`confirmed_typo` alias so the same input never asks again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.config import settings
from majak.models.schemas import PersonRef
from majak.models.tables import Person, PersonAlias, ReviewQueue
from majak.util.text import normalize_name


@dataclass
class Candidate:
    person_id: uuid.UUID
    canonical_name: str
    normalized: str
    score: float
    via: str  # 'name' | 'alias' | 'email'


def score_names(query_norm: str, candidate_norm: str) -> float:
    """Similarity in [0, 1] between two normalized names.

    Uses token_sort_ratio (order-insensitive) blended with WRatio to reward
    'Pavol Turcina' == 'Turcina Pavol' while still catching typos.
    """
    if not query_norm or not candidate_norm:
        return 0.0
    if query_norm == candidate_norm:
        return 1.0
    token = fuzz.token_sort_ratio(query_norm, candidate_norm) / 100.0
    wr = fuzz.WRatio(query_norm, candidate_norm) / 100.0
    return round(max(token, 0.5 * token + 0.5 * wr), 4)


async def _load_candidates(session: AsyncSession, raw_name: str, email: str | None) -> list[Candidate]:
    """Score the raw name against every person + alias (single-user scale)."""
    query_norm = normalize_name(raw_name)
    candidates: dict[uuid.UUID, Candidate] = {}

    # Exact email match short-circuits everything with full confidence.
    if email:
        row = (
            await session.execute(select(Person).where(Person.email.ilike(email)))
        ).scalar_one_or_none()
        if row is not None:
            candidates[row.id] = Candidate(row.id, row.canonical_name, row.normalized_name, 1.0, "email")

    people = (await session.execute(select(Person))).scalars().all()
    for p in people:
        s = score_names(query_norm, p.normalized_name)
        cur = candidates.get(p.id)
        if cur is None or s > cur.score:
            candidates[p.id] = Candidate(p.id, p.canonical_name, p.normalized_name, s, "name")

    aliases = (await session.execute(select(PersonAlias))).scalars().all()
    for a in aliases:
        s = score_names(query_norm, a.normalized)
        cur = candidates.get(a.person_id)
        if cur is None or s > cur.score:
            # Keep the canonical name for display; note it matched via alias.
            person = next((p for p in people if p.id == a.person_id), None)
            name = person.canonical_name if person else a.alias
            norm = person.normalized_name if person else a.normalized
            candidates[a.person_id] = Candidate(a.person_id, name, norm, s, "alias")

    return sorted(candidates.values(), key=lambda c: c.score, reverse=True)


async def resolve(
    session: AsyncSession,
    raw_name: str,
    *,
    context: str | None = None,
    email: str | None = None,
    source_id: uuid.UUID | None = None,
    seen_on: date | None = None,
    auto_create: bool = True,
) -> PersonRef:
    """Resolve a raw name to a person. May create a new person or a review row."""
    raw_name = raw_name.strip()
    if not raw_name:
        return PersonRef(raw_name=raw_name, status="new", confidence=0.0)

    ranked = await _load_candidates(session, raw_name, email)
    best = ranked[0] if ranked else None

    if best and best.score >= settings.person_match_link:
        await _touch_seen(session, best.person_id, seen_on)
        return PersonRef(
            raw_name=raw_name, person_id=best.person_id, confidence=best.score, status="linked"
        )

    if best and best.score >= settings.person_match_review:
        cands = [
            {"person_id": str(c.person_id), "name": c.canonical_name, "score": c.score, "via": c.via}
            for c in ranked[:5]
        ]
        review_id = await _queue_review(
            session,
            kind="person_ambiguous",
            payload={
                "raw_name": raw_name,
                "context": (context or "")[:500],
                "source_id": str(source_id) if source_id else None,
                "candidates": cands,
            },
        )
        return PersonRef(
            raw_name=raw_name,
            person_id=None,
            confidence=best.score,
            status="ambiguous",
            candidates=cands + [{"review_id": str(review_id)}],
        )

    # Below review threshold: create a new person (and surface it for review).
    if not auto_create:
        return PersonRef(raw_name=raw_name, status="new", confidence=best.score if best else 0.0)

    person = Person(
        canonical_name=raw_name,
        normalized_name=normalize_name(raw_name),
        email=email,
        first_seen=seen_on,
        last_seen=seen_on,
    )
    session.add(person)
    await session.flush()
    await _queue_review(
        session,
        kind="person_ambiguous",
        payload={
            "raw_name": raw_name,
            "created_person_id": str(person.id),
            "context": (context or "")[:500],
            "source_id": str(source_id) if source_id else None,
            "candidates": [],
            "note": "auto-created new person; confirm or merge",
        },
    )
    return PersonRef(raw_name=raw_name, person_id=person.id, confidence=1.0, status="new")


async def add_alias(
    session: AsyncSession, person_id: uuid.UUID, alias: str, *, kind: str = "variant"
) -> PersonAlias:
    """Add an alias, learning a spelling so resolution stops asking about it."""
    norm = normalize_name(alias)
    existing = (
        await session.execute(
            select(PersonAlias).where(
                PersonAlias.person_id == person_id, PersonAlias.normalized == norm
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if kind == "confirmed_typo":
            existing.kind = kind
        return existing
    row = PersonAlias(person_id=person_id, alias=alias, normalized=norm, kind=kind)
    session.add(row)
    await session.flush()
    return row


async def _touch_seen(session: AsyncSession, person_id: uuid.UUID, seen_on: date | None) -> None:
    if seen_on is None:
        return
    p = await session.get(Person, person_id)
    if p is None:
        return
    if p.first_seen is None or seen_on < p.first_seen:
        p.first_seen = seen_on
    if p.last_seen is None or seen_on > p.last_seen:
        p.last_seen = seen_on


async def _queue_review(session: AsyncSession, *, kind: str, payload: dict) -> uuid.UUID:
    row = ReviewQueue(kind=kind, payload=payload, status="pending")
    session.add(row)
    await session.flush()
    return row.id
