-- Os metadados PSN são acessados via backend, com autorização administrativa.
alter table public.psn_accounts enable row level security;
