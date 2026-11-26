-- 011 — Novo método de conexão: Remote Play DIRETO (o agente fala o protocolo com o console, sem chiaki-ng).
--        Permite vários consoles por PC, cada um com seu próprio controle, sem janelas nem monitores.
do $$
declare c record;
begin
  -- A restrição original (003) foi criada sem nome explícito: remove qualquer CHECK que valide a coluna method.
  for c in
    select con.conname from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace ns on ns.oid = rel.relnamespace
    where ns.nspname = 'public' and rel.relname = 'console_connection_configs' and con.contype = 'c'
      and pg_get_constraintdef(con.oid) ilike '%method%' and con.conname <> 'ccc_method_ck'
  loop
    execute format('alter table public.console_connection_configs drop constraint %I', c.conname);
  end loop;
  if not exists (select 1 from pg_constraint where conname = 'ccc_method_ck') then
    alter table public.console_connection_configs add constraint ccc_method_ck
      check (method in ('unconfigured','remote_play_chiaki','remote_play_direct','native_remote_play','hdmi_capture','simulated'));
  end if;
end $$;

comment on column public.console_connection_configs.method is
  'remote_play_direct = protocolo Remote Play direto no agente (rede local, vários consoles por PC); remote_play_chiaki = via chiaki-ng';
