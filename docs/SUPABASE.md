# Configurando o Supabase (plano gratuito)

1. Crie um projeto em https://supabase.com (região **South America (São Paulo)**). Guarde a senha do banco.
2. Em **Project Settings → Database → Connection string**, escolha **Session pooler** (funciona em IPv4; a conexão direta do plano gratuito é só IPv6). Copie a URI e acrescente `?sslmode=require`:
   `postgresql://postgres.SEU_REF:SUA_SENHA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres?sslmode=require`
3. Coloque em `backend/.env` como `DATABASE_URL` e rode:
   ```bash
   python -m app.migrate --status   # lista migrations
   python -m app.migrate            # cria as 59 tabelas, triggers de auditoria e RLS
   python -m app.seed --admin       # dados base + superadministrador
   ```
   Alternativa sem Python: cole cada arquivo de `backend/migrations/` em ordem no **SQL Editor** (o executor Python registra checksums em `schema_migrations`; prefira ele).
4. A extensão `btree_gist` é criada no schema `extensions` (padrão do Supabase) — é ela que impede reservas sobrepostas no mesmo console.

## Segurança no Supabase
- Todas as tabelas têm **RLS ativado sem políticas** e os papéis `anon`/`authenticated` têm acesso revogado: a chave pública do Supabase **não lê nada**. Somente a API (conectando como `postgres`, dono das tabelas) acessa o banco.
- Não use a `anon key`/`service_role` no frontend. Este projeto não precisa delas.
- Autenticação é feita pela API (Argon2id, códigos por e-mail, TOTP), não pelo Supabase Auth — assim o mesmo código roda em PostgreSQL local, nos testes e no Supabase.

## Organização do banco
| Domínio | Tabelas |
|---|---|
| Identidade | users, roles, role_assignments, auth_sessions, email_verification_codes, password_reset_tokens, mfa_factors, mfa_recovery_codes, linked_accounts, oauth_states |
| LGPD/políticas | policy_documents, policy_acceptances, data_subject_requests |
| Catálogo | platforms, genres, games, game_platforms, game_genres, favorites |
| Consoles/GameBridge | consoles, console_agents, capture_devices, control_adapters, console_connection_configs, console_method_changes, remote_play_pairings, console_connection_tests, console_health_samples, console_operating_hours, streaming_channels |
| Agenda/comercial | console_game_assignments, blackout_windows, price_packages, coupons, coupon_redemptions, reservations, reservation_holds, queue_entries, cancellation_requests, service_incidents |
| Pagamentos | payments, payment_events, webhook_events, refunds |
| Sessões | game_sessions, session_connections, session_input_tokens, session_events |
| Comunicação | notification_templates, notification_preferences, notifications, notification_deliveries, dev_mailbox, support_tickets, support_messages |
| Sistema | audit_logs, global_settings, rate_limit_buckets, schema_migrations |

Cada tabela tem `id` (uuid), colunas tipadas com `check`, chaves estrangeiras, `created_at`/`updated_at`
(atualizado por trigger) e comentários nas colunas mais sensíveis. Regras críticas também estão no banco:
- `reservations_no_overlap` e `cga_no_overlap`: exclusão de intervalos por console (sem overbooking mesmo sob concorrência);
- `game_sessions_one_active_per_console`: um único controlador por console;
- `ccc_capture_uq` / `ccc_control_uq`: uma entrada HDMI e um canal de controle não servem dois consoles;
- `consoles_publish_guard`: console só é publicado com vídeo, áudio, controle e heartbeat validados.

## Log de alterações
`audit_logs` recebe automaticamente **INSERT, UPDATE (com a lista de campos alterados) e DELETE** de 52 tabelas,
com o usuário que fez a ação (`actor_user_id`), IP e `request_id`. Senhas, hashes de códigos e segredos aparecem
como `[REDACTED]`. O próprio log é imutável (trigger bloqueia UPDATE/DELETE). Ações de negócio (cancelamento pelo
admin, troca de licença, exportação de relatório…) entram com `source='app'` e justificativa.
Tabelas de alto volume (telemetria, eventos de sessão, eventos de pagamento) não têm trigger, para caber no plano gratuito.

```sql
select occurred_at, action, table_name, changed_fields, actor_user_id
from audit_logs where table_name = 'reservations' order by id desc limit 50;
```

## Limites do plano gratuito
- 500 MB de banco; o worker apaga amostras de telemetria com mais de 7 dias.
- O projeto é pausado após 7 dias sem atividade (reative pelo painel).
- Backups diários automáticos não estão no plano gratuito: use `pg_dump` periódico.
