-- Validação do console do proprietário: rascunho → em análise → aprovado (equipe vincula o agente e libera a
-- publicação). Edições em console aprovado ficam pendentes (o console segue no ar com a versão aprovada).
alter table public.consoles add column if not exists owner_review_status text not null default 'draft';
alter table public.consoles add column if not exists owner_review_notes text not null default '';
alter table public.consoles add column if not exists owner_submitted_at timestamptz;
alter table public.consoles add column if not exists owner_reviewed_at timestamptz;
alter table public.consoles add column if not exists owner_reviewed_by uuid references public.users(id);
alter table public.consoles add column if not exists owner_approved_at timestamptz;
alter table public.consoles add column if not exists owner_pending jsonb not null default '{}'::jsonb;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'consoles_owner_review_status_ck') then
    alter table public.consoles add constraint consoles_owner_review_status_ck
      check (owner_review_status in ('draft','submitted','approved','changes_pending','rejected'));
  end if;
end $$;
-- Consoles de proprietário já publicados antes deste fluxo contam como aprovados.
update public.consoles set owner_review_status='approved', owner_approved_at=coalesce(owner_approved_at, now())
 where owner_user_id is not null and is_published and owner_review_status='draft';

-- Janela de jogo pedida pelo proprietário num console já aprovado: aguarda a equipe (não vende até aprovar).
alter table public.console_game_assignments drop constraint if exists console_game_assignments_status_check;
alter table public.console_game_assignments add constraint console_game_assignments_status_check
  check (status in ('active','cancelled','archived','pending_review'));

insert into public.notification_templates (code, channel, subject, body_text) values
  ('owner_review', 'in_app', 'Análise do console {console}: {resultado}', '{mensagem}')
on conflict (code, channel) do nothing;
insert into public.notification_templates (code, channel, subject, body_text, body_html) values
  ('owner_review', 'email', 'Análise do console {console}: {resultado}', '{mensagem} Veja no portal do proprietário: {link}',
   '<p style="margin:0 0 16px">Olá, {nome_usuario}!</p><p style="margin:0 0 16px">{mensagem}</p><a href="{link}" style="display:inline-block;padding:12px 18px;border-radius:8px;background-color:#6525ad;color:#ffffff;font-weight:bold;text-decoration:none">Abrir o portal do proprietário</a>')
on conflict (code, channel) do nothing;
