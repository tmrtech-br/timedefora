alter table public.reservations add column owner_user_id uuid references public.users(id);
alter table public.reservations add column owner_share_bps integer check (owner_share_bps between 0 and 10000);
alter table public.reservations add constraint reservations_owner_share_ck
  check ((owner_user_id is null) = (owner_share_bps is null));
create index reservations_owner_idx on public.reservations(owner_user_id) where owner_user_id is not null;

create table public.owner_payout_destinations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references public.users(id),
  kind text not null check (kind in ('pix','bank')),
  destination_enc text not null,
  masked text not null,
  updated_at timestamptz not null default now()
);
alter table public.owner_payout_destinations enable row level security;

alter table public.service_incidents add column owner_fault text
  check (owner_fault in ('renter','console'));
alter table public.service_incidents add column owner_approved_cents integer check (owner_approved_cents >= 0);

create table public.owner_settlements (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null unique references public.game_sessions(id),
  reservation_id uuid not null unique references public.reservations(id),
  owner_user_id uuid not null references public.users(id),
  base_cents integer not null check (base_cents >= 0),
  owner_share_bps integer not null check (owner_share_bps between 0 and 10000),
  owner_cents integer not null check (owner_cents between 0 and base_cents),
  status text not null check (status in ('held','eligible','cancelled','paid')),
  updated_at timestamptz not null default now()
);
create index owner_settlements_history_idx on public.owner_settlements(owner_user_id, updated_at desc);
alter table public.owner_settlements enable row level security;
