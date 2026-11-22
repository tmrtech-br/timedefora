-- 008 — Rota de rede do Remote Play: console na mesma rede do agente (LAN) ou acessado pela internet
--        (via PSN, sem abrir portas; ou por redirecionamento de portas no roteador do console).
alter table public.console_connection_configs
  add column if not exists network_route text not null default 'lan',
  add column if not exists public_host   text,              -- DDNS/IP público do roteador do console (só port forward)
  add column if not exists public_port   integer;           -- porta base do Remote Play no roteador (padrão 9295)

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'ccc_network_route_ck') then
    alter table public.console_connection_configs
      add constraint ccc_network_route_ck check (network_route in ('lan','internet_psn','internet_port_forward'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'ccc_public_port_ck') then
    alter table public.console_connection_configs
      add constraint ccc_public_port_ck check (public_port is null or public_port between 1 and 65535);
  end if;
end $$;

comment on column public.console_connection_configs.network_route is
  'lan = agente na mesma rede do console; internet_psn = Remote Play via PSN (sem portas abertas); internet_port_forward = portas redirecionadas no roteador do console';
