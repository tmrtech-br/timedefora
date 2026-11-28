-- 036 - Login Sony feito pelo proprietário antes da aprovação (conta ainda sem agente).
-- O servidor guarda o acesso cifrado (AES-GCM) só até a equipe escolher o agente;
-- na aprovação ele é repassado ao cofre DPAPI do agente e apagado daqui.
alter table public.psn_accounts add column if not exists credentials_enc text;
alter table public.psn_accounts add column if not exists login_started_at timestamptz;
alter table public.psn_accounts drop constraint if exists psn_account_unassigned_ck;
alter table public.psn_accounts add constraint psn_account_unassigned_ck
  check (agent_id is not null or (owner_user_id is not null and (
    status in ('pending','disabled','expired','error') or (status = 'linked' and credentials_enc is not null))));

-- Auditoria: mascara também o acesso Sony cifrado.
create or replace function public.audit_row_change() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_old jsonb; v_new jsonb; v_changed text[]; k text;
  v_redact text[] := array['password_hash','code_hash','token_hash','state_hash','code_verifier',
                           'totp_secret_enc','secret_reference','credential_hash','secret_enc','outbound_token_enc','credentials_enc'];
begin
  if tg_op in ('UPDATE','DELETE') then v_old := to_jsonb(old); end if;
  if tg_op in ('INSERT','UPDATE') then v_new := to_jsonb(new); end if;
  if tg_op = 'UPDATE' then
    select array_agg(n.key order by n.key) into v_changed
      from jsonb_each(v_new) n
     where n.value is distinct from v_old -> n.key and n.key <> 'updated_at';
    if v_changed is null then return new; end if;   -- nada mudou de fato
  end if;
  foreach k in array v_redact loop
    if v_old ? k and v_old ->> k is not null then v_old := jsonb_set(v_old, array[k], '"[REDACTED]"'); end if;
    if v_new ? k and v_new ->> k is not null then v_new := jsonb_set(v_new, array[k], '"[REDACTED]"'); end if;
  end loop;
  insert into public.audit_logs(source, action, table_name, record_id, actor_user_id, actor_ip,
                                request_id, old_data, new_data, changed_fields)
  values ('db_trigger', tg_op, tg_table_name, coalesce(v_new ->> 'id', v_old ->> 'id'),
          nullif(current_setting('app.actor_id', true), '')::uuid,
          nullif(current_setting('app.actor_ip', true), ''),
          nullif(current_setting('app.request_id', true), ''),
          v_old, v_new, v_changed);
  return coalesce(new, old);
end $$;
