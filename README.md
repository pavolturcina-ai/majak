# MAJÁK

A personal CEO assistant for Pavol Turčina (GOSPACE LABS s.r.o.). MAJÁK ingests
the CEO's daily inputs, resolves the people involved, extracts a structured daily
evaluation, tracks each item's lifecycle across days, and learns from the CEO's
edits and deletes. Two scheduled runs keep the day fresh.

- **18:00 `close_and_open_tomorrow`** — closes today (snapshot + roll-up), opens
  tomorrow, carries unfinished items forward, pulls tomorrow's calendar
  (meetings + a dossier per attendee).
- **04:00 `fill_overnight`** — pulls everything that arrived overnight (Gmail,
  Slack, Fathom, late transcripts), re-generates the pulse/sections, and notifies
  the CEO — so at 04:00 the day is already complete.

Manual inputs (text / file / image) are an optional supplement that go through
the **exact same pipeline**.

---

## Architecture

```
Any input ─► ingest.pipeline.ingest() ──────────────────────────────► committed day
             1 normalize   any format → clean text (+ transcript segments)
             2 classify    kind, occurred_on, title, topic_tags
             3 people      resolve vs people+aliases (review on ambiguity)
             4 extract     grounded units (verbatim quote + locator + source)
             5 merge       carry-over linking against open items (no dupes)
             6 review      low-confidence → review_queue (non-blocking)
             7 commit      sources, files, people, items, grounding, events, embeddings
             8 assemble    rebuild pulse + sections for the affected day
```

Everything is **grounded** (each item traces to a source with a verbatim quote),
nothing is **hard-deleted** (soft delete + archive), people are **never silently
merged** (anything uncertain goes to the review queue), and syncs are
**idempotent** (`sources.unique(connector, external_id)` + `sync_state` cursors).

### Layout

```
src/majak/
  config.py            settings (env via pydantic-settings)
  db.py                async engine/session (SQLAlchemy 2 + asyncpg)
  models/              ORM tables (mirror the migrations) + Pydantic schemas
  util/                text (accent-strip/normalize/chunk), timezone helpers
  ingest/              normalize · classify · people · extract · merge · pipeline
  llm/                 Anthropic client (routing/retries) · prompts · embeddings seam
  connectors/          base + gmail/slack/fathom/gcal (delta-sync)
  day/                 assemble (pulse+sections) · lifecycle (carry chains) · dossier
  scheduler/           jobs (18:00 / 04:00) · notify (stub)
  api/                 FastAPI app · auth deps · routers
  seed/                run.py — ingest seed/raw/* through the real pipeline
supabase/migrations/   SQL schema (source of truth for DDL)
frontend/              api.js adapter + reference thin-client (Phase 1)
tests/
```

---

## Setup

Requires Python 3.12 and the [Supabase CLI](https://supabase.com/docs/guides/cli).

```bash
cp .env.example .env          # fill in ANTHROPIC_API_KEY, SUPABASE_*, connector creds
make install                  # pip install -e ".[dev,ocr]"
supabase start                # local Postgres 15 + pgvector + Storage + Auth
supabase db reset             # applies supabase/migrations/*
```

`DATABASE_URL` in `.env` should point at the local Supabase Postgres
(`postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres` by default).

### Offline / no-key mode

The pipeline degrades gracefully. Without `ANTHROPIC_API_KEY`, classify/extract
fall back to deterministic heuristics (still grounded), embeddings are skipped,
and connectors that lack credentials are no-ops. This keeps the seed import and
the test suite runnable in CI.

---

## Run

```bash
make run          # uvicorn majak.api.main:app --reload --port 8000
make seed         # python -m majak.seed.run  (ingest seed/raw/* → summary)
make check        # ruff + mypy + pytest
```

Open `http://localhost:8000/docs` for the API, or serve `frontend/index.html`
(set `window.MAJAK_API_BASE` if the API is not same-origin).

### Trigger the scheduled jobs manually

```bash
# The pg_cron / edge caller presents CRON_SECRET as a bearer token.
curl -XPOST localhost:8000/api/scheduler/close-and-open  -H "Authorization: Bearer dev-cron-secret"
curl -XPOST localhost:8000/api/scheduler/fill-overnight  -H "Authorization: Bearer dev-cron-secret"
```

In production these are driven by `pg_cron` (see `0007_scheduler_cron.sql`); set
the `majak.api_base` and `majak.cron_secret` Postgres settings for the DB to call
the API. When `pg_cron` is unavailable, a Supabase scheduled Edge Function can
hit the same routes.

---

## Seed import (checkpoint)

Drop the CEO's exports into `seed/raw/`:

- meeting transcript HTML exports (e.g. `2025-07-09-*.html`, `2025-07-10-*.html`),
- `references.json` — Slack/Gmail source links (`[{kind, url, title, text?, occurred_on?}]`),
- optional `*.txt / *.eml / *.docx / *.pdf / image` supplements.

Then:

```bash
make seed
```

It ingests every file **through the real pipeline** and prints a summary: sources
archived, days covered, grounded items, resolved people, and pending review
items. It flags any ungrounded item so the data can be trusted.

---

## Data model highlights

- **`entered_day`** = the day a row appeared on the board; the carry-chain ROOT
  holds the true first-appearance day. Walking `carry_from` recovers the whole
  chain (`entered 9.7. → carried → done 11.7. 14:32`).
- **Status changes** stamp `status_at` (timestamp) + `status_day` (the day the
  change happened) and always write an `item_events` row.
- **Views**: *selected day (backward)* = rows with `entered_day == D`;
  *all current* = every open **leaf** item across days.
- **Aliases** absorb typos/nicknames. Confirming an ambiguous person stores the
  raw spelling as a `confirmed_typo` alias, so resolution never asks again.

---

## Tests

```bash
pytest -q
```

Pure-logic tests (text normalization, name scoring, carry-over similarity,
transcript parsing, grounded heuristic extraction, API routing/auth) run
everywhere. DB integration tests (carry chains, status auditing) run when
`TEST_DATABASE_URL` points at a migrated pgvector database, and skip otherwise.

---

## Later (clean seams left in place)

Jira connector · auto-tuning of extraction from `extraction_hints` · full web UI ·
mobile push · voice input. Embeddings are behind a provider seam
(`llm/embeddings.py`) ready for Voyage AI or any 1024-dim model.
