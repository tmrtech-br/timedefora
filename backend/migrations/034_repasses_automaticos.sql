-- Repasse ao proprietário: agendado 10 min após uma sessão concluída sem problemas, para o Pix/conta cadastrados.
-- O envio passa por um provedor configurável (payout_provider); "manual" = a equipe paga e marca como pago.
create table if not exists public.owner_payouts (
  id                 uuid primary key default gen_random_uuid(),
  settlement_id      uuid not null unique references public.owner_settlements(id) on delete restrict,
  owner_user_id      uuid not null references public.users(id),
  amount_cents       integer not null check (amount_cents > 0),
  destination_kind   text check (destination_kind in ('pix','bank')),
  destination_masked text,
  status             text not null default 'scheduled'
                     check (status in ('scheduled','waiting_destination','awaiting_manual','processing','paid','failed')),
  scheduled_for      timestamptz not null,
  provider           text not null default 'manual',
  provider_ref       text,
  proof_url          text,
  notes              text not null default '',
  attempts           integer not null default 0,
  last_error         text,
  paid_at            timestamptz,
  paid_by            uuid references public.users(id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists owner_payouts_status_idx on public.owner_payouts(status, scheduled_for);
create index if not exists owner_payouts_owner_idx on public.owner_payouts(owner_user_id, created_at desc);
alter table public.owner_payouts enable row level security;

insert into public.notification_templates (code, channel, subject, body_text) values
  ('owner_payout_paid', 'in_app', 'Repasse de {valor} enviado', 'Enviamos {valor} para {destino}, referente à sessão de {jogo}.')
on conflict (code, channel) do nothing;
insert into public.notification_templates (code, channel, subject, body_text, body_html) values
  ('owner_payout_paid', 'email', 'Repasse de {valor} enviado', 'Enviamos {valor} para {destino}, referente à sessão de {jogo}. Detalhes: {link}',
   '<p style="margin:0 0 16px">Olá, {nome_usuario}!</p><p style="margin:0 0 16px">Enviamos <strong>{valor}</strong> para <strong>{destino}</strong>, referente à sessão de {jogo}.</p><a href="{link}" style="display:inline-block;padding:12px 18px;border-radius:8px;background-color:#6525ad;color:#ffffff;font-weight:bold;text-decoration:none">Ver meus repasses</a>')
on conflict (code, channel) do nothing;
