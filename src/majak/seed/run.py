"""Seed import — ingest seed/raw/* through the REAL pipeline (no shortcuts).

Reads:
  - meeting transcript HTML exports (*.html / *.htm)
  - references.json  (Slack/Gmail source links already collected)
  - any *.txt / *.eml / *.docx / *.pdf / image supplements dropped in seed/raw/

Each file is wrapped in a RawInput and passed to ingest(), so the DB ends up
with resolved people (+ ambiguous ones in the review queue), archived sources
with transcripts, grounded items for the covered days, embeddings, and days rows.

Run:  python -m majak.seed.run   [--dir seed/raw]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import mimetypes
import re
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from majak.db import session_scope
from majak.ingest.pipeline import ingest
from majak.models.schemas import IngestResult, RawInput
from majak.models.tables import Day, Item, ItemSource, Person, ReviewQueue, Source

logger = logging.getLogger(__name__)

_TRANSCRIPT_EXT = {".html", ".htm"}
_TEXT_EXT = {".txt", ".md"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_FILE_EXT = {".docx", ".pdf", ".eml"}


def _guess_date(name: str) -> date | None:
    """Recover a date like '9.7', '10.7', '2025-07-09' from a filename."""
    import re

    m = re.search(r"(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})", name)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[._](\d{1,2})\b", name)
    if m:
        # Day.month, assume current year — the CEO's exports use e.g. '9.7'.
        try:
            return date(date.today().year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


_TS_LINE = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*$", re.MULTILINE)


def _looks_like_transcript(text: str) -> bool:
    return len(_TS_LINE.findall(text)) >= 5


def _raw_for(path: Path) -> RawInput | None:
    ext = path.suffix.lower()
    occurred_on = _guess_date(path.name)
    external_id = f"seed:{path.name}"

    if ext in _TRANSCRIPT_EXT:
        return RawInput(
            kind="transcript",
            connector="seed",
            external_id=external_id,
            title=path.stem,
            occurred_on=occurred_on,
            html=path.read_text(encoding="utf-8", errors="replace"),
        )
    if ext in _TEXT_EXT:
        body = path.read_text(encoding="utf-8", errors="replace")
        # A .txt with many timestamp lines is a transcript, not a note.
        kind = "transcript" if _looks_like_transcript(body) else "text"
        return RawInput(
            kind=kind,
            connector="seed",
            external_id=external_id,
            title=path.stem,
            occurred_on=occurred_on,
            text=body,
        )
    if ext in _IMAGE_EXT:
        return RawInput(
            kind="image",
            connector="seed",
            external_id=external_id,
            title=path.stem,
            occurred_on=occurred_on,
            image_bytes=path.read_bytes(),
            mime=mimetypes.guess_type(path.name)[0],
        )
    if ext in _FILE_EXT:
        return RawInput(
            kind="attachment",
            connector="seed",
            external_id=external_id,
            title=path.stem,
            occurred_on=occurred_on,
            file_bytes=path.read_bytes(),
            file_name=path.name,
            mime=mimetypes.guess_type(path.name)[0],
        )
    return None


def _raws_from_references(path: Path) -> list[RawInput]:
    """references.json: list of {kind, url, title, text?, occurred_on?, external_id?}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("references", [])
    raws: list[RawInput] = []
    for i, e in enumerate(entries):
        occurred = e.get("occurred_on")
        raws.append(
            RawInput(
                kind=e.get("kind", "text"),
                connector=e.get("connector", "seed-ref"),
                external_id=e.get("external_id") or f"seed-ref:{i}",
                title=e.get("title"),
                url=e.get("url"),
                occurred_on=date.fromisoformat(occurred) if occurred else None,
                text=e.get("text") or e.get("snippet") or e.get("title") or "",
                meta={k: v for k, v in e.items() if k not in {"text", "snippet"}},
            )
        )
    return raws


async def run(seed_dir: Path) -> None:
    if not seed_dir.exists():
        logger.error("Seed dir %s does not exist. Drop the exports there first.", seed_dir)
        return

    paths = sorted(p for p in seed_dir.iterdir() if p.is_file() and p.name != ".gitkeep")
    if not paths:
        logger.warning(
            "No files in %s. Drop the transcript HTML exports + references.json there.", seed_dir
        )
        return

    raws: list[RawInput] = []
    for p in paths:
        if p.name == "references.json":
            raws.extend(_raws_from_references(p))
            continue
        raw = _raw_for(p)
        if raw is not None:
            raws.append(raw)
        else:
            logger.info("Skipping unsupported file: %s", p.name)

    results: list[IngestResult] = []
    async with session_scope() as session:
        for raw in raws:
            logger.info("Ingesting %s (%s)…", raw.title or raw.external_id, raw.kind)
            res = await ingest(session, raw)
            results.append(res)

    await _summary(results)


async def _summary(results: list[IngestResult]) -> None:
    async with session_scope() as session:
        n_days = (await session.execute(select(func.count()).select_from(Day))).scalar_one()
        n_sources = (await session.execute(select(func.count()).select_from(Source))).scalar_one()
        n_items = (
            await session.execute(
                select(func.count()).select_from(Item).where(Item.status != "deleted")
            )
        ).scalar_one()
        n_grounded = (
            await session.execute(select(func.count(func.distinct(ItemSource.item_id))))
        ).scalar_one()
        n_people = (await session.execute(select(func.count()).select_from(Person))).scalar_one()
        n_review = (
            await session.execute(
                select(func.count()).select_from(ReviewQueue).where(ReviewQueue.status == "pending")
            )
        ).scalar_one()
        days = (await session.execute(select(Day).order_by(Day.date))).scalars().all()

    print("\n" + "=" * 60)
    print("  MAJÁK — seed import summary")
    print("=" * 60)
    print(f"  Sources archived : {n_sources}")
    print(f"  Days             : {n_days}  ({', '.join(d.date.isoformat() for d in days)})")
    print(f"  Items (active)   : {n_items}  (grounded: {n_grounded})")
    print(f"  People resolved  : {n_people}")
    print(f"  Review queue     : {n_review} pending")
    created = sum(len(r.created_item_ids) for r in results)
    carried = sum(len(r.carried_item_ids) for r in results)
    dupes = sum(1 for r in results if r.skipped_duplicate)
    print(f"  This run         : {created} created, {carried} carried/merged, {dupes} duplicates")
    for d in days:
        print(f"    · {d.date} [{d.status}] {d.pulse or ''}")
    print("=" * 60 + "\n")

    if n_items > 0 and n_grounded < n_items:
        print("  ⚠ Some items are ungrounded — investigate before trusting the data.\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ingest seed/raw/* through the pipeline.")
    parser.add_argument("--dir", default="seed/raw", help="directory of seed inputs")
    args = parser.parse_args()
    asyncio.run(run(Path(args.dir)))


if __name__ == "__main__":
    main()
