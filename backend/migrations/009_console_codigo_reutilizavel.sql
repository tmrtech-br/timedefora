-- 009 — Console excluído (deleted_at) libera o código e o número de série para um novo cadastro.
alter table public.consoles drop constraint if exists consoles_code_key;
create unique index if not exists consoles_code_active_uq on public.consoles (code) where deleted_at is null;

drop index if exists public.consoles_serial_uq;
create unique index if not exists consoles_serial_active_uq on public.consoles (serial_number)
  where serial_number is not null and deleted_at is null;
