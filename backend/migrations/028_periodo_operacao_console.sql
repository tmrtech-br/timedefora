alter table public.consoles
  add column operating_starts_at timestamptz,
  add column operating_ends_at timestamptz,
  add constraint console_operating_period_check check (
    (operating_starts_at is null and operating_ends_at is null) or
    (operating_starts_at is not null and operating_ends_at is not null and operating_starts_at < operating_ends_at)
  );
alter table public.console_connection_configs alter column bitrate_kbps set default 6000;
