"""Classify a normalized input: kind, occurred_on, title, topic_tags.

Uses the LLM when available, with a deterministic heuristic fallback so the
pipeline (and seed import) runs offline.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from dateutil import parser as dateparser

from majak.ingest.normalize import NormalizedInput
from majak.llm.client import get_llm
from majak.llm.prompts import CLASSIFY_V1
from majak.models.schemas import Classification, RawInput

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}\.\s?\d{1,2}\.\s?\d{2,4}|\d{1,2}/\d{1,2}/\d{2,4})\b"
)


async def classify(raw: RawInput, norm: NormalizedInput) -> Classification:
    llm = get_llm()
    if llm.available and norm.text.strip():
        try:
            data = await llm.complete_json(
                CLASSIFY_V1.format(content=norm.text[:6000]), route="extract", max_tokens=400
            )
            return Classification(
                kind=data.get("kind", raw.kind),
                occurred_on=_parse_date(data.get("occurred_on")) or _fallback_date(raw, norm),
                title=(data.get("title") or norm.title or "Bez názvu")[:120],
                topic_tags=[str(t)[:40] for t in (data.get("topic_tags") or [])][:5],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM classify failed, using heuristics: %s", exc)

    return _heuristic(raw, norm)


def _heuristic(raw: RawInput, norm: NormalizedInput) -> Classification:
    return Classification(
        kind=raw.kind,
        occurred_on=_fallback_date(raw, norm),
        title=(norm.title or _first_line(norm.text) or "Bez názvu")[:120],
        topic_tags=_keyword_tags(norm.text),
    )


def _first_line(text: str) -> str | None:
    for line in text.split("\n"):
        line = line.strip()
        if line:
            return line[:80]
    return None


def _fallback_date(raw: RawInput, norm: NormalizedInput) -> date | None:
    if raw.occurred_on:
        return raw.occurred_on
    if raw.occurred_at:
        return raw.occurred_at.date()
    # Try to sniff a date from the first part of the text.
    m = _DATE_RE.search(norm.text[:2000])
    if m:
        return _parse_date(m.group(1))
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # dayfirst=True: European format dominates the CEO's inputs.
        return dateparser.parse(value, dayfirst=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


# A small Slovak/English keyword→tag map for the offline fallback.
_KEYWORDS = {
    "faktúr": "financie",
    "invoice": "financie",
    "zmluv": "zmluvy",
    "contract": "zmluvy",
    "invest": "investori",
    "hiring": "nabor",
    "nábor": "nabor",
    "produkt": "produkt",
    "product": "produkt",
    "klient": "klienti",
    "client": "klienti",
    "customer": "klienti",
    "deadline": "termin",
    "termín": "termin",
    "marketing": "marketing",
    "sales": "obchod",
    "obchod": "obchod",
}


def _keyword_tags(text: str) -> list[str]:
    low = text.lower()
    tags: list[str] = []
    for needle, tag in _KEYWORDS.items():
        if needle in low and tag not in tags:
            tags.append(tag)
        if len(tags) >= 5:
            break
    return tags
