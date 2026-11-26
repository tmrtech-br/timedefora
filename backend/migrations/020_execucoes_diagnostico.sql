create table public.console_diagnostic_runs (
  id uuid primary key default gen_random_uuid(),
  console_id uuid not null references public.consoles(id),
  requested_by uuid not null references public.users(id),
  status text not null default 'queued' check (status in ('queued','running','completed','failed')),
  pairing_code_enc text,
  results jsonb not null default '[]' check (jsonb_typeof(results)='array'),
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create unique index console_diagnostic_runs_active_idx
  on public.console_diagnostic_runs(console_id) where status in ('queued','running');
alter table public.console_diagnostic_runs enable row level security;
