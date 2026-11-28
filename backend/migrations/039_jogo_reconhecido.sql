-- 039 - Código do jogo (CUSA/PPSA) reconhecido no console: a preparação abre o jogo pelo menu e confirma pelo console
-- (presença PSN pela internet ou DDP na rede local), sem roteiro nem imagem.
alter table public.game_launch_scripts add column if not exists title_id text;
alter table public.game_launch_scripts add column if not exists title_name text;
alter table public.game_launch_scripts add column if not exists settle_seconds integer;
alter table public.game_launch_scripts drop constraint if exists game_launch_scripts_title_ck;
alter table public.game_launch_scripts add constraint game_launch_scripts_title_ck
  check ((title_id is null or title_id ~ '^[A-Z]{4}[0-9]{5}$') and (settle_seconds is null or settle_seconds between 0 and 300));
