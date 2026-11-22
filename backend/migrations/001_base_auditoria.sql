-- =====================================================================
-- 001 — Base: extensões, schema de auditoria e funções utilitárias
-- Compatível com Supabase (PostgreSQL 15+). Todos os horários em UTC
-- (timestamptz). Apresentação em America/Fortaleza é feita na aplicação.
-- =====================================================================
create schema if not exists extensions;
create extension if not exists btree_gist with schema extensions;

-- ---------------------------------------------------------------------
-- audit_logs: registro de TODA inserção, alteração e exclusão nas
-- tabelas de negócio (via trigger) e de eventos de negócio (via app).
-- ---------------------------------------------------------------------
create table if not exists public.audit_logs (
  id              bigint generated always as identity primary key,
  occurred_at     timestamptz not null default now(),
  source          text not null check (source in ('db_trigger','app')),
  action          text not null,                 -- INSERT | UPDATE | DELETE | ação de negócio (ex.: reservation.cancel)
  table_name      text,                          -- tabela afetada (trigger)
  record_id       text,                          -- id do registro afetado
  actor_user_id   uuid,                          -- usuário que originou a mudança (app.actor_id)
  actor_ip        text,                          -- IP de origem (app.actor_ip)
  request_id      text,                          -- correlação com logs da API
  old_data        jsonb,                         -- linha antes (segredos mascarados)
  new_data        jsonb,                         -- linha depois (segredos mascarados)
  changed_fields  text[],                        -- colunas alteradas em UPDATE
  reason          text,                          -- justificativa (ações administrativas)
  details         jsonb not null default '{}'::jsonb
);
create index if not exists audit_logs_table_record_idx on public.audit_logs (table_name, record_id);
create index if not exists audit_logs_actor_idx on public.audit_logs (actor_user_id, occurred_at desc);
create index if not exists audit_logs_occurred_idx on public.audit_logs (occurred_at desc);
comment on table public.audit_logs is 'Log imutável de alterações (INSERT/UPDATE/DELETE por trigger) e ações de negócio.';

-- Bloqueia alteração/remoção do próprio log (imutável).
create or replace function public.audit_logs_immutable() returns trigger
language plpgsql as $$
begin
  raise exception 'audit_logs é somente-inserção';
end $$;
drop trigger if exists audit_logs_no_update on public.audit_logs;
create trigger audit_logs_no_update before update or delete on public.audit_logs
  for each row execute function public.audit_logs_immutable();

-- Trigger genérico de auditoria. Colunas sensíveis são mascaradas.
create or replace function public.audit_row_change() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_old jsonb; v_new jsonb; v_changed text[]; k text;
  v_redact text[] := array['password_hash','code_hash','token_hash','state_hash','code_verifier',
                           'totp_secret_enc','secret_reference','credential_hash','secret_enc','outbound_token_enc'];
begin
  if tg_op in ('UPDATE','DELETE') then v_old := to_jsonb(old); end if;
  if tg_op in ('INSERT','UPDATE') then v_new := to_jsonb(new); end if;
  if tg_op = 'UPDATE' then
    select array_agg(n.key order by n.key) into v_changed
      from jsonb_each(v_new) n
     where n.value is distinct from v_old -> n.key and n.key <> 'updated_at';
    if v_changed is null then return new; end if;   -- nada mudou de fato
  end if;
  foreach k in array v_redact loop
    if v_old ? k and v_old ->> k is not null then v_old := jsonb_set(v_old, array[k], '"[REDACTED]"'); end if;
    if v_new ? k and v_new ->> k is not null then v_new := jsonb_set(v_new, array[k], '"[REDACTED]"'); end if;
  end loop;
  insert into public.audit_logs(source, action, table_name, record_id, actor_user_id, actor_ip,
                                request_id, old_data, new_data, changed_fields)
  values ('db_trigger', tg_op, tg_table_name, coalesce(v_new ->> 'id', v_old ->> 'id'),
          nullif(current_setting('app.actor_id', true), '')::uuid,
          nullif(current_setting('app.actor_ip', true), ''),
          nullif(current_setting('app.request_id', true), ''),
          v_old, v_new, v_changed);
  return coalesce(new, old);
end $$;

-- Atualiza updated_at automaticamente.
create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- Configurações globais operacionais (valores editáveis no admin).
create table if not exists public.global_settings (
  id          uuid primary key default gen_random_uuid(),
  key         text not null unique,
  value       jsonb not null,
  description text not null default '',
  updated_by  uuid,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
comment on table public.global_settings is 'Parâmetros operacionais: expiração de hold, setup, no-show, avisos etc.';

-- Limites de requisição (rate limit) por chave (ip+rota ou usuário+ação).
create table if not exists public.rate_limit_buckets (
  id                uuid primary key default gen_random_uuid(),
  bucket_key        text not null unique,
  window_started_at timestamptz not null,
  hits              integer not null default 0
);
