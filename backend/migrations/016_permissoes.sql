create table public.user_permissions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references public.users(id) on delete cascade,
  version integer not null default 1 check (version > 0),
  overrides jsonb not null default '{}' check (jsonb_typeof(overrides)='object')
);
alter table public.user_permissions enable row level security;
