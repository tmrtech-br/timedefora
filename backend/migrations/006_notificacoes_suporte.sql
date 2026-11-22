-- =====================================================================
-- 006 — Notificações (in-app/e-mail), preferências, entregas, suporte
-- =====================================================================
create table if not exists public.notification_templates (
  id         uuid primary key default gen_random_uuid(),
  code       text not null,
  channel    text not null check (channel in ('email','in_app')),
  subject    text not null,
  body_html  text not null default '',
  body_text  text not null,
  active     boolean not null default true,
  version    integer not null default 1,
  updated_by uuid references public.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (code, channel)
);

create table if not exists public.notification_preferences (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid not null unique references public.users(id) on delete cascade,
  email_queue_updates  boolean not null default true,
  email_reminders      boolean not null default true,
  email_marketing      boolean not null default false,
  in_app_enabled       boolean not null default true,
  reminder_minutes     integer[] not null default '{15,10,5,1}',
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create table if not exists public.notifications (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.users(id) on delete cascade,
  event_code text not null,
  title      text not null,
  body       text not null,
  link       text,
  dedupe_key text not null unique,
  read_at    timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists notifications_user_idx on public.notifications (user_id, created_at desc);

create table if not exists public.notification_deliveries (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid references public.users(id) on delete cascade,
  channel             text not null check (channel in ('email','in_app')),
  event_code          text not null,
  template_code       text not null,
  dedupe_key          text not null unique,      -- sessão/reserva + evento + canal
  to_address          text,
  payload             jsonb not null default '{}'::jsonb,
  status              text not null default 'pending' check (status in ('pending','sending','sent','failed','skipped')),
  attempts            integer not null default 0,
  max_attempts        integer not null default 5,
  next_attempt_at     timestamptz not null default now(),
  last_error          text,
  provider_message_id text,
  sent_at             timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index if not exists deliveries_pending_idx on public.notification_deliveries (next_attempt_at) where status in ('pending','failed');

-- Caixa de e-mails de desenvolvimento (EMAIL_PROVIDER=dev). Vazia em produção.
create table if not exists public.dev_mailbox (
  id          bigint generated always as identity primary key,
  to_address  text not null,
  subject     text not null,
  body_text   text not null,
  body_html   text not null default '',
  created_at  timestamptz not null default now()
);

create table if not exists public.support_tickets (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.users(id) on delete cascade,
  reservation_id uuid references public.reservations(id),
  subject        text not null check (char_length(subject) between 3 and 140),
  category       text not null default 'geral' check (category in ('geral','pagamento','sessao','conta','reembolso','tecnico')),
  status         text not null default 'open' check (status in ('open','in_progress','resolved','closed')),
  priority       text not null default 'normal' check (priority in ('low','normal','high','urgent')),
  assigned_to    uuid references public.users(id),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists public.support_messages (
  id             uuid primary key default gen_random_uuid(),
  ticket_id      uuid not null references public.support_tickets(id) on delete cascade,
  author_user_id uuid not null references public.users(id),
  is_staff       boolean not null default false,
  body           text not null check (char_length(body) between 1 and 5000),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
