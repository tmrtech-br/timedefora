-- =====================================================================
-- 002 — Identidade, autenticação, perfis, papéis, MFA, LGPD
-- =====================================================================
create table if not exists public.users (
  id                  uuid primary key default gen_random_uuid(),
  full_name           text not null check (char_length(full_name) between 3 and 120),
  username            text not null check (username ~ '^[A-Za-z0-9_\.]{3,24}$'),  -- nome público (fila)
  email               text not null check (position('@' in email) > 1),
  email_verified_at   timestamptz,
  password_hash       text,                     -- Argon2id; nulo para contas só-Google
  status              text not null default 'pending_verification'
                      check (status in ('pending_verification','active','suspended','deleted')),
  avatar_url          text,
  locale              text not null default 'pt-BR',
  timezone            text not null default 'America/Fortaleza',
  failed_login_count  integer not null default 0,
  locked_until        timestamptz,
  last_login_at       timestamptz,
  suspended_reason    text,
  marketing_opt_in    boolean not null default false,
  deleted_at          timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create unique index if not exists users_email_uq on public.users (lower(email)) where deleted_at is null;
create unique index if not exists users_username_uq on public.users (lower(username));
comment on table public.users is 'Contas de usuário (perfil e credenciais). Nome civil e e-mail nunca são exibidos publicamente.';

create table if not exists public.roles (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique check (code in ('client','operator','admin','superadmin')),
  name        text not null,
  description text not null default '',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.role_assignments (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.users(id) on delete cascade,
  role_id     uuid not null references public.roles(id) on delete restrict,
  granted_by  uuid references public.users(id),
  granted_at  timestamptz not null default now(),
  revoked_at  timestamptz,
  revoked_by  uuid references public.users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create unique index if not exists role_assignments_active_uq on public.role_assignments (user_id, role_id) where revoked_at is null;

create table if not exists public.auth_sessions (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references public.users(id) on delete cascade,
  token_hash       text not null unique,          -- SHA-256 do token do cookie
  ip               text,
  user_agent       text,
  mfa_verified_at  timestamptz,
  created_at       timestamptz not null default now(),
  last_seen_at     timestamptz not null default now(),
  expires_at       timestamptz not null,
  revoked_at       timestamptz,
  revoked_reason   text,
  updated_at       timestamptz not null default now()
);
create index if not exists auth_sessions_user_idx on public.auth_sessions (user_id) where revoked_at is null;

create table if not exists public.email_verification_codes (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.users(id) on delete cascade,
  purpose        text not null check (purpose in ('signup','email_change')),
  target_email   text not null,
  code_hash      text not null,                 -- HMAC-SHA256 (nunca texto puro)
  attempts       integer not null default 0,
  max_attempts   integer not null default 5,
  expires_at     timestamptz not null,
  last_sent_at   timestamptz not null default now(),
  send_count     integer not null default 1,
  consumed_at    timestamptz,
  invalidated_at timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists evc_user_idx on public.email_verification_codes (user_id, purpose) where consumed_at is null and invalidated_at is null;

create table if not exists public.password_reset_tokens (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.users(id) on delete cascade,
  token_hash  text not null unique,
  ip          text,
  expires_at  timestamptz not null,
  used_at     timestamptz,
  invalidated_at timestamptz,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.mfa_factors (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.users(id) on delete cascade,
  factor_type     text not null default 'totp' check (factor_type in ('totp')),
  totp_secret_enc text not null,                -- AES-GCM com chave do servidor
  confirmed_at    timestamptz,
  last_used_step  bigint,                       -- antirreplay de código TOTP
  disabled_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create unique index if not exists mfa_factors_active_uq on public.mfa_factors (user_id) where disabled_at is null;

create table if not exists public.mfa_recovery_codes (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.users(id) on delete cascade,
  code_hash  text not null,
  used_at    timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.linked_accounts (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references public.users(id) on delete cascade,
  provider         text not null check (provider in ('google','twitch','kick','discord')),
  link_type        text not null check (link_type in ('oauth','public_profile')),
  provider_subject text,                         -- "sub" do OpenID (Google)
  provider_email   text,
  display_name     text,
  public_url       text,                         -- perfis públicos (Twitch/Kick/Discord) sem OAuth
  linked_at        timestamptz not null default now(),
  unlinked_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  check (link_type <> 'oauth' or provider_subject is not null)
);
create unique index if not exists linked_accounts_subject_uq on public.linked_accounts (provider, provider_subject)
  where unlinked_at is null and provider_subject is not null;
create unique index if not exists linked_accounts_user_provider_uq on public.linked_accounts (user_id, provider) where unlinked_at is null;

create table if not exists public.oauth_states (
  id            uuid primary key default gen_random_uuid(),
  provider      text not null,
  state_hash    text not null unique,
  code_verifier text not null,                  -- PKCE (curta duração)
  intent        text not null check (intent in ('login','link')),
  user_id       uuid references public.users(id) on delete cascade,
  redirect_to   text,
  expires_at    timestamptz not null,
  used_at       timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists public.policy_documents (
  id           uuid primary key default gen_random_uuid(),
  kind         text not null check (kind in ('terms','privacy','cancellation')),
  version      text not null,
  title        text not null,
  body         text not null,
  is_current   boolean not null default false,
  requires_legal_review boolean not null default true,
  published_at timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (kind, version)
);
create unique index if not exists policy_documents_current_uq on public.policy_documents (kind) where is_current;

create table if not exists public.policy_acceptances (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.users(id) on delete cascade,
  policy_id      uuid not null references public.policy_documents(id),
  context        text not null check (context in ('signup','checkout','update')),
  reservation_id uuid,
  ip             text,
  accepted_at    timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists public.data_subject_requests (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.users(id) on delete cascade,
  request_type text not null check (request_type in ('access','rectification','deletion','portability','consent_revocation')),
  details      text not null default '',
  status       text not null default 'open' check (status in ('open','in_progress','completed','rejected')),
  resolution   text,
  resolved_by  uuid references public.users(id),
  resolved_at  timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create table if not exists public.favorites (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.users(id) on delete cascade,
  game_id    uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, game_id)
);
