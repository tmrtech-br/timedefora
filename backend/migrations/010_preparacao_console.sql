-- 010 — Preparação do console antes da sessão (acordar o console e garantir o jogo aberto).
-- Se o console não ficar pronto, a sessão não começa: a reserva vai para resolução, um incidente
-- é aberto e a equipe é notificada — o cliente não perde tempo.
create table if not exists public.console_preparations (
  id              uuid primary key default gen_random_uuid(),
  reservation_id  uuid not null unique references public.reservations(id) on delete cascade,
  console_id      uuid not null references public.consoles(id),
  status          text not null default 'pending' check (status in ('pending','ready','failed')),
  attempts        integer not null default 0,
  simulated       boolean not null default false,
  last_message    text,
  ready_at        timestamptz,
  failed_at       timestamptz,
  incident_id     uuid references public.service_incidents(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists console_preparations_status_idx on public.console_preparations (status, console_id);

drop trigger if exists console_preparations_audit on public.console_preparations;
create trigger console_preparations_audit after insert or update or delete on public.console_preparations
  for each row execute function public.audit_row_change();
drop trigger if exists console_preparations_updated_at on public.console_preparations;
create trigger console_preparations_updated_at before update on public.console_preparations
  for each row execute function public.set_updated_at();

alter table public.console_preparations enable row level security;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.console_preparations from anon, authenticated';
  end if;
end $$;
