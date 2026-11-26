alter table public.console_diagnostic_runs drop constraint console_diagnostic_runs_status_check;
alter table public.console_diagnostic_runs add constraint console_diagnostic_runs_status_check
  check (status in ('queued','running','cancelling','cancelled','completed','failed'));
alter table public.console_diagnostic_runs add column test_type text
  check (test_type in ('discover','pair','psn_auth','connection','video_audio','controls','heartbeat','latency'));
drop index public.console_diagnostic_runs_active_idx;
create unique index console_diagnostic_runs_active_idx
  on public.console_diagnostic_runs(console_id) where status in ('queued','running','cancelling');
