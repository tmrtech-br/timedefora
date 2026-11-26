# Prompt para o Codex — Remote Play próprio, vários consoles e várias contas PSN no mesmo PC

> Copie tudo abaixo da linha para o Codex. Ele roda na raiz `e:\LocadoraOnline` (pasta `locaplay/` = produto,
> `chiaki-ng-main/` = código-fonte de referência do chiaki-ng, só leitura).

---

## 1. Objetivo

Você vai implementar no **LocaPlay** (locadora online de jogos por streaming) um **cliente Remote Play próprio, 100% em
Python**, dentro do ConsoleAgent, capaz de manter **várias sessões Remote Play simultâneas no mesmo PC**, cada uma com:

- um **console** (PS4 ou PS5), na **mesma rede** do PC do agente **ou em outra rede** (pela PSN, sem abrir portas);
- uma **conta PSN** vinculada (uma ou mais contas por agente);
- um **jogo** configurado no LocaPlay e um **jogador** do LocaPlay jogando pelo navegador.

Exemplo que DEVE funcionar ao final (critério de aceite principal):

1. Admin cadastra a conta PSN **teste01** e o console **PS4** de nome **testeps4** (vinculado à teste01).
2. Admin cadastra a conta PSN **teste02** e o console **PS5** de nome **testeps5** (vinculado à teste02).
3. No LocaPlay, testeps4 fica com o jogo **FIFA 26** e testeps5 com **GTA VI** (vínculo console↔jogo já existe: `console_game_assignments`).
4. **Jogador 01** reserva/joga FIFA 26 no testeps4; **Jogador 02** joga GTA VI no testeps5 — **ao mesmo tempo, no mesmo PC do agente**.
5. **Uma sessão nunca derruba, trava, atrasa ou recebe comandos da outra.**
6. Ao **conectar**, o console sai do repouso sozinho; ao **encerrar** a sessão do jogador, o console volta ao **repouso**
   (respeitando a regra da seção 7.4).
7. A latência (controle → imagem) deve ser a **menor possível** (seção 9).

**Nada de chiaki-ng em execução, nada de executável compilado, nada de janela, nada de controle virtual (ViGEm),
nada de captura de tela.** O chiaki-ng atual (método `remote_play_chiaki`) continua funcionando como está até o novo
método ser validado — não o remova nesta entrega.

## 2. Regras inegociáveis

1. **Só Python** (3.11+) no agente. Dependências novas só se forem wheels puras ou com binário pronto no PyPI para
   Windows x64 (ex.: `cryptography`, `aiohttp`, `websockets`, `av`). Sem compilar C.
2. **Nunca simular sucesso.** Um teste/conexão só passa com quadro de vídeo real decodificável vindo do console, áudio
   real e eco de controle real. Já existe essa regra no projeto (`simulated`, `media.Frame`); mantenha.
3. **Segredos** (tokens PSN, chaves de registro `RegistKey`/`RP-Key`, PIN) ficam **só no agente**, cifrados em disco
   (DPAPI do Windows via `ctypes`/`win32crypt`, ou AES-GCM com chave derivada da DPAPI). A API e o banco guardam só
   metadados (apelido da conta, online-id, account-id, estado). Nunca logar tokens, chaves ou PIN.
4. **Licença.** O protocolo PSN será **portado** do chiaki-ng (`chiaki-ng-main/lib`, **AGPL-3.0**) e a sessão vem da
   `pyremoteplay` incorporada (`locaplay/agent/pyremoteplay`, **GPL-3.0**). Todo código novo derivado deles fica em
   `locaplay/agent/remoteplay/` com cabeçalho de licença **AGPL-3.0-only**, `NOTICE.md` citando a origem
   (arquivo/linhas do chiaki-ng), e **sem importar nada** de `backend/` ou `frontend/`. O backend e o frontend falam com
   o agente só por HTTP/WebRTC (como hoje) e continuam fechados.
5. Não quebre o que existe: testes atuais de `locaplay/agent/tests` e `locaplay/backend/tests` devem continuar passando.
   Migrações são **aditivas** e idempotentes (`if not exists`), numeradas a partir de `013_`.
6. Textos de interface e mensagens de erro em **português do Brasil**, claros para o admin (o que aconteceu + o que fazer).
7. Código, nomes de variáveis e commits em inglês ou português — siga o estilo do arquivo que estiver editando.

## 3. O que já existe (leia antes de começar)

### Agente (`locaplay/agent/consoleagent/`)
| Arquivo | Papel |
|---|---|
| `server.py` | API HTTP do agente (FastAPI). `POST /v1/consoles/{console_id}/{action}`; um `ConsoleRuntime` **por console** (`runtimes`), cada um com seu "link". |
| `runtime.py` | Orquestra por console: `_bringup` (acordar → conectar → esperar imagem, com novas tentativas na PSN), `_open_game` (roteiro de botões para abrir o jogo), sessão do jogador, `revoke`, `disconnect`. Jobs em segundo plano com andamento consultável. |
| `links.py` | Interface comum de link. `ChiakiLink` (chiaki-ng em processo, legado) e **`DirectLink`** (pyremoteplay incorporada: uma sessão asyncio por console, vídeo decodificado para WebRTC, áudio próprio, controle próprio `DirectPad`). **Só rede local.** |
| `webrtc.py` | `WebRtcHub` (aiortc): vídeo/áudio para o navegador. Hoje **decodifica e recodifica** o vídeo. |
| `discovery.py` | Descoberta na LAN (UDP 987/9302) e pacote WAKEUP com a chave de registro. |
| `config.py` | `config.json` local do agente (tokens API↔agente, `consoles`, prazos). |
| `chiaki.py`, `winutil.py`, `gamepad.py`, `media.py` | Caminho chiaki-ng (legado). |

### pyremoteplay incorporada (`locaplay/agent/pyremoteplay/`)
`device.py` (RPDevice: status, wakeup, `standby`, sessão), `session.py` (sessão Remote Play sobre **TCP** + ctrl,
`_send_standby`/`async_standby`), `stream.py`/`stream_packets.py` (Takion sobre UDP), `register.py` (registro com PIN na
LAN), `oauth.py` (login PSN simples), `crypt.py`, `controller.py`, `receiver/`.

### Backend (`locaplay/backend/app/`, FastAPI + Postgres/psycopg, migrações SQL em `backend/migrations/`)
- Tabelas relevantes: `console_agents`, `consoles`, `console_connection_configs` (método, `network_route`
  `lan|internet_psn|internet_port_forward` — migração 008, `console_identifier`, resolução/fps/codec/bitrate,
  validações por canal), `console_connection_tests`, `remote_play_pairings`, `console_game_assignments`
  (console↔jogo por período, sem sobreposição), `reservations`, `game_sessions`, `session_input_tokens`.
- `gamebridge/contract.py` (contrato `ConsoleStreamingAdapter`), `gamebridge/agent_client.py` (adaptadores HTTP para o
  agente; métodos `remote_play_chiaki` e `remote_play_direct`), `gamebridge/registry.py`.
- `services/preparation.py` (prepara o console antes da reserva: acordar + abrir jogo; nunca mexe em console com sessão
  ativa), `services/sessions.py` (`join`, `webrtc_offer`, `send_input`, `end_session`, `admin_terminate`),
  `routers/admin.py` (cadastro de consoles/conexão e testes do painel; o teste de conexão devolve `in_progress`).

### Frontend (`locaplay/frontend/`, Next.js)
- `src/components/admin/Consoles.tsx` (cadastro de console, método, rota de rede, testes, publicar),
  `src/components/ConsoleVideo.tsx` (player WebRTC), `KeyBindings.tsx`/`InputTester.tsx` (controles do jogador).

### Referência do protocolo PSN (portar, não executar) — `chiaki-ng-main/`
| Arquivo | O que tem |
|---|---|
| `lib/src/remote/holepunch.c` (~6,3 mil linhas), `lib/include/chiaki/remote/holepunch.h` | Lista de consoles da conta (`chiaki_holepunch_list_devices`), criação/início de sessão no Session Manager da Sony, WebSocket de notificações push, oferta/resposta de candidatos, STUN, adivinhação de portas, UPnP, furo UDP para as conexões **ctrl** e **data**. |
| `lib/src/remote/stun.h` | Cliente STUN (endereço externo; lista de servidores). |
| `lib/src/remote/rudp.c`, `rudpsendbuffer.c`, `include/chiaki/remote/rudp.h` | **RUDP**: camada confiável sobre UDP usada nas conexões remotas para regist/session/ctrl (no lugar do TCP da LAN). |
| `lib/src/session.c` | Fluxo da sessão; trechos `if(session->rudp)` mostram o que muda pela PSN (regist automático via PSN, session request sobre RUDP, ctrl sobre RUDP, troca para o socket "data" furado). |
| `lib/src/regist.c`, `lib/src/ctrl.c` | Registro e ctrl (inclui variante RUDP). |
| `gui/src/psntoken.cpp`, `gui/src/psnaccountid.cpp`, `gui/include/psntoken.h` | OAuth da PSN: troca do código do redirect por tokens, renovação com refresh token, escopos (`psn:clientapp referenceDataService:countryConfig.read pushNotification:webSocket.desktop.connect sessionManager:remotePlaySession.system.update`, redirect `https://remoteplay.dl.playstation.net/remoteplay/redirect`), account-id. |
| `gui/src/qmlbackend.cpp` | Como a GUI usa tudo: lista de hosts PSN (PS5 pelo nome; **PS4 aparece só como "Main PS4 Console"**, o console principal da conta), reconexão, `PSN_INTERNET_WAIT_SECONDS`. |

## 4. Fatos de campo já medidos (não ignore)

Medidos com PS4 real em outra casa, via chiaki-ng, nesta máquina (logs em `%APPDATA%\Chiaki\Chiaki\log`):

1. **PS4 pela PSN só é alcançável se for o console principal ("Main PS4 Console") da conta.** Logo: **uma conta PSN por
   PS4** acessado pela internet. PS5: uma conta enxerga vários (campo `remoteplay_enabled` na lista de dispositivos).
2. **Com o console em repouso, a 1ª tentativa pela PSN sempre falha** (`Timed out waiting for holepunch session start
   notifications` após ~30 s): a própria tentativa acorda o console, que demora mais que o prazo. A 2ª tentativa conecta.
   → No seu código: **não copie o prazo fixo**; aguarde a notificação de início por até ~90 s quando o console estiver
   acordando, ou faça a nova tentativa automática.
3. Reabrir uma sessão PSN logo após a falha dá `Holepunch session was deleted on PSN server` / `Failed to create
   session`: **espere ~15 s** (ou apague explicitamente a sessão anterior no Session Manager) antes de recriar.
4. Servidores STUN da lista do chiaki-ng às vezes não respondem (`error 10060`): tente vários, em paralelo, com prazo curto.
5. PS4 comum transmite no máximo 720p (1080p só PS4 Pro); `pad info with size 0x7` é aviso inofensivo no PS4.
6. Após acordar do repouso, o PS4 abre na **tela inicial** com o jogo suspenso: o roteiro de abertura do jogo
   (`games.<slug>` = lista de botões) precisa cobrir isso (ex.: `["wait:4", "cross"]` retoma o primeiro bloco).

## 5. Arquitetura alvo

```
Navegador do jogador ──WebRTC (vídeo H.264 repassado + áudio Opus + DataChannel de controle)──┐
Painel admin ──HTTPS──> API LocaPlay ──HTTPS (token)──> ConsoleAgent (1 processo Python por PC)
                                                         ├─ PsnAccountStore (N contas, tokens cifrados, renovação)
                                                         ├─ SessionManager
                                                         │    ├─ RemotePlaySession testeps4 (conta teste01, rota psn|lan)
                                                         │    └─ RemotePlaySession testeps5 (conta teste02, rota psn|lan)
                                                         │         cada uma: asyncio task própria + sockets próprios +
                                                         │         controle próprio + trilhas WebRTC próprias
                                                         └─ PowerManager (acordar ao conectar / repouso ao sair)
```

### 5.1 Pacote novo `locaplay/agent/remoteplay/` (AGPL-3.0)
- `psn/oauth.py` — login (gera URL de login da Sony; recebe a URL de redirect colada pelo admin; troca por
  access/refresh token), renovação automática antes de expirar, account-id (base64/hex como o chiaki-ng espera),
  online-id. Sem navegador embutido.
- `psn/accounts.py` — `PsnAccountStore`: N contas, arquivo `data/psn_accounts.json` **cifrado**, um lock por conta,
  renovação concorrente segura (duas sessões da mesma conta não renovam ao mesmo tempo).
- `psn/devices.py` — lista consoles da conta (PS5 por nome/DUID; PS4 = console principal).
- `remote/stun.py`, `remote/upnp.py` (opcional, só se existir lib pura), `remote/holepunch.py` — porte do
  `holepunch.c`: criar sessão, WebSocket de notificações, ofertas, furo **ctrl** e **data**, encerramento limpo
  (sempre apagar a sessão na Sony ao terminar ou falhar).
- `remote/rudp.py` — porte do RUDP (envio confiável, retransmissão, ack, keep-alive) **assíncrono** (asyncio
  `DatagramProtocol`), um por sessão.
- `transport.py` — abstração `Transport` com duas implementações: `LanTransport` (TCP + UDP como a pyremoteplay já faz)
  e `PsnTransport` (RUDP para regist/session/ctrl + UDP furado para Takion). A pyremoteplay passa a receber o transporte
  em vez de abrir sockets por conta própria (mudança mínima em `session.py`/`stream.py`; mantenha a API pública).
- `session.py` — `RemotePlaySession`: conecta (rota `lan` ou `internet_psn`), expõe `video_packets()` (H.264/H.265
  **sem decodificar**), `audio_packets()` (Opus), `controller`, `standby()`, `stats()` (RTT, perda, fps, bitrate
  **reais**), eventos de estado (`connecting|streaming|reconnecting|ended|error` + motivo).

### 5.2 No ConsoleAgent
- Novo link `RemotePlayLink` em `links.py` (mesma interface de `DirectLink`) usando `remoteplay.session`.
  Novo método no banco: **`remote_play_native`** (rota `lan` ou `internet_psn`). `DirectLink` pode virar alias dele.
- `SessionManager`: no máximo **uma sessão por console**; sessões de consoles diferentes **totalmente independentes**
  (task, sockets, filas, controle, trilhas WebRTC). Exceção em uma sessão é capturada e só afeta aquela sessão.
- Limite por agente configurável (`max_sessions`), e recusa clara quando CPU/banda não comportam (medir, não chutar).
- `PowerManager` (seção 7).

## 6. Cadastro e vínculos (backend + painel)

### 6.1 Migração `013_contas_psn.sql`
```sql
create table if not exists public.psn_accounts (
  id            uuid primary key default gen_random_uuid(),
  agent_id      uuid not null references public.console_agents(id),
  label         text not null,                       -- "teste01" (nome interno)
  online_id     text,                                -- preenchido pelo agente após o login
  account_id    text,                                -- idem (não é segredo, mas não exibir ao jogador)
  status        text not null default 'pending' check (status in ('pending','linked','expired','error','disabled')),
  last_check_at timestamptz,
  last_error    text not null default '',
  created_by    uuid references public.users(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (agent_id, label)
);
-- console ↔ conta (PS4 pela internet: a conta precisa ter este PS4 como principal)
alter table public.console_connection_configs add column if not exists psn_account_id uuid references public.psn_accounts(id);
alter table public.console_connection_configs add column if not exists psn_device_uid text;       -- DUID (PS5) / marcador do PS4 principal
alter table public.console_connection_configs add column if not exists standby_after_session boolean not null default true;
alter table public.console_connection_configs add column if not exists keep_awake_minutes integer not null default 15
  check (keep_awake_minutes between 0 and 240);    -- não hiberna se houver reserva começando dentro deste prazo
```
Inclua `remote_play_native` no CHECK de `method` (mesmo padrão da migração 011). Regra: um PS4 com rota
`internet_psn` exige `psn_account_id`, e **duas configurações não podem apontar a mesma conta para PS4 diferentes**
(índice parcial ou validação na API com mensagem clara).

### 6.2 API (rotas admin, auditadas como as existentes)
- `GET/POST /admin/psn-accounts`, `PATCH/DELETE /admin/psn-accounts/{id}`.
- `POST /admin/psn-accounts/{id}/login/start` → agente devolve a URL de login da Sony.
- `POST /admin/psn-accounts/{id}/login/finish` `{redirect_url}` → agente troca por tokens, guarda cifrado, devolve
  online-id/account-id; a API marca `linked`.
- `POST /admin/psn-accounts/{id}/devices` → consoles visíveis por aquela conta (para o admin escolher).
- `POST /admin/consoles/{id}/pair` (já existe o fluxo de PIN): para `remote_play_native`, registro com PIN de 8 dígitos
  **na LAN ou pela PSN** (o chiaki-ng registra pela PSN: ver `regist.c` + holepunch), guardando a chave só no agente.
- Heartbeat do agente passa a informar por conta: `linked/expired` e expiração do token (sem o token).
- Endpoints novos no agente espelhando os acima: `/v1/psn/accounts/...` e `/v1/consoles/{id}/...` (mesma autenticação
  Bearer `api_to_agent_token` já usada).

### 6.3 Painel (`frontend/src/components/admin/`)
- Página **Contas PSN**: lista, criar (rótulo + agente), "Vincular" (abre a URL da Sony em nova aba; campo para colar a
  URL de redirect), estado, "Testar" (renova token e lista consoles), desativar.
- **Consoles** (`Consoles.tsx`): método "Remote Play nativo"; rota "Mesma rede" / "Outra rede (PSN)"; seleção da conta
  PSN e do console da conta (lista vinda de `/devices`); IP local opcional para rota LAN; "Hibernar ao fim da sessão" e
  "Manter acordado se houver reserva em X min"; roteiro de abertura do jogo editável por jogo.
- Testes do painel (já existem: heartbeat, pair, connection, video_audio, controls, latency) passam a funcionar para o
  novo método, com repetição automática enquanto `in_progress` (já implementado no painel).
- Indicação, por console, de quem está jogando agora e do estado da sessão (sem expor dados de outro jogador).

## 7. Energia: acordar ao conectar, repouso ao sair

1. **Acordar**: rota `lan` → pacote WAKEUP com a chave de registro (`discovery.py`) e esperar status "ligado";
   rota `internet_psn` → a criação da sessão PSN acorda o console; trate a primeira falha como esperada (seção 4.2) e
   reporte o andamento ("acordando o console pela PSN…").
2. **Preparação**: continua em `services/preparation.py` (X min antes da reserva). Ao ficar pronto, abrir o jogo pelo
   roteiro (`games.<slug>`), confirmar imagem real e **manter a sessão aberta** até o jogador entrar (sem fechar e
   reabrir — é o que mais custa tempo pela PSN).
3. **Repouso ao sair**: em `end_session`/`admin_terminate`/fim do tempo, o backend chama `disconnect` com
   `{standby: true|false}`. O agente: solta todos os botões, fecha a trilha WebRTC, envia **standby pelo ctrl**
   (`session._send_standby` / equivalente RUDP) e encerra a sessão PSN na Sony. Verifique o resultado (na LAN pela
   descoberta; na PSN pelo fim da sessão) e registre em `session_events`.
4. **Não hibernar** se: `standby_after_session=false`; houver reserva do mesmo console começando em menos de
   `keep_awake_minutes` (nesse caso manter conectado ou só desconectar); o admin estiver em teste.
5. Nunca hibernar/desconectar um console que tenha **outra** sessão ativa.

## 8. Isolamento ("um jogo não derruba o outro")

- Uma `RemotePlaySession` por console; cada uma com socket(s), RUDP, Takion, buffers e controle **próprios**. Nada
  global mutável compartilhado entre sessões (atenção a singletons da pyremoteplay, `Profiles.set_default_path`, caches de
  módulo — torne-os por sessão ou protegidos por lock).
- Renovação de token de uma conta não pode bloquear sessões de outras contas; duas sessões da mesma conta (PS5) usam
  a mesma renovação com lock.
- Entrada do jogador: o token de entrada (`session_input_tokens`) vale **só** para o console da sua sessão; comando
  para outro console = recusado e auditado (já existe a regra; mantenha no caminho novo).
- Queda de uma sessão: reconexão automática **daquela** sessão (até N tentativas, com backoff), mantendo o jogador na
  página com aviso "reconectando"; as outras seguem intactas.
- Teste automatizado obrigatório: duas sessões falsas no mesmo processo; matar/derrubar uma (exceção, timeout, perda
  total de pacotes) e provar que a outra continua entregando quadros e aceitando controle.

## 9. Latência mínima

1. **Vídeo sem recodificar**: repasse o H.264 que vem do console direto para o WebRTC. O aiortc aceita pacote já
   codificado: a trilha devolve `av.Packet` e o `RTCRtpSender` usa `H264Encoder.pack()` (ver
   `aiortc/rtcrtpsender.py` e `aiortc/codecs/h264.py`). Negocie H.264 *constrained baseline/high* compatível com o
   navegador. Para PS5 em H.265, prefira pedir H.264 ao console (o navegador nem sempre decodifica H.265 no WebRTC).
   Recodificação só como alternativa explícita (e medida).
2. **Áudio**: o console manda Opus; repasse sem decodificar se o aiortc permitir; senão decodifique/recodifique com
   blocos de 10–20 ms (já há código em `links.py`).
3. **Controle pelo DataChannel** do próprio WebRTC (não por HTTP via API): canal `unordered`, `maxRetransmits=0`,
   mensagens binárias pequenas com estado completo do controle + número de sequência; o agente aplica direto no
   `controller` da sessão. Mantenha a API HTTP de entrada só como reserva. A autorização do DataChannel usa o mesmo
   token de entrada da sessão.
4. Sem filas crescendo: quando atrasar, descarte quadros antigos até o próximo quadro-chave (peça IDR ao console se o
   protocolo permitir); nunca acumular segundos de atraso.
5. Pedir ao console **720p60** (PS4) / perfil configurado (PS5), bitrate do cadastro (`bitrate_kbps`), e expor ao
   navegador o modo "baixa latência" (jitter buffer mínimo: `playoutDelayHint`/`jitterBufferTarget` onde existir).
6. Medir e mostrar **valores reais**: RTT do Takion, perda, fps recebido, bitrate, e latência de entrada (carimbo de
   tempo no DataChannel ida/volta). Nada inventado (contrato `StreamMetrics`).
7. ICE: usar os STUN/TURN de `WEBRTC_ICE_SERVERS`/`ice_servers` já existentes; preferir caminho direto (host/srflx).

## 10. Fluxo completo do exemplo (deve funcionar ponta a ponta)

1. Admin → Contas PSN → cria **teste01** (agente "PC-01") → Vincular → login Sony → cola a URL → `linked`.
2. Admin → Consoles → cria **testeps4** (PS4) → método Remote Play nativo → rota "Outra rede (PSN)" → conta teste01 →
   console "Main PS4 Console" → Pareamento (PIN do PS4) → testes heartbeat/pair/connection/video_audio/controls passam →
   Publicar.
3. Idem **teste02** + **testeps5** (PS5, rota LAN ou PSN, console escolhido pelo nome na lista da conta).
4. Admin vincula **FIFA 26** ao testeps4 e **GTA VI** ao testeps5 (`console_game_assignments`) e configura o roteiro
   de abertura de cada jogo.
5. Jogador 01 reserva FIFA 26 → preparação acorda o testeps4 e abre o jogo → jogador entra e joga.
6. Ao mesmo tempo Jogador 02 reserva GTA VI → mesma coisa no testeps5.
7. Jogador 01 encerra → testeps4 recebe standby e hiberna; **testeps5 não é afetado** (sem engasgo mensurável).

## 11. Testes e critérios de aceite

Automatizados (sem hardware; dublês de rede como já feito em `agent/tests`):
- OAuth: troca de código, renovação, expiração, conta expirada → estado `expired` e mensagem clara.
- Holepunch: máquina de estados contra um "servidor PSN falso" (WebSocket + HTTP locais) e um "console falso" UDP:
  sucesso, timeout com console acordando + nova tentativa, sessão apagada na Sony, STUN fora do ar.
- RUDP: perda, duplicação e reordenação de pacotes (fuzz simples); retransmissão; keep-alive; fechamento.
- Isolamento (seção 8) e energia (seção 7: hiberna/não hiberna conforme regras).
- Backend: migração 013, rotas de contas PSN, validação "uma conta por PS4 pela internet", auditoria.
- Frontend: `npx tsc --noEmit` limpo.

Manuais (roteiro em `docs/CHECKLIST_INSTALACAO_CONSOLE.md` — atualize-o):
- Um PS4 pela PSN em outra casa: do repouso até imagem em < 2 min; standby ao sair confirmado.
- Duas sessões simultâneas (PS4 + PS5, ou dois PS4 com duas contas) no mesmo PC por 30 min, sem quedas cruzadas.
- Latência de entrada medida e registrada (meta: ≤ 1 quadro de acréscimo sobre o Remote Play oficial na mesma rede).

## 12. Entregas (faça em fases, cada uma testável; pare e reporte ao fim de cada fase)

1. **Contas PSN**: `psn/oauth.py`, `psn/accounts.py`, `psn/devices.py`, endpoints do agente e do backend, migração 013,
   página Contas PSN. Permitir **importar** os tokens já salvos pelo chiaki-ng deste PC (registro
   `HKCU\Software\Chiaki\Chiaki\settings`: `psn_refresh_token`, `psn_auth_token`, `psn_auth_token_expiry`,
   `psn_account_id`) como atalho de teste.
2. **Transporte PSN**: `stun.py`, `rudp.py`, `holepunch.py` + testes com servidor/console falsos.
3. **Sessão pela PSN**: `PsnTransport` na pyremoteplay; regist/session/ctrl sobre RUDP; Takion no socket furado;
   imagem real do PS4 em outra casa.
4. **Repasse de mídia e controle por DataChannel** (seção 9) para LAN e PSN.
5. **Energia + preparação + fim de sessão** (seção 7) e **isolamento** (seção 8) com duas sessões.
6. **Painel completo** e atualização dos documentos (`agent/README.md`, `docs/PS4_PASSO_A_PASSO.md`,
   `docs/CHECKLIST_INSTALACAO_CONSOLE.md`, `docs/MATRIZ_REQUISITOS.md`).

Em cada fase: liste arquivos alterados, como testar, o que foi validado com hardware real e o que **não** foi
(não declare pronto o que não foi verificado).

## 13. Riscos conhecidos (registre como decidir, não esconda)

- **Termos de uso da PSN**: aluguel de acesso por Remote Play pode violar os termos da Sony (risco de banimento das
  contas). Decisão de negócio do dono do produto; o código deve permitir desativar contas/consoles rapidamente.
- Mudanças do lado da Sony (endpoints/escopos do Session Manager) quebram a rota PSN sem aviso: isole tudo em
  `remoteplay/psn` e `remoteplay/remote`, com mensagens de erro que citem a etapa (login, lista, criar sessão,
  notificação, STUN, furo, RUDP, Takion).
- CGNAT duplo / NAT simétrico nos dois lados pode impedir o furo: detectar e informar ("rede do console não permite
  conexão direta"); o chiaki-ng usa adivinhação de portas e UPnP — porte também.
- Banda de subida na casa dos consoles (~5–15 Mbps por sessão) e CPU do PC do agente: medir e limitar sessões.
