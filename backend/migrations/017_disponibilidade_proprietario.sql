alter table public.consoles add column owner_onboarding_agent_id uuid references public.console_agents(id);
alter table public.consoles add column owner_requested_psn_account_id uuid references public.psn_accounts(id) on delete set null;

create table public.owner_console_rates (
  id uuid primary key default gen_random_uuid(),
  console_id uuid not null unique references public.consoles(id),
  min_minutes integer not null check (min_minutes between 1 and 480),
  max_minutes integer not null check (max_minutes between min_minutes and 480),
  rate_unit text not null check (rate_unit in ('minute','hour')),
  rate_cents integer not null check (rate_cents between 1 and 1000000)
);
alter table public.owner_console_rates enable row level security;
