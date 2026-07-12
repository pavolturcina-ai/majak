"""Dedup + carry-over linking.

A newly extracted unit is matched against currently-open items. A strong match
means "the same task/threat seen again" — we link the new item to the origin via
`carry_from` and preserve the origin's `entered_day`, rather than creating a
duplicate.

Matching blends lexical similarity (rapidfuzz, always available) with optional
embedding cosine similarity when vectors are present.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.models.schemas import ExtractedUnit
from majak.models.tables import Item
from majak.util.text import normalize_name

# Above this blended score, treat the unit as a carry-over of an existing item.
CARRY_THRESHOLD = 0.86


@dataclass
class MergeMatch:
    item: Item
    score: float


def lexical_similarity(a: str, b: str) -> float:
    a_n, b_n = normalize_name(a), normalize_name(b)
    if not a_n or not b_n:
        return 0.0
    return fuzz.token_set_ratio(a_n, b_n) / 100.0


def cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def blended_score(unit_title: str, item_title: str, emb_sim: float | None) -> float:
    lex = lexical_similarity(unit_title, item_title)
    if emb_sim is None:
        return lex
    return round(0.5 * lex + 0.5 * emb_sim, 4)


async def find_carry_over(
    session: AsyncSession,
    unit: ExtractedUnit,
    *,
    unit_embedding: list[float] | None = None,
    section_scope: bool = False,
) -> MergeMatch | None:
    """Return the best open item this unit continues, if any is strong enough."""
    stmt = select(Item).where(Item.status == "open")
    if section_scope:
        stmt = stmt.where(Item.section == unit.section)
    open_items = (await session.execute(stmt)).scalars().all()

    best: MergeMatch | None = None
    for item in open_items:
        emb_sim = None  # per-item embeddings are compared by the caller if desired
        score = blended_score(unit.title, item.title, emb_sim)
        if best is None or score > best.score:
            best = MergeMatch(item=item, score=score)

    if best and best.score >= CARRY_THRESHOLD:
        return best
    return None
