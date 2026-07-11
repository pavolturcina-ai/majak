"""Apply SQL migrations to the database pointed at by DATABASE_URL.

Idempotent: tracks applied files in a `_migrations` table and skips them on
re-run, so it is safe as a Render preDeployCommand. The pg_cron migration
(0007_scheduler_cron.sql) is skipped by default — on a managed deploy the
schedule is driven by Render Cron Jobs, not pg_cron. Pass --include-cron to
apply it anyway (self-hosted Postgres with pg_cron).

Usage:  python -m majak.migrate [--include-cron] [--dir supabase/migrations]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from majak.config import settings

logger = logging.getLogger(__name__)


def _dsn() -> str:
    # asyncpg wants a plain postgresql:// DSN (no SQLAlchemy +asyncpg suffix).
    return settings.database_url.replace("+asyncpg", "")


async def run(mig_dir: Path, include_cron: bool) -> None:
    import asyncpg

    conn = await asyncpg.connect(_dsn())
    try:
        await conn.execute(
            "create table if not exists _migrations "
            "(name text primary key, applied_at timestamptz default now())"
        )
        applied = {r["name"] for r in await conn.fetch("select name from _migrations")}
        files = sorted(mig_dir.glob("*.sql"))
        for f in files:
            if "scheduler_cron" in f.name and not include_cron:
                logger.info("skip %s (pg_cron; using Render Cron instead)", f.name)
                continue
            if f.name in applied:
                logger.info("skip %s (already applied)", f.name)
                continue
            logger.info("apply %s", f.name)
            sql = f.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("insert into _migrations(name) values($1)", f.name)
        logger.info("migrations up to date")
    finally:
        await conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ap = argparse.ArgumentParser(description="Apply SQL migrations to DATABASE_URL.")
    ap.add_argument("--dir", default=os.environ.get("MIGRATIONS_DIR", "supabase/migrations"))
    ap.add_argument("--include-cron", action="store_true", help="also apply pg_cron migration")
    args = ap.parse_args()
    asyncio.run(run(Path(args.dir), args.include_cron))


if __name__ == "__main__":
    main()
