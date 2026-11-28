-- Remarcação por falha da plataforma: a nova reserva aponta para a original (o pagamento continua nela).
alter table public.reservations add column if not exists rescheduled_from uuid references public.reservations(id);
create index if not exists reservations_rescheduled_from_idx on public.reservations(rescheduled_from) where rescheduled_from is not null;
comment on column public.reservations.rescheduled_from is
  'Reserva original quando esta foi criada por remarcação (falha da plataforma); o pagamento/estorno usa a original.';
