-- Agentes que a equipe libera para proprietários escolherem no cadastro do console (o login PSN passa por eles).
alter table public.console_agents add column if not exists available_to_owners boolean not null default false;
comment on column public.console_agents.available_to_owners is
  'Proprietários podem escolher este agente ao cadastrar o console (permite conectar a conta PSN antes da análise).';
