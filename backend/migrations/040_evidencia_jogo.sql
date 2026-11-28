-- 040 - Evidência do reconhecimento do jogo (print da tela tirado pelo agente) para a equipe conferir na aprovação.
alter table public.game_launch_scripts add column if not exists evidence_png text;          -- PNG em base64 (tons de cinza, reduzido)
alter table public.game_launch_scripts add column if not exists detected_at timestamptz;
alter table public.game_launch_scripts add column if not exists detected_by uuid references public.users(id);
