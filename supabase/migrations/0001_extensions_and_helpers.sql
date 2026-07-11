-- 0001 — extensions + shared helpers
-- MAJÁK schema foundation. All timestamps are timestamptz; the app operates in
-- Europe/Bratislava and converts at the edges.

create extension if not exists pg_trgm;
create extension if not exists vector;
-- gen_random_uuid() lives in pgcrypto on some builds; pg 15 ships it in core,
-- but ensure it is present.
create extension if not exists pgcrypto;

-- Generic updated_at trigger used by tables that carry an updated_at column.
create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;
