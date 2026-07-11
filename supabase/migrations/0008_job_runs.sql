-- 0008 — job run history (observability for the scheduled runs)

create table job_runs (
  id           uuid primary key default gen_random_uuid(),
  job          text not null,                          -- 'fill-overnight' | 'close-and-open'
  on_day       date,
  status       text not null default 'running',        -- running | ok | failed | skipped
  stats        jsonb not null default '{}',            -- per-connector fetched/ingested/errors
  error        text,
  started_at   timestamptz not null default now(),
  finished_at  timestamptz
);
create index job_runs_started_idx on job_runs (started_at desc);
create index job_runs_job_idx on job_runs (job);
