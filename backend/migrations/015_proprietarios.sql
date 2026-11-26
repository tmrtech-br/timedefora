alter table public.roles drop constraint roles_code_check;
alter table public.roles add constraint roles_code_check
  check (code in ('client','operator','admin','superadmin','owner'));
insert into public.roles (code, name, description)
values ('owner', 'Proprietário/Locador', 'Portal e inventário do proprietário')
on conflict (code) do nothing;

alter table public.policy_documents drop constraint policy_documents_kind_check;
alter table public.policy_documents add constraint policy_documents_kind_check
  check (kind in ('terms','privacy','cancellation','owner_terms'));
alter table public.policy_acceptances drop constraint policy_acceptances_context_check;
alter table public.policy_acceptances add constraint policy_acceptances_context_check
  check (context in ('signup','checkout','update','owner_enrollment'));
create unique index policy_acceptances_owner_uq
  on public.policy_acceptances(user_id, policy_id) where context='owner_enrollment';

insert into public.policy_documents(kind, version, title, body, is_current, published_at)
values ('owner_terms', '1', 'Termos do proprietário', $terms$
Mantenha o console nas configurações exigidas pela plataforma e com internet estável, preferencialmente cabeada.
Não utilize o console durante as sessões alugadas.
Você assume o risco de bloqueio ou suspensão pela Sony da conta PSN vinculada.
$terms$, true, now());

alter table public.consoles add column owner_user_id uuid references public.users(id);
alter table public.psn_accounts add column owner_user_id uuid references public.users(id);
create index consoles_owner_idx on public.consoles(owner_user_id) where owner_user_id is not null;
create index psn_accounts_owner_idx on public.psn_accounts(owner_user_id) where owner_user_id is not null;

alter table public.console_connection_tests add column duration_ms integer
  check (duration_ms >= 0);
