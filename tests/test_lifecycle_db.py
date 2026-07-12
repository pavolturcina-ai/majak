"""Integration tests for the day lifecycle + pipeline against a live Postgres.

Skipped unless TEST_DATABASE_URL points at a pgvector-enabled database with the
migrations applied. These cover the carry-over chain and status auditing — the
requirements that are hard to verify with pure-logic tests alone.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.db

TEST_DB = os.getenv("TEST_DATABASE_URL")


_DATA_TABLES = (
    "item_events, item_people, item_sources, item_embeddings, items, "
    "source_chunks, source_participants, source_files, sources, "
    "person_aliases, review_queue, people, days, sync_state, extraction_hints"
)


@pytest.fixture
async def session():
    if not TEST_DB:
        pytest.skip("Set TEST_DATABASE_URL to run DB integration tests")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(TEST_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    # Isolate each test: start from a clean, dedicated test database.
    async with maker() as s:
        await s.execute(text(f"truncate {_DATA_TABLES} restart identity cascade"))
        await s.commit()
    async with maker() as s:
        yield s
        await s.rollback()
    await engine.dispose()


async def test_carry_chain_preserves_true_origin(session):
    from majak.day.lifecycle import (
        carry_root,
        carry_unfinished,
        ensure_day,
        set_status,
    )
    from majak.models.tables import Item

    d9 = date(2025, 7, 9)
    d10 = d9 + timedelta(days=1)
    d11 = d9 + timedelta(days=2)
    for d in (d9, d10, d11):
        await ensure_day(session, d, status="open")

    origin = Item(entered_day=d9, section="top", title="Poslať faktúru", status="open")
    session.add(origin)
    await session.flush()

    carried_10 = await carry_unfinished(session, d9, d10)
    assert len(carried_10) == 1

    # Re-running the same carry is idempotent.
    assert await carry_unfinished(session, d9, d10) == []

    carried_11 = await carry_unfinished(session, d10, d11)
    assert len(carried_11) == 1

    leaf = await session.get(Item, carried_11[0])
    assert leaf.entered_day == d11
    # Walking carry_from recovers the true first-appearance day.
    assert await carry_root(session, leaf) == d9

    # Closing the leaf records when + on which day.
    await set_status(session, leaf, "done", on_day=d11)
    assert leaf.status == "done"
    assert leaf.status_day == d11


async def test_delete_requires_reason(session):
    from majak.day.lifecycle import ensure_day, set_status
    from majak.models.tables import Item

    d = date(2025, 7, 9)
    await ensure_day(session, d, status="open")
    item = Item(entered_day=d, section="top", title="X", status="open")
    session.add(item)
    await session.flush()

    with pytest.raises(ValueError):
        await set_status(session, item, "deleted")

    await set_status(session, item, "deleted", reason="duplicitné")
    assert item.status == "deleted"
