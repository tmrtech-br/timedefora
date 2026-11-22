-- =====================================================================
-- 003 — Inventário: plataformas, jogos, consoles, agentes, captura,
-- controle, configuração de conexão (GameBridge), pareamento, testes,
-- saúde, canais de transmissão pública
-- =====================================================================
create table if not exists public.platforms (
  id                  uuid primary key default gen_random_uuid(),
  code                text not null unique,      -- PS4, PS5, XBOX_SERIES, SWITCH...
  name                text not null,
  manufacturer        text not null,
  family              text not null check (family in ('playstation','xbox','nintendo','other')),
  remote_play_capable boolean not null default false, -- matriz de compatibilidade (não garante funcionamento)
  notes               text not null default '',
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table if not exists public.genres (
  id         uuid primary key default gen_random_uuid(),
  slug       text not null unique,
  name       text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.games (
  id                         uuid primary key default gen_random_uuid(),
  slug                       text not null unique check (slug ~ '^[a-z0-9-]{2,80}$'),
  title                      text not null check (char_length(title) between 1 and 120),
  short_description          text not null default '',
  description                text not null default '',
  cover_url                  text,
  banner_url                 text,
  trailer_url                text,
  trailer_licensed           boolean not null default false,
  age_rating                 text check (age_rating in ('L','10','12','14','16','18')),
  release_date               date,
  requirements               text not null default '',
  status                     text not null default 'draft' check (status in ('draft','published','unpublished','archived')),
  min_minutes                integer not null default 10 check (min_minutes > 0),
  max_minutes                integer not null default 120 check (max_minutes >= min_minutes),
  featured_manual            boolean not null default false,   -- destaque manual do admin
  featured_rank              integer,
  commercial_license_status  text not null default 'not_verified'
                             check (commercial_license_status in ('not_verified','pending','authorized','denied')),
  commercial_license_doc_url text,
  commercial_license_notes   text not null default '',
  license_verified_by        uuid references public.users(id),
  license_verified_at        timestamptz,
  image_rights_notes         text not null default '',
  stream_rights_allowed      boolean not null default false,
  is_demo                    boolean not null default false,  -- dados demonstrativos (seed)
  created_by                 uuid references public.users(id),
  updated_by                 uuid references public.users(id),
  deleted_at                 timestamptz,
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now()
);
comment on column public.games.commercial_license_status is 'Venda real só é permitida com authorized (ou is_demo em ambiente de desenvolvimento).';

create table if not exists public.game_platforms (
  id          uuid primary key default gen_random_uuid(),
  game_id     uuid not null references public.games(id) on delete cascade,
  platform_id uuid not null references public.platforms(id) on delete restrict,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (game_id, platform_id)
);

create table if not exists public.game_genres (
  id         uuid primary key default gen_random_uuid(),
  game_id    uuid not null references public.games(id) on delete cascade,
  genre_id   uuid not null references public.genres(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (game_id, genre_id)
);

alter table public.favorites drop constraint if exists favorites_game_fk;
alter table public.favorites add constraint favorites_game_fk foreign key (game_id) references public.games(id) on delete cascade;

create table if not exists public.console_agents (
  id                uuid primary key default gen_random_uuid(),
  name              text not null unique,
  host_name         text not null,
  description       text not null default '',
  location          text not null default '',
  agent_version     text,
  endpoint_url      text,                       -- URL HTTPS do ConsoleAgent na rede interna/VPN
  status            text not null default 'unknown' check (status in ('unknown','online','degraded','offline')),
  credential_hash   text,                       -- hash do token que o AGENTE usa para chamar a API (heartbeat)
  outbound_token_enc text,                      -- token (AES-GCM) que a API usa para chamar o agente
  is_simulated      boolean not null default false,
  last_heartbeat_at timestamptz,
  cpu_limit_pct     integer check (cpu_limit_pct between 1 and 100),
  ram_limit_mb      integer check (ram_limit_mb > 0),
  network_limit_mbps integer check (network_limit_mbps > 0),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create table if not exists public.consoles (
  id            uuid primary key default gen_random_uuid(),
  code          text not null unique check (code ~ '^[A-Z0-9-]{3,30}$'),   -- PS5-01
  name          text not null,                                             -- PS5 nº 01
  platform_id   uuid not null references public.platforms(id),
  manufacturer  text not null default '',
  model         text not null default '',
  serial_number text,
  description   text not null default '',
  location      text not null default '',
  status        text not null default 'unconfigured'
                check (status in ('unconfigured','maintenance','offline','online','degraded','disabled')),
  is_published  boolean not null default false,  -- só publica após validação completa
  agent_id      uuid references public.console_agents(id),
  notes         text not null default '',
  created_by    uuid references public.users(id),
  updated_by    uuid references public.users(id),
  deleted_at    timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index if not exists consoles_serial_uq on public.consoles (serial_number) where serial_number is not null;

create table if not exists public.capture_devices (
  id                         uuid primary key default gen_random_uuid(),
  agent_id                   uuid not null references public.console_agents(id) on delete restrict,
  manufacturer               text not null,
  model                      text not null,
  device_identifier          text not null,       -- id físico no host
  input_port                 text not null default 'HDMI-1',
  supports_simultaneous_inputs boolean not null default false,
  max_resolution             text not null default '1080p',
  max_fps                    integer not null default 60,
  status                     text not null default 'unknown' check (status in ('unknown','ok','error','disconnected')),
  notes                      text not null default '',
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now(),
  unique (agent_id, device_identifier, input_port)
);

create table if not exists public.control_adapters (
  id              uuid primary key default gen_random_uuid(),
  agent_id        uuid not null references public.console_agents(id) on delete restrict,
  adapter_type    text not null check (adapter_type in ('remote_play_input','usb_controller_interface','bluetooth_controller_interface','other')),
  manufacturer    text not null default '',
  model           text not null default '',
  identifier      text not null,
  mapping_profile jsonb not null default '{}'::jsonb,
  authorized      boolean not null default false,  -- autorização/compatibilidade confirmada
  status          text not null default 'unknown' check (status in ('unknown','ok','error','disconnected')),
  notes           text not null default '',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (agent_id, identifier)
);

create table if not exists public.console_connection_configs (
  id                    uuid primary key default gen_random_uuid(),
  console_id            uuid not null unique references public.consoles(id) on delete cascade,
  method                text not null default 'unconfigured'
                        check (method in ('unconfigured','remote_play_chiaki','native_remote_play','hdmi_capture','simulated')),
  agent_id              uuid references public.console_agents(id),
  internal_host         text,                    -- IP/hostname na LAN (nunca exposto ao jogador)
  console_identifier    text,
  discovery_mode        text not null default 'manual' check (discovery_mode in ('manual','lan_discovery')),
  resolution            text not null default '1080p' check (resolution in ('720p','1080p')),
  fps                   integer not null default 60 check (fps in (30,60)),
  codec                 text not null default 'h264' check (codec in ('h264','h265')),
  bitrate_kbps          integer not null default 10000 check (bitrate_kbps between 1000 and 50000),
  low_latency           boolean not null default true,
  audio_enabled         boolean not null default true,
  capture_device_id     uuid references public.capture_devices(id),
  capture_color_space   text,
  video_encoder         text,
  control_adapter_id    uuid references public.control_adapters(id),
  connection_status     text not null default 'unconfigured'
                        check (connection_status in ('unconfigured','pairing','online','degraded','offline','error')),
  video_validated_at    timestamptz,
  audio_validated_at    timestamptz,
  control_validated_at  timestamptz,
  heartbeat_validated_at timestamptz,
  validated_at          timestamptz,             -- todos os canais validados
  validated_by          uuid references public.users(id),
  last_check_at         timestamptz,
  version               integer not null default 1,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  check (method <> 'hdmi_capture' or (capture_device_id is not null and control_adapter_id is not null) or connection_status = 'unconfigured')
);
-- Um canal HDMI físico e um adaptador de controle não podem servir dois consoles.
create unique index if not exists ccc_capture_uq on public.console_connection_configs (capture_device_id) where capture_device_id is not null;
create unique index if not exists ccc_control_uq on public.console_connection_configs (control_adapter_id) where control_adapter_id is not null;

create table if not exists public.console_method_changes (
  id              uuid primary key default gen_random_uuid(),
  console_id      uuid not null references public.consoles(id) on delete cascade,
  from_method     text not null,
  to_method       text not null,
  config_snapshot jsonb not null,               -- configuração anterior completa (rollback)
  reason          text not null default '',
  changed_by      uuid references public.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table if not exists public.remote_play_pairings (
  id                      uuid primary key default gen_random_uuid(),
  console_id              uuid not null references public.consoles(id) on delete cascade,
  agent_id                uuid references public.console_agents(id),
  status                  text not null default 'pending' check (status in ('pending','paired','expired','failed','revoked')),
  secret_reference        text,                  -- referência ao cofre do agente; NUNCA o segredo
  pairing_code_expires_at timestamptz,
  paired_at               timestamptz,
  revoked_at              timestamptz,
  initiated_by            uuid references public.users(id),
  error_message           text,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);
create unique index if not exists rpp_active_uq on public.remote_play_pairings (console_id) where status in ('pending','paired');

create table if not exists public.console_connection_tests (
  id         uuid primary key default gen_random_uuid(),
  console_id uuid not null references public.consoles(id) on delete cascade,
  test_type  text not null check (test_type in ('discover','pair','connection','video_audio','controls','heartbeat','latency')),
  result     text not null check (result in ('passed','failed','not_available')),
  simulated  boolean not null default false,
  message    text not null default '',
  metrics    jsonb not null default '{}'::jsonb,
  run_by     uuid references public.users(id),
  run_at     timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists cct_console_idx on public.console_connection_tests (console_id, run_at desc);

-- Amostras de telemetria (alto volume: sem trigger de auditoria).
create table if not exists public.console_health_samples (
  id               bigint generated always as identity primary key,
  console_id       uuid not null references public.consoles(id) on delete cascade,
  agent_id         uuid references public.console_agents(id),
  checked_at       timestamptz not null default now(),
  status           text not null check (status in ('online','degraded','offline','error')),
  fps              real,
  bitrate_kbps     real,
  rtt_ms           real,
  jitter_ms        real,
  packet_loss_pct  real,
  frames_dropped   integer,
  input_latency_ms real,
  temperature_c    real,
  simulated        boolean not null default false,
  error            text
);
create index if not exists chs_console_idx on public.console_health_samples (console_id, checked_at desc);

create table if not exists public.console_operating_hours (
  id          uuid primary key default gen_random_uuid(),
  console_id  uuid not null references public.consoles(id) on delete cascade,
  weekday     smallint not null check (weekday between 0 and 6),   -- 0=domingo (America/Fortaleza)
  opens_at    time not null,
  closes_at   time not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  check (opens_at < closes_at)
);

create table if not exists public.streaming_channels (
  id                   uuid primary key default gen_random_uuid(),
  console_id           uuid references public.consoles(id) on delete cascade,
  game_id              uuid references public.games(id) on delete cascade,
  provider             text not null check (provider in ('twitch','kick','external')),
  channel_name         text,
  external_url         text,
  status               text not null default 'offline' check (status in ('offline','live','disabled')),
  privacy_mask_enabled boolean not null default true,
  notes                text not null default '',
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  check (console_id is not null or game_id is not null),
  check (provider = 'external' or channel_name ~ '^[A-Za-z0-9_]{2,40}$'),
  check (provider <> 'external' or external_url like 'https://%')
);

-- Guarda de publicação: console só pode ser publicado com todos os canais validados.
create or replace function public.consoles_publish_guard() returns trigger
language plpgsql as $$
declare cfg record;
begin
  if new.is_published and (tg_op = 'INSERT' or not old.is_published) then
    select * into cfg from public.console_connection_configs where console_id = new.id;
    if cfg is null or cfg.method = 'unconfigured' or cfg.validated_at is null
       or cfg.video_validated_at is null or cfg.audio_validated_at is null
       or cfg.control_validated_at is null or cfg.heartbeat_validated_at is null then
      raise exception 'Console % não pode ser publicado sem vídeo, áudio, controle e heartbeat validados', new.code
        using errcode = 'check_violation';
    end if;
  end if;
  return new;
end $$;
drop trigger if exists consoles_publish_guard on public.consoles;
create trigger consoles_publish_guard before insert or update of is_published on public.consoles
  for each row execute function public.consoles_publish_guard();
