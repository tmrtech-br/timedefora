-- =====================================================================
-- 005 — Pagamentos, webhooks, reembolsos, sessões de jogo, tokens de
-- entrada, conexões e eventos de sessão
-- =====================================================================
create table if not exists public.payments (
  id                     uuid primary key default gen_random_uuid(),
  reservation_id         uuid not null references public.reservations(id) on delete restrict,
  user_id                uuid not null references public.users(id) on delete restrict,
  provider               text not null check (provider in ('mercadopago','simulated')),
  method                 text not null default 'unknown' check (method in ('pix','card','unknown')),
  status                 text not null default 'created'
                         check (status in ('created','pending','approved','rejected','cancelled','expired','refunded','charged_back')),
  amount_cents           integer not null check (amount_cents >= 0),
  currency               text not null default 'BRL',
  idempotency_key        text not null unique,
  provider_preference_id text,
  provider_payment_id    text,
  checkout_url           text,
  status_detail          text,
  approved_at            timestamptz,
  expires_at             timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);
create unique index if not exists payments_provider_payment_uq on public.payments (provider, provider_payment_id) where provider_payment_id is not null;
create index if not exists payments_reservation_idx on public.payments (reservation_id);

create table if not exists public.payment_events (
  id          bigint generated always as identity primary key,
  payment_id  uuid not null references public.payments(id) on delete cascade,
  from_status text,
  to_status   text not null,
  source      text not null check (source in ('api','webhook','reconciliation','admin','worker')),
  details     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create table if not exists public.webhook_events (
  id                uuid primary key default gen_random_uuid(),
  provider          text not null,
  dedupe_key        text not null,                 -- id da notificação/recurso+ação
  topic             text,
  resource_id       text,
  signature_valid   boolean not null,
  request_ts        bigint,                        -- timestamp assinado (antirreplay)
  payload           jsonb not null,
  processing_status text not null default 'received' check (processing_status in ('received','processed','ignored','failed','rejected')),
  error             text,
  received_at       timestamptz not null default now(),
  processed_at      timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (provider, dedupe_key)
);

create table if not exists public.refunds (
  id                 uuid primary key default gen_random_uuid(),
  payment_id         uuid not null references public.payments(id) on delete restrict,
  reservation_id     uuid not null references public.reservations(id) on delete restrict,
  amount_cents       integer not null check (amount_cents > 0),
  reason             text not null,
  status             text not null default 'requested' check (status in ('requested','processing','completed','failed')),
  provider_refund_id text,
  requested_by       uuid references public.users(id),
  error              text,
  completed_at       timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create table if not exists public.game_sessions (
  id                   uuid primary key default gen_random_uuid(),
  reservation_id       uuid not null unique references public.reservations(id) on delete restrict,
  user_id              uuid not null references public.users(id),
  console_id           uuid not null references public.consoles(id),
  status               text not null default 'ready' check (status in ('ready','active','ended','expired','failed')),
  adapter_method       text not null,
  input_device         text check (input_device in ('keyboard_mouse','gamepad')),
  released_at          timestamptz,              -- liberação efetiva do console
  first_connected_at   timestamptz,
  last_connected_at    timestamptz,
  contract_starts_at   timestamptz not null,
  contract_ends_at     timestamptz not null,
  ended_at             timestamptz,
  end_reason           text check (end_reason in ('time_up','user_ended','admin','failure','no_show')),
  seconds_used         integer not null default 0,
  compensation_minutes integer not null default 0,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
-- Um único controlador ativo por console.
create unique index if not exists game_sessions_one_active_per_console on public.game_sessions (console_id) where status in ('ready','active');

create table if not exists public.session_connections (
  id              uuid primary key default gen_random_uuid(),
  session_id      uuid not null references public.game_sessions(id) on delete cascade,
  connected_at    timestamptz not null default now(),
  disconnected_at timestamptz,
  disconnect_reason text,
  ip              text,
  user_agent      text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table if not exists public.session_input_tokens (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid not null references public.game_sessions(id) on delete cascade,
  user_id        uuid not null references public.users(id),
  reservation_id uuid not null references public.reservations(id),
  console_id     uuid not null references public.consoles(id),
  token_hash     text not null unique,
  issued_at      timestamptz not null default now(),
  expires_at     timestamptz not null,
  revoked_at     timestamptz,
  revoke_reason  text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- Eventos de sessão (alto volume: sem trigger de auditoria).
create table if not exists public.session_events (
  id          bigint generated always as identity primary key,
  session_id  uuid not null references public.game_sessions(id) on delete cascade,
  event_type  text not null,
  details     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists session_events_idx on public.session_events (session_id, created_at);
