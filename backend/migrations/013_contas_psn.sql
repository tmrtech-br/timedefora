-- 013 - Metadados de contas PSN. Segredos ficam SOMENTE no cofre DPAPI do ConsoleAgent.
-- Executável novamente sem destruir dados (idempotente, aditivo).
create table if not exists public.psn_accounts (
    id uuid primary key default gen_random_uuid(),
    agent_id uuid not null references public.console_agents(id),
    label text not null,
    online_id text,
    account_id text,
    status text not null default 'pending'
      check (status in ('pending','linked','expired','error','disabled')),
    last_check_at timestamptz,
    last_error text not null default '',
    created_by uuid references public.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint psn_account_agent_label_uk unique(agent_id,label)
);
create unique index if not exists psn_account_label_ci_uk on public.psn_accounts(agent_id, lower(label));

alter table public.console_connection_configs
  add column if not exists psn_account_id uuid references public.psn_accounts(id);
alter table public.console_connection_configs
  add column if not exists psn_device_uid text;
alter table public.console_connection_configs
  add column if not exists standby_after_session boolean not null default true;
alter table public.console_connection_configs
  add column if not exists keep_awake_minutes integer not null default 15;

-- Add the limits idempotently; existing deployments may already have custom constraints.
do $$ begin
    if not exists (select 1 from pg_constraint where conname='ccc_keep_awake_minutes_ck'
                   and conrelid='public.console_connection_configs'::regclass) then
        alter table public.console_connection_configs
          add constraint ccc_keep_awake_minutes_ck check (keep_awake_minutes between 0 and 240);
    end if;
end $$;

-- Upgrade the 011 method check. Preserve legacy methods.
alter table public.console_connection_configs drop constraint if exists ccc_method_ck;
alter table public.console_connection_configs add constraint ccc_method_ck check
    (method in ('unconfigured','remote_play_chiaki','remote_play_direct',
                'remote_play_native','native_remote_play','hdmi_capture','simulated'));

-- Prevent reuse of an account for two different internet PS4 consoles and
-- enforce that linked accounts belong to the configured agent (also validated by API).
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
                and cfg.network_route='internet_psn' and cfg.method='remote_play_native' and p.code='PS4') then
            raise exception 'Esta conta PSN já está vinculada a outro PS4 via internet';
        end if;
    end if;
    return NEW;
end $$;

drop trigger if exists trg_psn_console_binding on public.console_connection_configs;
create trigger trg_psn_console_binding
before insert or update of psn_account_id, agent_id, method, network_route
on public.console_connection_configs for each row
execute function public.check_psn_console_binding();

comment on table public.psn_accounts is
  'Somente metadados PSN; tokens de OAuth e chaves do console permanecem no Windows ConsoleAgent via DPAPI.';
