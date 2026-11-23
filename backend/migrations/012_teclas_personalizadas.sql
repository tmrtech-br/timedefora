-- 012 — Teclas personalizadas do jogador (teclado/mouse → comandos do controle). NULL = mapeamento padrão do site.
alter table public.users add column if not exists input_bindings jsonb;

comment on column public.users.input_bindings is
  '{"keys": {"acao": "CodigoDaTecla"}, "mouse_look": bool, "mouse_sensitivity": número} — ver frontend/src/lib/keymap.ts';
