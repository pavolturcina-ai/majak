-- 0007 — pg_cron schedule for the two daily runs.
-- Guarded so a fresh local DB without pg_cron still applies the rest of the schema.
-- Times are given in UTC by pg_cron; Europe/Bratislava is UTC+1 (winter) / UTC+2 (summer).
-- The job bodies call the API via pg_net; adjust the URL/secret for the deployment.
-- These schedules are the fallback when the API-side scheduler is disabled.

do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pg_cron') then
    create extension if not exists pg_cron;
    create extension if not exists pg_net;

    -- 18:00 Europe/Bratislava close_and_open_tomorrow.
    perform cron.schedule(
      'majak_close_and_open',
      '0 16 * * *',   -- 16:00 UTC ≈ 18:00 CEST (summer); revisit for winter DST
      $cron$
        select net.http_post(
          url := current_setting('majak.api_base', true) || '/scheduler/close-and-open',
          headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'Authorization', 'Bearer ' || current_setting('majak.cron_secret', true)
          )
        );
      $cron$
    );

    -- 04:00 Europe/Bratislava fill_overnight.
    perform cron.schedule(
      'majak_fill_overnight',
      '0 2 * * *',    -- 02:00 UTC ≈ 04:00 CEST (summer)
      $cron$
        select net.http_post(
          url := current_setting('majak.api_base', true) || '/scheduler/fill-overnight',
          headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'Authorization', 'Bearer ' || current_setting('majak.cron_secret', true)
          )
        );
      $cron$
    );
  else
    raise notice 'pg_cron not available; skipping cron schedule (use the API scheduler instead).';
  end if;
end;
$$;
