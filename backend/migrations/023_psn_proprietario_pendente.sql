alter table public.psn_accounts alter column agent_id drop not null;
alter table public.psn_accounts add constraint psn_account_unassigned_ck
  check (agent_id is not null or (owner_user_id is not null and status in ('pending','disabled')));
create unique index psn_account_owner_pending_label_uq
  on public.psn_accounts(owner_user_id, lower(label)) where agent_id is null;
