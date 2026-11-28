-- 038 - Roteiros de abertura dos jogos, por console, editáveis pelo proprietário e pela equipe.
-- Antes só existiam no config.json do agente; jogo sem roteiro deixava o console parado no menu do PS4.
create table if not exists public.game_launch_scripts (
    id uuid primary key default gen_random_uuid(),
    console_id uuid not null references public.consoles(id) on delete cascade,
    game_id uuid not null references public.games(id) on delete cascade,
    steps jsonb not null default '[]'::jsonb,        -- lista de passos (texto), mesmo formato do config.json do agente
    images jsonb not null default '{}'::jsonb,       -- nome -> {png (base64, tons de cinza), width (largura da tela de origem)}
    updated_by uuid references public.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint game_launch_scripts_unique unique (console_id, game_id),
    constraint game_launch_scripts_steps_ck check (jsonb_typeof(steps) = 'array' and jsonb_array_length(steps) <= 60),
    constraint game_launch_scripts_images_ck check (jsonb_typeof(images) = 'object')
);
alter table public.game_launch_scripts enable row level security;
create index if not exists game_launch_scripts_game_idx on public.game_launch_scripts(game_id);
