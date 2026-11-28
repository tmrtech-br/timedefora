-- 037 - Conta PSN de console excluído volta a ficar livre.
-- A exclusão pelo proprietário não limpava a configuração de conexão, e a trava "uma conta PSN por PS4"
-- contava consoles excluídos: a conta ficava presa e o "Aplicar configuração e testar" falhava.
create or replace function public.check_psn_console_binding() returns trigger
language plpgsql as $$
declare platform_name text;
begin
    if NEW.method <> 'remote_play_native' or NEW.network_route <> 'internet_psn' then
        return NEW;
    end if;
    if NEW.psn_account_id is null then
        raise exception 'Conta PSN obrigatória para Remote Play nativo via internet';
    end if;
    if not exists (select 1 from public.psn_accounts p
                   where p.id = NEW.psn_account_id and p.agent_id = NEW.agent_id and p.status='linked') then
        raise exception 'Conta PSN deve estar vinculada e pertencer ao mesmo agente';
    end if;
    select p.code into platform_name from public.consoles c join public.platforms p on p.id=c.platform_id
       where c.id=NEW.console_id;
    if platform_name='PS4' then
        perform pg_advisory_xact_lock(hashtext(NEW.psn_account_id::text)::bigint);
        if exists (select 1 from public.console_connection_configs cfg
            join public.consoles c on c.id=cfg.console_id
            join public.platforms p on p.id=c.platform_id
            where cfg.psn_account_id=NEW.psn_account_id and cfg.console_id<>NEW.console_id
                and cfg.network_route='internet_psn' and cfg.method='remote_play_native' and p.code='PS4'
                and c.deleted_at is null) then
            raise exception 'Esta conta PSN já está vinculada a outro PS4 via internet';
        end if;
    end if;
    return NEW;
end $$;

-- Consoles já excluídos: solta conta PSN e dispositivos (igual à exclusão feita pela equipe).
update public.console_connection_configs cfg
   set capture_device_id=null, control_adapter_id=null, psn_account_id=null, psn_device_uid=null,
       connection_status='unconfigured', method='unconfigured'
  from public.consoles c
 where c.id = cfg.console_id and c.deleted_at is not null
   and (cfg.psn_account_id is not null or cfg.capture_device_id is not null or cfg.control_adapter_id is not null
        or cfg.method <> 'unconfigured');
