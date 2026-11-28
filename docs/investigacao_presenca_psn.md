# Investigação: confirmar o jogo aberto no PS4/PS5 — testes e resultados (28/11/2026)

Bancada: PS4 "PS4-118" (FW `system-version 14020001`), IP 192.168.1.122, na mesma rede do PC do agente.
Perfil PSN ativo no console: `macielthiago1`. Jogo de teste: Far Cry 5, `CUSA05904`.
Cofre do agente (DPAPI): 3 registros vinculados — 2× `macielthiago1`, 1× `thimy14`.
Login Sony atual (cadastro do proprietário): client Remote Play `ba495a24-818c-472b-b12d-ff231c1b5745`,
escopo `psn:clientapp referenceDataService:countryConfig.read pushNotification:webSocket.desktop.connect sessionManager:remotePlaySession.system.update`
(`agent/remoteplay/psn/oauth.py`).

## 1. Fluxo real do PS4 (anotado pelo usuário)

| Horário | Ação | Tela |
|---|---|---|
| 09:36 | botão PS (console em repouso) | ~40 s depois: "Seja bem-vindo", último perfil já selecionado |
| 09:36 | ✕ no perfil `macielthiago1` | menu principal com foco em "Novidades" |
| 09:37 | → | foco no último jogo jogado (Far Cry 5) |
| 09:37 | ✕ | jogo começa a abrir |
| 09:38 | — | carregando |
| 09:39 | — | menu do jogo |

## 2. Rede local — DDP (UDP 987) — FUNCIONA

Monitor a cada 5 s (`agent/consoleagent/discovery.py`, campos `running-app-titleid`/`running-app-name` do `raw`):

| Horário | DDP |
|---|---|
| 09:35:59 | `em repouso` (620) |
| 09:36:08 | sem resposta (transição) |
| 09:36:41 | `ligado` (200), sem app |
| 09:38:04 | `ligado`, `CUSA05904`, `Far Cry® 5` |
| 09:45:42 | `em repouso` |

Observações:
- O title ID aparece no início do carregamento (~1 min antes do menu): não significa "pronto para jogar".
- Algumas consultas não têm resposta (transições e aleatoriamente): não tratar uma resposta vazia como "desligado".
- Só funciona com o agente na mesma rede do console.

## 3. Internet — presença PSN — NÃO FUNCIONOU

Todas as consultas são só leitura, com o token do Remote Play já salvo no cofre (sem renovar/gravar nos testes 3.3–3.4).

| # | Requisição | Resultado |
|---|---|---|
| 3.1 | `GET m.np.playstation.com/api/userProfile/v1/internal/users/me/basicPresences?type=primary` | **403 Insufficient scope** |
| 3.2 | mesma rota com `account_id` do cofre no caminho | **400** `Bad Request (path: accountId_or_me)` — o cofre guarda o ID em Base64 de 8 bytes little-endian (`oauth.account_info`), não decimal |
| 3.3 | `GET us-prof.np.community.playstation.net/userProfile/v1/users/me/profile2?fields=onlineId,presences(@titleInfo,platform,onlineStatus,lastOnlineDate)` | **200**, mas `onlineStatus: offline` durante TODO o monitor de 12 min (repouso → perfil → Far Cry 5 no menu), para as 3 contas |
| 3.4 | `GET .../users/me/presences?fields=...` (mesmo host) | **404** |
| 3.5 | `GET m.np.playstation.com/api/gamelist/v2/users/me/titles` | **403** escopo insuficiente |
| 3.6 | `GET m.np.playstation.com/api/userProfile/v2/internal/users/basicPresences?accountIds=<decimal>&type=primary&platforms=PS4,PS5,MOBILE_APP,PSPC&withOwnGameTitleInfo=true` (rota do PSNAWP, script `docs/testar_presenca_psn.py`, ID decimal corrigido) | **403 Insufficient scope** para `macielthiago1` e `thimy14` |
| 3.7 | Login OAuth do Remote Play pedindo também `psn:mobile.v2.core` (script `docs/testar_escopo_mobile.py`) | Sony mostra **"Algo deu errado"** após o login; não redireciona |
| 3.8 | Controle: mesmo login sem `psn:mobile.v2.core` (`--controle`) | **funciona** (redireciona com `code`) → a Sony recusa o escopo mobile para o client Remote Play |

## 3b. Segunda rodada — profile2 com status "Online" — FUNCIONA (28/11/2026, 10:08–10:18)

Sonda `docs/testar_profile2_psn.py` (`me` e Online ID explícito, campos
`onlineId,primaryOnlineStatus,presences(@default,@titleInfo,platform,lastOnlineDate,hasBroadcastData)`),
mesmo token do Remote Play do cofre (registro `macielthiago1`), a cada 10 s, junto com o DDP local:

| Horário | Ação no PS4 | DDP (LAN) | profile2 (internet) — `me` e ID explícito iguais |
|---|---|---|---|
| 10:08:11 | repouso | sem resposta | 200, offline |
| 10:09:03 | "Seja bem-vindo" | ligado | 200, offline |
| 10:09:46 | perfil → Definir status online → **Online** | ligado | 200, **online, PS4** |
| 10:10:08 | abriu Far Cry 5 | `CUSA05904` | 200, online, PS4, **`CUSA05904_00`** |
| ~10:13 | Fase B: privacidade "Jogando agora" → qualquer pessoa (pediu novo login) | sem mudança | sem mudança |
| 10:17:30 | fechou o jogo | ligado, sem app | 200, online, PS4, **sem title ID** |

Conclusões (observado no console):
- A causa do "offline" anterior era o **status online do perfil no console** ("aparecer offline"). Com "Online", a rota legada
  profile2 entrega status, plataforma e title ID com o **token do Remote Play já existente** (sem escopo mobile nem NPSSO).
- Atraso medido: abertura e fechamento apareceram na **mesma leitura de 10 s** que o DDP (atraso ≤ intervalo de amostragem).
- A privacidade "Jogando agora" não alterou o resultado (já aparecia antes): é a própria conta consultando a si mesma.
- Title ID vem com sufixo (`CUSA05904_00`): normalizar para `CUSA05904`. Aparece no início do carregamento, não no menu do jogo.
- Pendente: PS5 (e jogo PS4 rodando no PS5), duas contas no mesmo console, conta usada em outro console ao mesmo tempo,
  comportamento ao entrar em repouso, estabilidade da rota legada (psn-api a descreve como legada).

## 4. Rede local — Second Screen PS4 (TCP 997) — BLOQUEADO

Porte do ps4-waker (MIT) em `agent/consoleagent/secondscreen.py`:
- DDP `WAKEUP`/`LAUNCH` (client-type `a`, auth-type `C`) → TCP 997 → ClientHello → ServerHello → Handshake (AES-128-CBC chave 16 zeros, IV = semente, chave RSA OAEP-SHA1) → Login: **funciona**; respostas decifradas corretamente.
- Login sem PIN → **20** (PIN necessário).
- Login com PIN válido (2 PINs diferentes, gerados em Configurações > Configurações de conexão do aplicativo móvel > Adicionar dispositivo) → **23** para todas as credenciais testadas: SHA-256 de um texto próprio; SHA-256 do account ID (bytes LE, bytes BE, decimal LE, decimal BE, hex).
- ps4-waker e pyps4-2ndscreen não geram a credencial: capturam o `user-credential` do app do celular fingindo ser um PS4 (dummy DDP). Código 23 não aparece em nenhum dos dois projetos.

## 5. Conclusões
- **Pela internet funciona** com o login atual: rota legada `profile2` (seção 3b), desde que o perfil do console esteja com status **Online**.
  basicPresences/gamelist continuam negados (403) e a Sony não concede o escopo mobile ao client Remote Play.
- Na rede local o DDP dá o mesmo sinal e serve de redundância/referência.
- NPSSO (client do app PlayStation) não é necessário.
- Solução: fluxo padrão automático (PS → ✕ perfil → → → ✕) + confirmação do title ID pela presença PSN (qualquer rede) e DDP
  (mesma rede) + espera de imagem estável antes de liberar o jogador. Imagem de referência vira só reforço opcional.
