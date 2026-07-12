-- 0002 — people + aliases (canonical entities and the typo-tolerance layer)

create table people (
  id              uuid primary key default gen_random_uuid(),
  canonical_name  text not null,
  normalized_name text not null,                       -- lowercased, accent-stripped
  role            text,
  org             text,
  email           text,
  linkedin        text,
  notes           text,
  tags            text[] not null default '{}',
  first_seen      date,
  last_seen       date,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index people_normalized_trgm on people using gin (normalized_name gin_trgm_ops);
create index people_email_idx on people (lower(email)) where email is not null;
create trigger people_set_updated_at
  before update on people
  for each row execute function set_updated_at();

-- Aliases — this is how typos and nicknames stop breaking resolution.
create table person_aliases (
  id          uuid primary key default gen_random_uuid(),
  person_id   uuid not null references people(id) on delete cascade,
  alias       text not null,
  normalized  text not null,
  kind        text not null default 'variant'          -- 'confirmed_typo' | 'variant' | 'nickname'
              check (kind in ('confirmed_typo', 'variant', 'nickname')),
  created_at  timestamptz not null default now(),
  unique (person_id, normalized)
);
create index person_aliases_normalized_trgm on person_aliases using gin (normalized gin_trgm_ops);
