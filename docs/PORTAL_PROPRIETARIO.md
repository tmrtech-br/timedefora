# Portal do proprietário

Antes de iniciar a aplicação com esta versão, aplique as migrações `015` a `022` com `python -m app.migrate` a partir de `backend`. A fila de diagnóstico usa o worker da aplicação. Execute a API com `RUN_WORKER=true` ou mantenha `python -m app.worker` em um processo separado.

## Superadmin

Conceda o papel `owner` em **Usuários e permissões**. O proprietário confirma o e-mail e aceita a versão vigente dos termos em **Portal do proprietário**. Ele pode acumular o papel de locatário. A API impede o acúmulo do papel de proprietário com papéis de equipe.

Abra **Cadastro de console** para criar um rascunho ou retomar um console existente. Para um console de proprietário, selecione um agente autorizado para habilitar o cadastro de PSN no portal. Configure a conexão com a conta proposta, associe um jogo a uma janela, defina os horários operacionais quando aplicáveis e rode os diagnósticos. A publicação exige a conexão validada e um jogo publicado com janela vigente ou futura. Consoles de proprietário também exigem tarifa.

Em **Usuários e permissões → Permissões**, marque ou desmarque menus, níveis mínimos e ações por rota. O backend aplica as restrições além dos requisitos de papel e MFA existentes. Em **Parâmetros**, `owner_share_bps` define a parcela global do proprietário. O padrão de 3000 equivale a 30% sobre o valor da reserva após desconto. A regra é congelada no momento da reserva.

Em **Sessões e incidentes**, associe o incidente à reserva. Para locação de proprietário, registre causa e justificativa. Incidente atribuído ao locatário solicita o estorno integral e cancela a parcela do proprietário. Para problema no console, o suporte pode informar um valor entre zero e a parcela definida na reserva.

## Proprietário

Cadastre um console no portal. Após a equipe autorizar um agente, cadastre e vincule a conta PSN pelo login da Sony. Selecione a conta para solicitar o vínculo com o console. Cadastre janelas de jogos e a tarifa por minuto ou por hora. A equipe configura e publica o console. Ajustes de agenda, tarifa e associação exigem um console despublicado.

Em **Recebimento**, cadastre PIX ou conta bancária. O portal exibe somente o destino mascarado. O dashboard apresenta tempo alugado, sessões realizadas, histórico e situação da apuração.

## Contratos de API

| Endpoint | Operação |
|---|---|
| `GET /owner/terms` | Retorna ID, versão, título, texto e data do aceite vigente, quando houver. |
| `POST /owner/enrollment` | Recebe `policy_version_id` e `accepted: true`. Aceites repetidos da mesma versão são idempotentes. Uma versão substituída retorna `409`. |
| `GET/POST /owner/psn-accounts` | Lista contas próprias ou recebe `console_id` e `label` para criar uma conta no agente autorizado. |
| `POST /owner/psn-accounts/{id}/login/start`, `/login/finish`, `/test` | Inicia autenticação, recebe `redirect_url` para concluir o vínculo e verifica a autenticação no agente. |
| `GET/POST /owner/consoles` | Lista inventário ou recebe `code`, `name` e `platform_code` para cadastrar PS4/PS5. |
| `PUT /owner/consoles/{id}/connection` | Recebe `psn_account_id` e registra a conta solicitada. |
| `GET/POST /owner/consoles/{id}/games` | Lista jogos compatíveis e janelas ou recebe `game_id`, `starts_at` e `ends_at` com fuso. |
| `GET/PUT /owner/consoles/{id}/availability` | Consulta ou grava `min_minutes`, `max_minutes`, `rate_unit` e `rate_cents`. |
| `GET /owner/dashboard`, `GET /owner/settlements` e `GET /owner/settlements/{id}` | Retorna totais, histórico de sessões, listagem paginada e detalhe de apurações do titular. |
| `GET/PUT /owner/payout-destination` | Consulta destino mascarado ou cadastra `kind` com chave PIX ou dados bancários. |
| `GET/PUT /admin/users/{id}/permissions` | Consulta catálogo e configurações individuais ou grava `version` e `overrides`. |
| `GET /me/permissions` | Informa os papéis e as configurações individuais da sessão autenticada. |
| `PUT /admin/console-onboardings/{id}/owner-agent` | Autoriza `agent_id` para o cadastro PSN pelo proprietário. |
| `POST /admin/console-onboardings/{id}/publish` | Publica após validação de conexão e vínculo de agenda. |
| `POST /admin/consoles/{id}/diagnostic-runs` | Agenda o lote, responde `202` e retorna o ID. Aceita `code` para pareamento manual quando aplicável. |
| `GET /admin/consoles/{id}/diagnostic-runs/{run_id}` | Retorna situação da execução e resultados persistidos, incluindo resultados parciais. |
| `POST /admin/incidents/{id}/resolve` | Aceita `owner_fault` e `owner_approved_cents` para decisões de locação de proprietário. |
| Exclusões administrativas | Envie JSON `{"reason":"Justificativa da exclusão"}` nas rotas de exclusão. O motivo acompanha a entrada de auditoria. |

## Persistência e operação

- `015` acrescenta titularidade ao inventário e termos versionados em `policy_documents` e `policy_acceptances`.
- `016` cria as configurações individuais versionadas em `user_permissions`.
- `017` registra o agente autorizado, a conta solicitada e as tarifas em `owner_console_rates`.
- `018` registra titularidade e regra financeira na reserva e cria `owner_payout_destinations` e `owner_settlements`. Os dados de recebimento são cifrados. O histórico financeiro anterior à migração permanece fora da apuração.
- `019` habilita o diagnóstico de autenticação PSN separado do teste de conexão. A confirmação de funcionamento com agente e console em redes distintas exige homologação em hardware real.
- `020` persiste a fila e os resultados. A execução aguarda o console sair de uma sessão ativa. O código de pareamento fica cifrado enquanto necessário e é removido quando o lote termina ou expira.
- `021` registra o tipo de teste individual e o estado de cancelamento do diagnóstico.
- `022` registra a pausa da disponibilidade. A pausa impede novas reservas e preserva as já registradas.

A apuração cria saldos elegíveis ou retidos após a sessão. O envio e a confirmação de dinheiro dependem da integração com um provedor de repasse. O Mercado Pago existente continua responsável pelas cobranças e pelos estornos. A aprovação de uma apuração para repasse não altera seu status para pago.
