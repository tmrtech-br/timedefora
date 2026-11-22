-- =====================================================================
-- 004 — Agenda e comercial: vínculos jogo×console por janela, bloqueios,
-- pacotes, cupons, reservas, holds, fila, cancelamentos, incidentes
-- =====================================================================
create table if not exists public.console_game_assignments (
  id                  uuid primary key default gen_random_uuid(),
  console_id          uuid not null references public.consoles(id) on delete restrict,
  game_id             uuid not null references public.games(id) on delete restrict,
  starts_at           timestamptz not null,
  ends_at             timestamptz not null,
  period              tstzrange generated always as (tstzrange(starts_at, ends_at, '[)')) stored,
  status              text not null default 'active' check (status in ('active','cancelled','archived')),
  recurrence_group_id uuid,                      -- vínculos gerados por recorrência
  responsible_user_id uuid references public.users(id),
  notes               text not null default '',
  created_by          uuid references public.users(id),
  updated_by          uuid references public.users(id),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  check (starts_at < ends_at),
  -- Um console não pode ter duas janelas ativas sobrepostas.
  constraint cga_no_overlap exclude using gist (console_id with =, period with &&) where (status = 'active')
);
create index if not exists cga_game_idx on public.console_game_assignments (game_id, starts_at);

create table if not exists public.blackout_windows (
  id          uuid primary key default gen_random_uuid(),
  console_id  uuid not null references public.consoles(id) on delete cascade,
  starts_at   timestamptz not null,
  ends_at     timestamptz not null,
  period      tstzrange generated always as (tstzrange(starts_at, ends_at, '[)')) stored,
  kind        text not null default 'maintenance' check (kind in ('maintenance','blocked','event')),
  reason      text not null default '',
  status      text not null default 'active' check (status in ('active','cancelled')),
  created_by  uuid references public.users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  check (starts_at < ends_at)
);
create index if not exists blackout_console_idx on public.blackout_windows using gist (console_id, period) where status = 'active';

create table if not exists public.price_packages (
  id           uuid primary key default gen_random_uuid(),
  name         text not null,
  minutes      integer not null check (minutes between 5 and 480),
  price_cents  integer not null check (price_cents >= 0),
  currency     text not null default 'BRL' check (currency = 'BRL'),
  game_id      uuid references public.games(id) on delete cascade,      -- nulo = qualquer jogo
  console_id   uuid references public.consoles(id) on delete cascade,   -- nulo = qualquer console
  platform_id  uuid references public.platforms(id),
  valid_from   timestamptz,
  valid_until  timestamptz,
  local_start_time time,       -- faixa horária (America/Fortaleza), opcional
  local_end_time   time,
  is_promotion boolean not null default false,
  active       boolean not null default true,
  sort_order   integer not null default 0,
  created_by   uuid references public.users(id),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  check (valid_from is null or valid_until is null or valid_from < valid_until),
  check ((local_start_time is null) = (local_end_time is null))
);

create table if not exists public.coupons (
  id               uuid primary key default gen_random_uuid(),
  code             text not null unique check (code ~ '^[A-Z0-9_-]{3,30}$'),
  description      text not null default '',
  discount_type    text not null check (discount_type in ('percent','fixed')),
  discount_value   integer not null check (discount_value > 0),   -- % ou centavos
  max_redemptions  integer,
  per_user_limit   integer not null default 1,
  min_minutes      integer,
  game_id          uuid references public.games(id) on delete cascade,
  valid_from       timestamptz,
  valid_until      timestamptz,
  active           boolean not null default true,
  created_by       uuid references public.users(id),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  check (discount_type <> 'percent' or discount_value <= 100)
);

create table if not exists public.reservations (
  id                 uuid primary key default gen_random_uuid(),
  code               text not null unique,                 -- código curto exibido ao usuário
  user_id            uuid not null references public.users(id) on delete restrict,
  game_id            uuid not null references public.games(id) on delete restrict,
  console_id         uuid not null references public.consoles(id) on delete restrict,
  assignment_id      uuid not null references public.console_game_assignments(id) on delete restrict,
  package_id         uuid references public.price_packages(id),
  coupon_id          uuid references public.coupons(id),
  mode               text not null check (mode in ('queue','scheduled')),  -- fila (início estimado) x horário fixo
  minutes            integer not null check (minutes > 0),
  setup_minutes      integer not null default 0 check (setup_minutes >= 0),
  starts_at          timestamptz not null,
  ends_at            timestamptz not null,
  blocked_until      timestamptz not null,                 -- ends_at + setup/limpeza
  period             tstzrange generated always as (tstzrange(starts_at, blocked_until, '[)')) stored,
  status             text not null default 'pending_payment'
                     check (status in ('pending_payment','confirmed','active','completed','no_show',
                                       'cancelled','expired','needs_resolution','refunded')),
  price_cents        integer not null check (price_cents >= 0),
  discount_cents     integer not null default 0 check (discount_cents >= 0),
  total_cents        integer not null check (total_cents >= 0),
  hold_expires_at    timestamptz,
  confirmed_at       timestamptz,
  cancelled_at       timestamptz,
  cancelled_by       uuid references public.users(id),
  cancel_reason      text,
  resolution_notes   text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  check (starts_at < ends_at and ends_at <= blocked_until),
  check (total_cents = price_cents - discount_cents),
  -- Garantia final contra overbooking: nenhum intervalo ocupado se sobrepõe no mesmo console.
  constraint reservations_no_overlap exclude using gist (console_id with =, period with &&)
    where (status in ('pending_payment','confirmed','active'))
);
create index if not exists reservations_user_idx on public.reservations (user_id, created_at desc);
create index if not exists reservations_console_status_idx on public.reservations (console_id, status, starts_at);

create table if not exists public.coupon_redemptions (
  id             uuid primary key default gen_random_uuid(),
  coupon_id      uuid not null references public.coupons(id) on delete restrict,
  user_id        uuid not null references public.users(id) on delete restrict,
  reservation_id uuid not null unique references public.reservations(id) on delete cascade,
  discount_cents integer not null,
  status         text not null default 'reserved' check (status in ('reserved','redeemed','released')),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists public.reservation_holds (
  id              uuid primary key default gen_random_uuid(),
  reservation_id  uuid not null unique references public.reservations(id) on delete cascade,
  expires_at      timestamptz not null,
  released_at     timestamptz,
  release_reason  text check (release_reason in ('paid','expired','cancelled','late_payment_reconfirmed')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table if not exists public.queue_entries (
  id                  uuid primary key default gen_random_uuid(),
  reservation_id      uuid not null unique references public.reservations(id) on delete cascade,
  console_id          uuid not null references public.consoles(id),
  user_id             uuid not null references public.users(id),
  position            integer not null,
  status              text not null check (status in ('waiting','next','playing','done','left')),
  estimated_start_at  timestamptz not null,
  estimated_end_at    timestamptz not null,
  entered_at          timestamptz not null default now(),
  last_notified_position integer,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index if not exists queue_console_idx on public.queue_entries (console_id, position) where status in ('waiting','next','playing');

create table if not exists public.cancellation_requests (
  id             uuid primary key default gen_random_uuid(),
  reservation_id uuid not null references public.reservations(id) on delete cascade,
  user_id        uuid not null references public.users(id),
  reason         text not null,
  status         text not null default 'requested' check (status in ('requested','approved','denied')),
  decided_by     uuid references public.users(id),
  decided_at     timestamptz,
  decision_notes text,
  refund_cents   integer,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create unique index if not exists cancel_req_open_uq on public.cancellation_requests (reservation_id) where status = 'requested';

create table if not exists public.service_incidents (
  id                 uuid primary key default gen_random_uuid(),
  console_id         uuid references public.consoles(id),
  reservation_id     uuid references public.reservations(id),
  kind               text not null check (kind in ('console_failure','stream_failure','agent_offline','platform_delay','other')),
  description        text not null,
  started_at         timestamptz not null default now(),
  resolved_at        timestamptz,
  compensation       text check (compensation in ('none','extension','reschedule','refund')),
  compensation_notes text,
  created_by         uuid references public.users(id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
