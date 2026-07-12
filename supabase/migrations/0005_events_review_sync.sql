-- 0005 — audit/learning events + confirmation queue + sync cursors

-- Every manual change is recorded (audit + learning signal).
create type event_type as enum ('create', 'edit', 'delete', 'done', 'reopen', 'move', 'tag', 'carry');

create table item_events (
  id       uuid primary key default gen_random_uuid(),
  item_id  uuid not null references items(id) on delete cascade,
  type     event_type not null,
  before   jsonb,
  after    jsonb,
  reason   text,                                       -- required for delete (enforced in app layer)
  actor    text not null default 'pavol',
  at       timestamptz not null default now(),
  on_day   date
);
create index item_events_item_idx on item_events (item_id);
create index item_events_type_idx on item_events (type);

-- Confirmation queue (ask-on-suspicion, non-blocking).
create type review_kind as enum ('person_ambiguous', 'low_confidence_extract', 'other');

create table review_queue (
  id          uuid primary key default gen_random_uuid(),
  kind        review_kind not null,
  payload     jsonb not null,                          -- candidates, context, source_id
  status      text not null default 'pending'          -- pending | resolved | dismissed
              check (status in ('pending', 'resolved', 'dismissed')),
  created_at  timestamptz not null default now(),
  resolved_at timestamptz
);
create index review_queue_status_idx on review_queue (status);

-- Delta-sync cursors per connector.
create table sync_state (
  connector    text primary key,
  cursor       text,
  last_run_at  timestamptz,
  meta         jsonb not null default '{}'
);
