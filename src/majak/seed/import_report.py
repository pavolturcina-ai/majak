"""Import an evaluation report's finished items verbatim into the database.

This does NOT re-extract anything. It takes the report's own `const SEED`
(the curated day evaluation — 76 items with their sections, rails, owners,
chips and grounding) plus `const SOURCES` and loads them 1:1 into the schema, so
the finished evaluation lives in the database and is never lost.

Titles, descriptions, quotes and locators are copied exactly as authored.

Usage:
    python -m majak.seed.import_report path/to/report.html [--year 2026]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import uuid
from datetime import date

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from majak.day.lifecycle import ensure_day, record_event
from majak.db import session_scope
from majak.models.tables import (
    Item,
    ItemPerson,
    ItemSource,
    Person,
    Source,
)
from majak.util.text import normalize_name

logger = logging.getLogger(__name__)

# SEED section ids -> item_section enum values.
SECTION_MAP = {
    "top": "top",
    "dec": "decision",
    "good": "good",
    "threat": "threat",
    "deleg": "deleg",
    "quick": "quick",
    "radar": "radar",
}
_DM_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.?")


def _const(html: str, name: str) -> object:
    """Extract a `const NAME = <json>;` value via brace/bracket matching."""
    idx = html.find(f"const {name}")
    if idx == -1:
        raise ValueError(f"const {name} not found")
    eq = html.find("=", idx)
    start = next(i for i in range(eq, len(html)) if html[i] in "[{")
    open_ch = html[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return json.loads(html[start : i + 1])
    raise ValueError(f"Unbalanced literal for const {name}")


def parse_report(html: str) -> tuple[dict, dict]:
    return _const(html, "SEED"), _const(html, "SOURCES")


def _to_date(day: str, year: int) -> date | None:
    m = _DM_RE.search(day or "")
    if not m:
        return None
    return date(year, int(m.group(2)), int(m.group(1)))


def _kind_for(label: str) -> str:
    low = label.lower()
    if "porad" in low or "meeting" in low or "call" in low or "transcript" in low:
        return "transcript"
    if "slack" in low:
        return "slack"
    if "mail" in low or "gmail" in low or "@" in low:
        return "email"
    if "jira" in low:
        return "jira"
    return "text"


class _SourceRegistry:
    """Archives report SOURCES and resolves ctx grounding labels to source ids."""

    def __init__(self, session: AsyncSession, year: int) -> None:
        self.s = session
        self.year = year
        self.by_label: dict[str, uuid.UUID] = {}
        self.titles: list[tuple[str, uuid.UUID]] = []  # (title, id) for fuzzy match
        self._seq = 0

    async def archive(self, sources: dict) -> None:
        for m in sources.get("meetings", []):
            sid = await self._add(
                kind="transcript",
                title=m.get("title", ""),
                day=m.get("day", ""),
                raw_text=m.get("transcript"),
                connector="seed-report",
            )
            self.titles.append((m.get("title", ""), sid))
        for grp, kind in (("slack", "slack"), ("gmail", "email"), ("jira", "jira")):
            for r in sources.get(grp, []):
                sid = await self._add(
                    kind=kind,
                    title=r.get("label", ""),
                    day=r.get("day", ""),
                    url=r.get("url") or None,
                    connector=f"seed-{grp}",
                )
                self.titles.append((r.get("label", ""), sid))

    async def _add(
        self,
        *,
        kind: str,
        title: str,
        day: str,
        raw_text: str | None = None,
        url: str | None = None,
        connector: str,
    ) -> uuid.UUID:
        self._seq += 1
        src = Source(
            kind=kind,
            title=title[:200] if title else None,
            occurred_on=_to_date(day, self.year),
            connector=connector,
            external_id=f"{connector}:{self._seq}:{title[:60]}",
            url=url,
            raw_text=raw_text,
            topic_tags=[],
        )
        self.s.add(src)
        await self.s.flush()
        if title:
            self.by_label.setdefault(title, src.id)
        return src.id

    async def resolve(self, label: str) -> uuid.UUID:
        """Return the best source id for a grounding label (fuzzy), else create one."""
        if not label:
            label = "Podklad"
        if label in self.by_label:
            return self.by_label[label]
        best_id, best_score = None, 0.0
        for title, sid in self.titles:
            score = fuzz.token_set_ratio(label.lower(), title.lower()) / 100.0
            if score > best_score:
                best_id, best_score = sid, score
        if best_id is not None and best_score >= 0.55:
            self.by_label[label] = best_id
            return best_id
        # No confident match — create a labelled source so grounding still resolves.
        sid = await self._add(
            kind=_kind_for(label), title=label, day="", connector="seed-ctx"
        )
        return sid


class _PeopleRegistry:
    """Get-or-create people by normalized name (curated import — no review noise)."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session
        self.cache: dict[str, uuid.UUID] = {}
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        for p in (await self.s.execute(select(Person))).scalars().all():
            self.cache[p.normalized_name] = p.id
        self._loaded = True

    async def get_or_create(self, raw_name: str, seen_on: date | None) -> uuid.UUID | None:
        await self._ensure_loaded()
        name = raw_name.strip()
        if not name or name.lower() in {"?", "n/a", "tím", "team"}:
            return None
        norm = normalize_name(name)
        if norm in self.cache:
            return self.cache[norm]
        # Fuzzy against known people (absorbs 'Pavol' vs an existing 'Pavol T.').
        best_norm, best_score = None, 0.0
        for known in self.cache:
            score = fuzz.token_sort_ratio(norm, known) / 100.0
            if score > best_score:
                best_norm, best_score = known, score
        if best_norm is not None and best_score >= 0.94:
            self.cache[norm] = self.cache[best_norm]
            return self.cache[best_norm]
        person = Person(
            canonical_name=name,
            normalized_name=norm,
            first_seen=seen_on,
            last_seen=seen_on,
        )
        self.s.add(person)
        await self.s.flush()
        self.cache[norm] = person.id
        return person.id


def _split_people(*fields: object) -> list[str]:
    """Flatten owner/who fields into distinct names ('Pavol / Janči' -> two)."""
    names: list[str] = []
    for f in fields:
        if isinstance(f, list):
            for x in f:
                names.extend(_split_people(x))
        elif isinstance(f, str):
            for part in re.split(r"[/,;&]| a ", f):
                part = part.strip()
                if part:
                    names.append(part)
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


async def import_report(session: AsyncSession, seed: dict, sources: dict, year: int) -> dict:
    registry = _SourceRegistry(session, year)
    await registry.archive(sources)
    people = _PeopleRegistry(session)

    # Days present among the items; the report's headline day carries the pulse.
    section_items = [
        (SECTION_MAP.get(sec.get("id"), "radar"), it)
        for sec in seed.get("sections", [])
        for it in sec.get("items", [])
    ]
    days_seen: set[date] = set()
    for _, it in section_items:
        d = _to_date(it.get("day", ""), year)
        if d:
            days_seen.add(d)
    for d in sorted(days_seen):
        await ensure_day(session, d, status="open")

    headline = max(days_seen) if days_seen else _to_date("", year)
    if headline:
        day_row = await ensure_day(session, headline, status="open")
        day_row.pulse = seed.get("pulse")
        day_row.summary = seed.get("human")

    created = 0
    grounded = 0
    for section, it in section_items:
        entered = _to_date(it.get("day", ""), year) or headline
        item = Item(
            entered_day=entered,
            section=section,
            title=(it.get("t") or "Bez názvu")[:400],
            description=it.get("d"),
            rail=it.get("rail", "signal"),
            owners=_split_people(it.get("own", [])),
            chips=it.get("chips", []),
            status="open",
        )
        session.add(item)
        await session.flush()
        created += 1

        used_keys: set[tuple[uuid.UUID, str]] = set()
        for n, ctx in enumerate(it.get("ctx", []) or []):
            src_id = await registry.resolve(ctx.get("src", ""))
            locator = ctx.get("loc", "") or ""
            # The grounding PK is (item, source, locator). Two quotes from the same
            # source with the same/empty locator would collide — disambiguate.
            if (src_id, locator) in used_keys:
                locator = f"{locator}#{n}" if locator else f"#{n}"
            used_keys.add((src_id, locator))
            session.add(
                ItemSource(
                    item_id=item.id,
                    source_id=src_id,
                    locator=locator,
                    quote=ctx.get("q"),
                    url=ctx.get("url"),
                )
            )
            grounded += 1

        # Link people from the curated owner names only. The ctx `who` field is
        # free-form display text ("Pavol / Janči") and stays in the grounding.
        for name in _split_people(it.get("own", [])):
            pid = await people.get_or_create(name, entered)
            if pid is None:
                continue
            if await session.get(ItemPerson, {"item_id": item.id, "person_id": pid}) is None:
                session.add(ItemPerson(item_id=item.id, person_id=pid))

        await record_event(
            session, item.id, "create",
            after={"section": section, "title": item.title, "imported": True},
            on_day=entered,
        )

    return {"items": created, "grounded_links": grounded, "days": sorted(str(d) for d in days_seen)}


async def run(report_path: str, year: int) -> None:
    from pathlib import Path

    html = Path(report_path).read_text(encoding="utf-8", errors="replace")
    seed, sources = parse_report(html)
    async with session_scope() as session:
        result = await import_report(session, seed, sources, year)
    async with session_scope() as session:
        n_items = (await session.execute(select(func.count()).select_from(Item))).scalar_one()
        n_grounded = (
            await session.execute(select(func.count(func.distinct(ItemSource.item_id))))
        ).scalar_one()
        n_people = (await session.execute(select(func.count()).select_from(Person))).scalar_one()
        n_sources = (await session.execute(select(func.count()).select_from(Source))).scalar_one()
    print("\n" + "=" * 56)
    print("  MAJÁK — verbatim report import")
    print("=" * 56)
    print(f"  Items imported   : {result['items']}")
    print(f"  Grounded (rows)  : {n_grounded}/{n_items} items · {result['grounded_links']} quotes")
    print(f"  Sources archived : {n_sources}")
    print(f"  People           : {n_people}")
    print(f"  Days             : {', '.join(result['days'])}")
    print("=" * 56 + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ap = argparse.ArgumentParser(description="Import a report's SEED items verbatim into the DB.")
    ap.add_argument("report", help="path to the evaluation report .html")
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()
    asyncio.run(run(args.report, args.year))


if __name__ == "__main__":
    main()
