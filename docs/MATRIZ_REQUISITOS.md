# Matriz de rastreabilidade de requisitos

Estados: **VALIDADO** = implementado e coberto por teste executado · **IMPLEMENTADO** = código integrado e exercitado manualmente/E2E, sem teste dedicado · **SIMULADO** = funciona apenas com o simulador, identificado na interface · **BLOQUEADO** = código pronto, depende de credencial/hardware/autorização externa · **PARCIAL** · **PENDENTE**.

Testes: `B:` backend (`backend/tests/…`), `E:` Playwright (`frontend/e2e/…`).

| ID | Requisito | Arquivos principais | Estado | Teste / observação |
|---|---|---|---|---|
| R01 | Cadastro (nome, usuário público, e-mail, senha, confirmação, aceite de termos/privacidade) | services/auth.py, app/cadastrar | VALIDADO | B: test_cadastro_validacoes; E: jornada |
| R02 | Código de 6 dígitos, 10 min, hash HMAC, limite de tentativas, cooldown de reenvio | services/auth.py, migrations/002 | VALIDADO | B: test_cadastro_codigo_correto…, test_codigo_incorreto_limite… |
| R03 | Recursos pagos bloqueados até confirmar e-mail | core/deps.py `verified_user` | VALIDADO | B: test_email_nao_verificado_nao_pode_reservar |
| R04 | Login, bloqueio por tentativas, mensagem genérica, rate limit | services/auth.py, core/security.py | VALIDADO | B: test_login_generico_bloqueio_e_rate_limit |
| R05 | Recuperação de senha com token de 30 min e revogação de sessões | services/auth.py | VALIDADO | B: test_recuperacao_de_senha_revoga_sessoes |
| R06 | Troca de e-mail com confirmação no novo endereço | services/auth.py, routers/me.py | VALIDADO | B: test_troca_de_email… |
| R07 | Google OAuth/OIDC com PKCE, sem vínculo por coincidência de e-mail | services/google_oauth.py | BLOQUEADO | Requer GOOGLE_CLIENT_ID/SECRET; fluxo sem teste automatizado (depende do Google) |
| R08 | MFA TOTP obrigatório para equipe, antirreplay, códigos de recuperação | services/auth.py, core/deps.py | VALIDADO | B: test_rbac_admin_exige_papel_e_mfa; E: painel administrativo |
| R09 | Senhas Argon2id, cookies HttpOnly/SameSite, CSRF double-submit, checagem de Origin | core/security.py, main.py | VALIDADO | B: test_csrf_obrigatorio_e_origem |
| R10 | Perfil: nome, usuário, avatar, senha, sessões ativas, histórico, favoritos, horas, total gasto | routers/me.py, app/perfil, app/configuracoes | IMPLEMENTADO | Conquistas internas: PENDENTE (marcado "em breve") |
| R11 | Contas externas Twitch/Kick/Discord só como perfil público, sem senha | routers/me.py | IMPLEMENTADO | Validação de URL por serviço |
| R12 | LGPD: exportação, solicitações de acesso/retificação/exclusão/portabilidade, anonimização | routers/me.py, routers/admin.py | VALIDADO | B: test_lgpd_exportacao…; políticas são rascunho (revisão jurídica PENDENTE) |
| R13 | Dashboard/home fiel à referência com dados do backend | app/page.tsx, routers/catalog.py | VALIDADO | E: home desktop/mobile (screenshot + medidas) |
| R14 | Destaque por minutos jogados/sessões/receita ou manual | services/catalog.py | IMPLEMENTADO | Métrica configurável em global_settings |
| R15 | Seções: disponíveis, mais jogados, lançamentos, próximos, promoções, recentes, favoritos, recomendações | routers/catalog.py | PARCIAL | API retorna todas; a home mostra apenas a composição da referência (6 cards) |
| R16 | Catálogo: busca, filtros console/gênero/preço/disponibilidade, ordenação | app/jogos, routers/catalog.py | VALIDADO | E: catálogo filtra e mostra estado vazio |
| R17 | Página do jogo: janela, tempo restante, último período livre, próxima disponibilidade, avisos | services/scheduling.py `availability_summary` | IMPLEMENTADO | E: jornada (página exibida) |
| R18 | Cadastro independente de jogos e consoles | routers/admin.py | VALIDADO | B: test_vinculo_sobreposto…, E: admin cria console |
| R19 | Vínculo jogo×console por janela, sem sobreposição, recorrência, plataforma compatível | migrations/004 `cga_no_overlap`, routers/admin.py | VALIDADO | B: test_vinculo_sobreposto_plataforma_e_recorrencia |
| R20 | Alterar janela com reservas pagas exige resolução, aviso, reembolso, auditoria | routers/admin.py `_resolve_affected` | VALIDADO | B: test_alterar_janela_com_reserva_paga_exige_resolucao |
| R21 | Método de conexão obrigatório por console (Remote Play, HDMI, Native, Simulador, Não configurado) com campos dinâmicos | routers/admin.py, components/admin/Consoles.tsx | VALIDADO | B: test_hdmi_exige…, test_remote_play_nao_aplicavel_a_xbox… |
| R22 | HDMI exige capturadora e canal de controle separado; canal físico exclusivo | migrations/003, routers/admin.py | VALIDADO | B: test_hdmi_exige_capturadora_e_controle_separado_e_canal_exclusivo |
| R23 | Publicação só com vídeo/áudio/controle/heartbeat validados (também no banco) | migrations/003 trigger, routers/admin.py | VALIDADO | B: test_publicacao_bloqueada_no_banco…, test_validacao_simulada_publica… |
| R24 | Troca de método bloqueada com sessão/reserva; histórico e rollback | routers/admin.py | VALIDADO | B: test_validacao_simulada_publica_e_troca_de_metodo_bloqueada… |
| R25 | Pareamento Remote Play pelo admin, segredo só como referência ao cofre do agente | routers/admin.py, migrations/003 | BLOQUEADO | Simulador valida o fluxo; Chiaki depende do ConsoleAgent |
| R26 | Contrato GameBridge (11 operações), adaptadores isolados do negócio | app/gamebridge/* | VALIDADO | B: test_todos_adaptadores_implementam…, test_servicos_de_negocio_nao_importam… |
| R27 | Adaptador Chiaki Web Remote Play | gamebridge/agent_client.py | BLOQUEADO | Hardware, ConsoleAgent e análise AGPL-3.0 pendentes |
| R28 | Adaptador HDMI + controle separado | gamebridge/agent_client.py | BLOQUEADO | Capturadora e interface de controle autorizadas |
| R29 | GameBridge Native | gamebridge/agent_client.py | PENDENTE (placeholder recusa tudo) | Por definição do adendo |
| R30 | Pacotes e preços no servidor (jogo/console/plataforma/horário), promoções, cupons | services/scheduling.py | VALIDADO | B: test_preco_e_pacote…, test_cupom_percentual… |
| R31 | Motor: S≥A, S+D≤B, B exclusivo para iniciar | services/scheduling.py | VALIDADO | B: test_regra_central…, 09:30/09:50/10:00 |
| R32 | Caso 09:30+30 aceito; 09:50+30 bloqueado; 09:50+10 aceito; 10:00 bloqueado | services/scheduling.py | VALIDADO | B: test_0930…, test_0950…(2), test_1000… |
| R33 | Sessão até 09:50 impede nova de 30 min; fila anterior impede compra | services/scheduling.py | VALIDADO | B: test_sessao_ate_0950…, test_fila_anterior… |
| R34 | Concorrência sem overbooking (lock + constraint de exclusão) | services/scheduling.py, migrations/004 | VALIDADO | B: 20 reservas simultâneas → 1 aceita; inserção direta bloqueada |
| R35 | Setup entre jogadores, manutenção, horário de funcionamento | services/scheduling.py | VALIDADO | B: test_setup…, test_horario_de_funcionamento… |
| R36 | Reserva provisória de 5 min com expiração | services/scheduling.py | VALIDADO | B: test_hold_provisorio_bloqueia_e_expira |
| R37 | Fila FIFO com nomes públicos, posição e estimativa; antecipação quando libera | services/scheduling.py | VALIDADO | B: test_fifo…, test_cancelamento_libera… |
| R38 | Atualização "em tempo real" | hooks.ts (polling 5 s) | PARCIAL | Atualização periódica; WebSocket não implementado |
| R39 | Mercado Pago Checkout Pro (Pix/cartão), idempotência | services/payment_providers.py | BLOQUEADO | Requer MP_ACCESS_TOKEN; fluxo validado com provedor simulado |
| R40 | Webhook com assinatura, antirreplay, duplicado, fora de ordem, valor divergente | routers/play.py, services/payments.py | VALIDADO | B: test_webhook_assinatura_invalida…, test_webhook_valido_duplicado…, test_valor_divergente… |
| R41 | Pagamento tardio: reconfirma se livre; senão não fura a fila e reembolsa | services/scheduling.py `confirm_reservation` | VALIDADO | B: test_pagamento_tardio_… (2) |
| R42 | Cancelamento/reembolso conforme política, solicitações analisadas pelo admin | routers/play.py, routers/admin.py | VALIDADO | B: test_cancelamento_com_antecedencia… |
| R43 | Avisos 15/10/5/1 min, deduplicados, e-mail "Sua vez está chegando" e "pronto" | worker.py, seed.py (templates) | VALIDADO | B: test_aviso_5_minutos_deduplicado_e_aviso_de_pronto |
| R44 | Envio real de e-mails | services/email_provider.py | BLOQUEADO | Requer SMTP/Resend; em dev grava em dev_mailbox |
| R45 | Sala de espera: cronômetro do servidor, teste de rede, áudio, input, gamepad | app/sessoes/[id] | IMPLEMENTADO | E: jornada |
| R46 | Sessão exclusiva com token efêmero; A não controla B; revogação no fim com navegador aberto | services/sessions.py | VALIDADO | B: test_join_token_input_e_expiracao…, test_usuario_a_nao_controla… |
| R47 | Atraso não estende; reconexão revoga token anterior; no-show; encerramento antecipado libera | services/sessions.py, worker.py | VALIDADO | B: test_reconexao…, test_aviso_antes_do_fim_e_ausencia, test_encerrar_antes… |
| R48 | Teclado/mouse e Gamepad API | app/jogar, components/InputTester.tsx | IMPLEMENTADO | E: comando de teclado chega ao servidor |
| R49 | Streaming privado WebRTC | — | PENDENTE | Sem vídeo real; depende do ConsoleAgent |
| R50 | Stream público Twitch/Kick com offline, sem controles | components/PublicStream.tsx | IMPLEMENTADO / BLOQUEADO | Embed pronto; requer canal e domínio autorizado |
| R51 | Painel admin: visão geral, consoles, jogos, vínculos/calendário, agentes, preços, filas, reservas, sessões, transmissões, financeiro, usuários, notificações, auditoria, configurações | routers/admin.py, components/admin/* | IMPLEMENTADO | E: painel administrativo; calendário sem drag-and-drop |
| R52 | RBAC cliente/operador/admin/superadmin no servidor | core/deps.py | VALIDADO | B: test_rbac… |
| R53 | Relatórios e CSV (com neutralização de fórmulas) | routers/admin.py | VALIDADO | B: test_relatorio_csv… |
| R54 | Auditoria de INSERT/UPDATE/DELETE com ator, mascaramento e imutabilidade | migrations/001, 007 | VALIDADO | B: test_auditoria_registra… |
| R55 | Proteção IDOR/BOLA | routers/play.py | VALIDADO | B: test_idor_reserva_de_outro_usuario |
| R56 | Banco PostgreSQL/Supabase, migrations versionadas, RLS | migrations/*, app/migrate.py | VALIDADO | Aplicado do zero em todo `pytest`; RLS/revoke testados com roles do Supabase |
| R57 | Heartbeat/queda do agente → console offline + incidente | worker.py | VALIDADO | B: test_falha_de_heartbeat… |
| R58 | Licenciamento comercial bloqueia venda | services/scheduling.py | VALIDADO | B: test_jogo_sem_licenca… |
| R59 | CI, Docker Compose, .env.example | .github/workflows, docker-compose.yml | IMPLEMENTADO | CI não executado nesta entrega (sem repositório remoto) |
| R60 | Observabilidade (métricas, tracing, alertas externos), backups automáticos | — | PENDENTE | Logs estruturados básicos e /health existem |
| R61 | Testes de carga | — | PENDENTE | |
| R62 | Parâmetros liga/desliga no painel (plataformas, vendas, modos fila/horário, cupons, cadastro, Google, teclado/mouse, transmissões, chamados) aplicados no servidor | services/settings_store.py, admin/Params.tsx, GET /features | VALIDADO | B: tests/test_parametros.py (8 testes); visual por screenshot |
| R63 | Teste de conexão real (latência, variação, download) na sala de espera | GET /net/ping, /net/download, NetworkTest.tsx | IMPLEMENTADO | Mede até o servidor da API, não até o console |
| R64 | Limite de caracteres com contador e campos obrigatórios em todos os formulários | components/ui.tsx (Field) | IMPLEMENTADO | Padrão 50; campos longos com limite explícito; servidor também valida |
| R65 | Rota de rede do Remote Play: mesma rede, internet via PSN ou portas abertas (DDNS) | migrations/008, admin.py set_connection, Consoles.tsx | IMPLEMENTADO | B: test_rota_de_rede_remote_play_pela_internet; conexão real depende do ConsoleAgent |
| R66 | ConsoleAgent Parte 1: heartbeat, autenticação nos dois sentidos, saúde e descoberta real do PS4/PS5 (UDP 987/9302); ações da Parte 2 respondem "não disponível"; resposta simulada de agente real não valida console | agent/consoleagent, admin.py run_test, agent_client.py | VALIDADO (sem hardware) | A: 15 testes; B: test_console_agent_integracao + 3 testes; descoberta com PS4 real pendente |
| R67 | Preparação do console antes da sessão (console livre); falha → sessão não inicia, reserva em resolução, incidente automático, cliente e equipe notificados | services/preparation.py, worker.py, sessions.join, migrations/010 | VALIDADO (simulador) | B: test_preparacao.py; preparação real (acordar/abrir jogo) depende do ConsoleAgent Parte 2 |
| R68 | Botão Share bloqueado por padrão (parâmetro) | settings share_button_enabled, sessions.send_input | VALIDADO | B: test_share_bloqueado_por_padrao |
| R69 | Checklist de instalação de console (conta dedicada, conta de criança com limite de gastos R$ 0, restrições, energia, atualizações) | docs/CHECKLIST_INSTALACAO_CONSOLE.md | DOCUMENTADO | Configuração manual no console/PSN |
