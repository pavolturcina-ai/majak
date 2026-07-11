"""The two scheduled runs, driven by pg_cron (or the API scheduler routes).

- 18:00 close_and_open_tomorrow: finalize today (snapshot + roll-up, close),
  open tomorrow, carry unfinished items forward, pull tomorrow's calendar →
  radar entries + attendee dossiers.
- 04:00 fill_overnight: for each connector fetch_since(cursor) → run pipeline →
  re-assemble the open day → notify that the brief is ready.

Both are idempotent (sources.unique(connector, external_id) + sync_state cursors).
"""

from __future__ import annotations

import contextlib
import logging
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from majak.connectors.base import load_default_connectors
from majak.day.assemble import assemble_day, get_day_view
from majak.day.lifecycle import carry_unfinished, close_day, ensure_day, next_day, open_day
from majak.ingest.pipeline import ingest
from majak.models.schemas import RawInput
from majak.models.tables import Item, ItemSource, Source, SyncState
from majak.scheduler.notify import notify
from majak.util.time import today_local

logger = logging.getLogger(__name__)

# Session-level advisory-lock keys — single-flight so concurrent runs don't
# contend on the same rows (what tripped the statement timeout).
_LOCK_CLOSE = 811_018
_LOCK_FILL = 811_004


async def _try_lock(session: AsyncSession, key: int) -> bool:
    return bool((await session.execute(text("select pg_try_advisory_lock(:k)"), {"k": key})).scalar())


async def _unlock(session: AsyncSession, key: int) -> None:
    # Tolerate a failed in-flight transaction: roll back, then release the lock.
    with contextlib.suppress(Exception):
        await session.rollback()
    try:
        await session.execute(text("select pg_advisory_unlock(:k)"), {"k": key})
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("advisory unlock %s failed: %s", key, exc)


async def close_and_open_tomorrow(session: AsyncSession, *, on: date | None = None) -> dict:
    """18:00 — close today, open tomorrow, carry forward, pull calendar."""
    today = on or today_local()
    tomorrow = next_day(today)

    if not await _try_lock(session, _LOCK_CLOSE):
        logger.warning("close_and_open: another run in progress; skipping")
        return {"skipped": "another run in progress", "day": today.isoformat()}
    try:
        await assemble_day(session, today)
        rollup = await _rollup_for_day(session, today)
        day_row = await close_day(session, today)
        day_row.summary = (day_row.summary or "") + _rollup_line(rollup)
        await session.commit()

        await open_day(session, tomorrow)
        carried = await carry_unfinished(session, today, tomorrow)
        await session.commit()

        calendar_sources = await _pull_calendar(session, tomorrow)
        await assemble_day(session, tomorrow)
        await session.commit()

        result = {
            "closed_day": today.isoformat(),
            "opened_day": tomorrow.isoformat(),
            "carried_items": len(carried),
            "calendar_sources": calendar_sources,
            "rollup": rollup,
        }
        logger.info("close_and_open_tomorrow: %s", result)
        return result
    finally:
        await _unlock(session, _LOCK_CLOSE)


async def fill_overnight(session: AsyncSession, *, on: date | None = None) -> dict:
    """04:00 — fetch overnight inputs from every connector, fill the open day.

    Commits per item so locks are held briefly, progress persists across a
    crash, and long LLM processing never sits inside one giant transaction.
    """
    today = on or today_local()

    if not await _try_lock(session, _LOCK_FILL):
        logger.warning("fill_overnight: another run in progress; skipping")
        return {"skipped": "another run in progress", "day": today.isoformat()}
    try:
        await open_day(session, today)
        await session.commit()  # release the day row immediately

        connectors = load_default_connectors()
        stats: dict[str, dict] = {}

        for name, conn in connectors.items():
            state = await _get_sync_state(session, name)
            cursor = state.cursor
            try:
                items, new_cursor = await conn.fetch_since(cursor)
            except NotImplementedError:
                stats[name] = {"skipped": "not wired"}
                continue
            except Exception as exc:  # noqa: BLE001 — one connector must not fail the run
                logger.error("connector %s fetch failed: %s", name, exc)
                await session.rollback()
                stats[name] = {"error": str(exc)}
                continue

            ingested = errors = 0
            for raw in items:
                try:
                    res = await ingest(session, raw)
                    await session.commit()  # per-item: brief locks, durable progress
                    if not res.skipped_duplicate:
                        ingested += 1
                except Exception as exc:  # noqa: BLE001 — one item must not fail the batch
                    await session.rollback()
                    errors += 1
                    logger.warning("ingest failed (%s): %s", name, exc)

            state = await _get_sync_state(session, name)
            state.cursor = new_cursor
            state.last_run_at = today_local_dt()
            await session.commit()
            stats[name] = {"fetched": len(items), "ingested": ingested, "errors": errors}

        await assemble_day(session, today)
        await session.commit()
        view = await get_day_view(session, today)

        await notify(
            subject=f"MAJÁK — brief pripravený ({today.isoformat()})",
            body=(view.pulse if view else "Deň je pripravený."),
        )
    finally:
        await _unlock(session, _LOCK_FILL)

    result = {"day": today.isoformat(), "connectors": stats}
    logger.info("fill_overnight: %s", result)
    return result


# ── helpers ───────────────────────────────────────────────────────────────────
async def _get_sync_state(session: AsyncSession, connector: str) -> SyncState:
    state = await session.get(SyncState, connector)
    if state is None:
        state = SyncState(connector=connector, cursor=None)
        session.add(state)
        await session.flush()
    return state


async def _pull_calendar(session: AsyncSession, target: date) -> int:
    """Pull `target`'s meetings into the pipeline (radar + dossiers)."""
    connectors = load_default_connectors()
    gcal = connectors.get("gcal")
    if gcal is None or not getattr(gcal, "configured", False):
        return 0
    try:
        raw_events: list[RawInput] = await gcal.fetch_day(target)  # type: ignore[attr-defined]
    except NotImplementedError:
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("calendar pull failed: %s", exc)
        return 0

    count = 0
    for raw in raw_events:
        res = await ingest(session, raw)
        if not res.skipped_duplicate:
            count += 1
    return count


async def _rollup_for_day(session: AsyncSession, day: date) -> dict:
    """Closed-item log for a day: what got done/deleted."""
    done = (
        await session.execute(
            select(Item).where(Item.status == "done", Item.status_day == day)
        )
    ).scalars().all()
    deleted = (
        await session.execute(
            select(Item).where(Item.status == "deleted", Item.status_day == day)
        )
    ).scalars().all()
    return {"done": len(done), "deleted": len(deleted)}


def _rollup_line(rollup: dict) -> str:
    return f"\n[roll-up] hotové: {rollup['done']}, zmazané: {rollup['deleted']}"


def today_local_dt():
    from majak.util.time import now_local

    return now_local()


# Silence unused-import warnings for symbols kept for callers/readability.
_ = (ensure_day, Source, ItemSource)
