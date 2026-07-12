"""Extract grounded evaluation units (tasks/threats/good-news/decisions).

Every unit keeps a verbatim quote + locator + source (grounding). The LLM path
is preferred; the heuristic fallback still emits grounded units so the seed
import and offline runs produce real, traceable data (never ungrounded).
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.ingest.normalize import NormalizedInput
from majak.llm.client import get_llm
from majak.llm.prompts import EXTRACT_V1
from majak.models.schemas import ExtractedUnit, Grounding
from majak.models.tables import ExtractionHint

logger = logging.getLogger(__name__)

_VALID_SECTIONS = {"top", "decision", "good", "threat", "deleg", "quick", "radar"}
_VALID_RAILS = {"signal", "hi", "mid", "lo", "dec", "win"}


async def extract_units(
    session: AsyncSession,
    source_id: uuid.UUID,
    norm: NormalizedInput,
) -> list[ExtractedUnit]:
    llm = get_llm()
    text = norm.text.strip()
    if not text:
        return []

    if llm.available:
        try:
            hints = await _load_hints(session)
            prompt = EXTRACT_V1.format(
                content=text[:16000], source_id=str(source_id), hints=hints
            )
            data = await llm.complete_json(prompt, route="extract", max_tokens=4000)
            units = _coerce_units(data)
            if units:
                return units
            logger.info("LLM extraction returned no units; falling back to heuristics")
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM extract failed, using heuristics: %s", exc)

    return _heuristic_units(norm)


def _coerce_units(data: object) -> list[ExtractedUnit]:
    if isinstance(data, dict):
        data = data.get("units") or data.get("items") or []
    if not isinstance(data, list):
        return []
    units: list[ExtractedUnit] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        section = row.get("section", "radar")
        if section not in _VALID_SECTIONS:
            section = "radar"
        rail = row.get("rail", "signal")
        if rail not in _VALID_RAILS:
            rail = "signal"
        grounding = [
            Grounding(quote=g.get("quote", ""), locator=g.get("locator"), url=g.get("url"))
            for g in (row.get("grounding") or [])
            if isinstance(g, dict) and g.get("quote")
        ]
        if not grounding:
            # Grounding is mandatory — skip ungrounded units.
            continue
        units.append(
            ExtractedUnit(
                section=section,
                title=str(row.get("title", "")).strip()[:200] or "Bez názvu",
                description=(row.get("description") or None),
                rail=rail,
                owners=[str(o) for o in (row.get("owners") or [])],
                people=[str(p) for p in (row.get("people") or [])],
                chips=[c for c in (row.get("chips") or []) if isinstance(c, dict)],
                grounding=grounding,
                confidence=float(row.get("confidence", 1.0)),
            )
        )
    return units


# ── Heuristic fallback (grounded) ─────────────────────────────────────────────
# Cue phrases (Slovak + English) mapped to sections; each keeps the source line
# verbatim as the grounding quote.
_CUES: list[tuple[str, str, str]] = [
    # (regex, section, rail)
    (r"\b(rozhodli sme|rozhodnutie|decided|we will go with|schválené)\b", "decision", "dec"),
    (r"\b(riziko|hrozba|problém|blocker|risk|threat|mešká|delay)\b", "threat", "mid"),
    (r"\b(dobrá správa|super|výhra|podpísali|closed|won|success|získali)\b", "good", "win"),
    (r"\b(treba|musíme|todo|to-?do|action item|úloha|deadline|termín|pošli|priprav)\b", "top", "signal"),
    (r"\b(deleguj|prevezme|na teba|assign|owner)\b", "deleg", "signal"),
]


def _heuristic_units(norm: NormalizedInput) -> list[ExtractedUnit]:
    units: list[ExtractedUnit] = []
    lines = _candidate_lines(norm)
    for locator, speaker, line in lines:
        low = line.lower()
        for pattern, section, rail in _CUES:
            if re.search(pattern, low):
                owners = [speaker] if speaker and section == "deleg" else []
                units.append(
                    ExtractedUnit(
                        section=section,
                        title=_titleize(line),
                        description=None,
                        rail=rail,
                        owners=owners,
                        people=[speaker] if speaker else [],
                        grounding=[Grounding(quote=line.strip(), locator=locator)],
                        confidence=0.4,
                    )
                )
                break
    return _dedupe(units)


def _candidate_lines(norm: NormalizedInput) -> list[tuple[str | None, str | None, str]]:
    """Yield (locator, speaker, text) for each substantive line."""
    out: list[tuple[str | None, str | None, str]] = []
    if norm.segments:
        for seg in norm.segments:
            text = seg.get("text", "").strip()
            if len(text) >= 8:
                out.append((seg.get("ts"), seg.get("speaker"), text))
        return out
    for idx, line in enumerate(norm.text.split("\n"), start=1):
        line = line.strip()
        if len(line) >= 8:
            out.append((f"L{idx}", None, line))
    return out


def _titleize(line: str) -> str:
    line = re.sub(r"^\[?[\d:]+\]?\s*", "", line)  # drop leading timestamp
    line = re.sub(r"^[A-ZÀ-ž][\w .'-]{1,40}:\s*", "", line)  # drop leading speaker
    return line.strip()[:120]


def _dedupe(units: list[ExtractedUnit]) -> list[ExtractedUnit]:
    seen: set[str] = set()
    out: list[ExtractedUnit] = []
    for u in units:
        key = u.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


async def _load_hints(session: AsyncSession) -> str:
    rows = (await session.execute(select(ExtractionHint).limit(20))).scalars().all()
    if not rows:
        return ""
    lines = "\n".join(f"- ({r.scope}) {r.hint}" for r in rows)
    return f"\nLEARNED HINTS (apply these):\n{lines}\n"
