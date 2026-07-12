-- 0004 — days + items + grounding + people links

create type day_status as enum ('draft', 'open', 'closed');

create table days (
  date       date primary key,
  status     day_status not null default 'draft',
  pulse      text,
  summary    text,
  opened_at  timestamptz,
  closed_at  timestamptz
);

create type item_section as enum ('top', 'decision', 'good', 'threat', 'deleg', 'quick', 'radar');
create type item_status  as enum ('open', 'done', 'deleted');
create type list_kind    as enum ('uloha', 'napad', 'poznamka');

create table items (
  id           uuid primary key default gen_random_uuid(),
  entered_day  date references days(date),             -- the day it FIRST appeared
  section      item_section not null,
  title        text not null,
  description  text,
  rail         text not null default 'signal',         -- severity: signal/hi/mid/lo/dec/win
  owners       text[] not null default '{}',
  chips        jsonb not null default '[]',
  list_kind    list_kind,                              -- optional: saved-to-list tag
  carry_from   uuid references items(id),              -- link to origin item across days
  status       item_status not null default 'open',
  status_at    timestamptz,                            -- WHEN the status last changed
  status_day   date,                                   -- on which day the status changed
  order_index  int not null default 0,
  created_at   timestamptz not null default now()
);
create index items_entered_day_idx on items (entered_day);
create index items_status_idx on items (status);
create index items_section_idx on items (section);
create index items_carry_from_idx on items (carry_from);

-- Grounding: every item traces to its source(s) with an exact quote.
-- locator defaults to '' (never null) so it can be part of a plain composite PK
-- — the same (item, source) can be grounded at multiple locators (e.g. two
-- transcript timestamps) without collision.
create table item_sources (
  item_id    uuid not null references items(id) on delete cascade,
  source_id  uuid not null references sources(id),
  quote      text,
  locator    text not null default '',                 -- transcript timestamp / message link
  url        text,
  primary key (item_id, source_id, locator)
);

create table item_people (
  item_id    uuid not null references items(id) on delete cascade,
  person_id  uuid not null references people(id),
  primary key (item_id, person_id)
);
