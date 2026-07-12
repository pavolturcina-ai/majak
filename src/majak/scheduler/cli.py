"""CLI entrypoint for the scheduled jobs — invoked by Render Cron Jobs.

  python -m majak.scheduler.cli close-and-open   # 18:00 Europe/Bratislava
  python -m majak.scheduler.cli fill-overnight   # 04:00 Europe/Bratislava

Runs the job directly against DATABASE_URL (no HTTP), so it does not depend on
the API being up. Prints the result as JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from majak.db import dispose_engine, session_scope
from majak.scheduler.jobs import close_and_open_tomorrow, fill_overnight

logger = logging.getLogger(__name__)


async def _run(job: str) -> dict:
    async with session_scope() as session:
        if job == "close-and-open":
            result = await close_and_open_tomorrow(session)
        else:
            result = await fill_overnight(session)
    await dispose_engine()
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    ap = argparse.ArgumentParser(description="Run a MAJÁK scheduled job.")
    ap.add_argument("job", choices=["close-and-open", "fill-overnight"])
    args = ap.parse_args()
    result = asyncio.run(_run(args.job))
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
