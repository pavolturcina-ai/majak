-- 0003 — sources (every input, archived forever) + participants + files

create type source_kind as enum (
  'transcript', 'text', 'email', 'slack', 'jira', 'fathom', 'calendar', 'attachment', 'image'
);

create table sources (
  id           uuid primary key default gen_random_uuid(),
  kind         source_kind not null,
  title        text,
  occurred_on  date,
  occurred_at  timestamptz,
  connector    text,                                   -- 'gmail' | 'slack' | 'fathom' | 'gcal' | 'manual' | 'seed'
  external_id  text,
  url          text,
  topic_tags   text[] not null default '{}',
  raw_text     text,                                   -- normalized clean text
  storage_path text,                                   -- original file in Supabase Storage
  meta         jsonb not null default '{}',
  created_at   timestamptz not null default now(),
  -- Idempotent sync: the same (connector, external_id) is ingested once.
  unique (connector, external_id)
);
create index sources_occurred_on_idx on sources (occurred_on);
create index sources_kind_idx on sources (kind);

create table source_participants (
  source_id   uuid not null references sources(id) on delete cascade,
  person_id   uuid not null references people(id),
  raw_name    text,
  confidence  real,
  primary key (source_id, person_id)
);

create table source_files (
  id           uuid primary key default gen_random_uuid(),
  source_id    uuid not null references sources(id) on delete cascade,
  storage_path text,
  mime         text,
  ocr_text     text
);
