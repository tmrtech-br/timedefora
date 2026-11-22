-- =====================================================================
-- 007 — Segurança: triggers de auditoria/updated_at em todas as tabelas
-- de negócio, RLS habilitado (negação por padrão) e revogação do acesso
-- direto das roles públicas do Supabase (anon/authenticated).
-- A API acessa o banco com papel de serviço; o navegador NUNCA acessa
-- o banco diretamente.
-- =====================================================================
do $$
declare
  t text;
  audited text[] := array[
    'global_settings','users','roles','role_assignments','auth_sessions','email_verification_codes',
    'password_reset_tokens','mfa_factors','mfa_recovery_codes','linked_accounts','oauth_states',
    'policy_documents','policy_acceptances','data_subject_requests','favorites',
    'platforms','genres','games','game_platforms','game_genres','console_agents','consoles',
    'capture_devices','control_adapters','console_connection_configs','console_method_changes',
    'remote_play_pairings','console_connection_tests','console_operating_hours','streaming_channels',
    'console_game_assignments','blackout_windows','price_packages','coupons','reservations',
    'coupon_redemptions','reservation_holds','queue_entries','cancellation_requests','service_incidents',
    'payments','webhook_events','refunds','game_sessions','session_connections','session_input_tokens',
    'notification_templates','notification_preferences','notifications','notification_deliveries',
    'support_tickets','support_messages'];
  all_tables text[];
begin
  foreach t in array audited loop
    execute format('drop trigger if exists %I on public.%I', t || '_audit', t);
    execute format('create trigger %I after insert or update or delete on public.%I
                    for each row execute function public.audit_row_change()', t || '_audit', t);
    if exists (select 1 from information_schema.columns
               where table_schema = 'public' and table_name = t and column_name = 'updated_at') then
      execute format('drop trigger if exists %I on public.%I', t || '_updated_at', t);
      execute format('create trigger %I before update on public.%I
                      for each row execute function public.set_updated_at()', t || '_updated_at', t);
    end if;
  end loop;

  select array_agg(table_name::text) into all_tables
    from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE';
  foreach t in array all_tables loop
    execute format('alter table public.%I enable row level security', t);
  end loop;

  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on all tables in schema public from anon, authenticated';
    execute 'revoke all on all sequences in schema public from anon, authenticated';
    execute 'alter default privileges in schema public revoke all on tables from anon, authenticated';
  end if;
end $$;
