# Validação do Remote Play nativo — Fase 1

Data da validação: 24/11/2026.

> **Atualização de 26/11/2026.** Este registro descreve o estado de 24/11. Depois dele, a rota `internet_psn` do
> `remote_play_native` passou a funcionar **para PS4** (`PsnLink` em `agent/consoleagent/links.py`, fluxo em
> `agent/remoteplay/psn/connection.py`): o HTTP 501 `psn_transport_pending` vale agora só para PS5. Validado com
> hardware real pelo dono do produto: conta PSN vinculada, PS4 na mesma rede do agente e PS4 movido para outra rede,
> com o jogador abrindo a sessão e jogando. Ainda sem validação real: PS4 que nunca esteve na rede do agente, NAT
> simétrico/CGNAT, sessões longas (mais de 1 h), duas sessões PSN simultâneas e o repouso ao fim da sessão.
> Correções da revisão de 26/11: novas tentativas também quando a negociação PSN falha, cofre PSN único por processo,
> falha temporária de renovação não expira mais a conta, qualidade/resolução do cadastro repassadas ao PS4, fila UDP
> maior, repouso ao fim da sessão (rota PSN), diagnóstico PSN fora do laço do WebRTC e cadastro de PS5 pela PSN recusado.

## Resumo executivo

Os 36 arquivos da atualização estão presentes. A conferência usou os 23 arquivos do overlay e as 13 transformações sobre os originais no backup. As divergências em relação ao pacote correspondem às correções e aos testes desta auditoria. O instalador permaneceu sem execução.

O backend, o frontend e o ConsoleAgent passaram nas verificações locais descritas abaixo. O modo `remote_play_native` em LAN delega para o mesmo `DirectLink` de `remote_play_direct`. O ConsoleAgent respondeu HTTP 501 com `psn_transport_pending` para o modo nativo via `internet_psn`. O backend também bloqueia a execução desse transporte. Nenhum console respondeu à descoberta PS4 por broadcast nesta execução.

## Resultados

| ID | Módulo | Cenário | Resultado | Evidência | Observação |
|---|---|---|---|---|---|
| INST-01 | Instalação | Manifesto e backup | Aprovado | 23 arquivos de overlay e 13 patches conferidos | Cópia de trabalho preservada |
| DB-01 | PostgreSQL 18 | Migrações 001–014 em banco descartável | Aprovado | `app.migrate --status` mostrou 013 e 014 como aplicadas | A 014 adiciona RLS sem modificar o checksum da 013 |
| DB-02 | Banco configurado | Estado da 013 e da 014 | Bloqueado | Conexão local expirou e o serviço Windows estava parado. A conta atual não conseguiu iniciá-lo | Estado das duas migrations nesse destino permanece desconhecido |
| API-01 | FastAPI | Suíte completa com banco descartável | Aprovado | 91 testes passaram | Inclui heartbeat em integração, sessões, controles e regressões antigas |
| API-02 | Contas PSN | Permissões, cadastro, consulta, rótulo inválido, duplicidade, expiração, desativação, exclusão | Aprovado | `backend/tests/test_psn_accounts.py` | PostgreSQL real, respostas do agente simuladas |
| DB-03 | Contas PSN | RLS habilitada e ausência de políticas públicas | Aprovado | Consulta aos catálogos `pg_class` e `pg_policy` no teste | Identidade real da Data API do Supabase e associação concorrente de PS4 seguem sem ensaio dedicado |
| PRO-01 | STUN e hole punching | Parse, transação, mapeamento, UDP e recusa sem prova válida | Aprovado | `test_protocol_components.py`, UDP em loopback | IP público e NAT em redes distintas ficaram sem comprovação |
| PRO-02 | SCE RUDP | Serialização, entradas inválidas, sequência, descarte da primeira transmissão, retransmissão, ACK e fechamento | Aprovado | `test_protocol_components.py`, UDP em loopback | Duplicação e reordenação na recepção e retransmissão esgotada ainda precisam de testes dedicados |
| PRO-04 | ConsoleAgent | Suíte completa | Aprovado | 55 testes passaram | Inclui WebRTC, protocolo, controles e PSN |
| PRO-03 | PSN | OAuth, erros HTTP, expiração, dispositivos PS5, criação e remoção da sessão | Aprovado | Respostas HTTP simuladas na suíte do agente | Os endpoints da Sony e a autenticação com conta real ficaram bloqueados |
| SEC-01 | Credenciais | Redação de token nos logs e cofre | Aprovado | Teste HTTPX com token sintético e ida e volta com DPAPI real do Windows | O fluxo LAN legado mantém ID e chaves de pareamento em JSON local, fora do cofre novo |
| WEB-01 | Next.js | Tipos e build de produção | Aprovado | `npm run lint` e `npm run build` | 28 páginas geradas no build |
| WEB-02 | Navegador | Home, admin, contas PSN, redirecionamento e operação da tela em 390 px | Aprovado | Três respostas HTTP 200, redirecionamentos sem sessão e teste Playwright | Sessão, MFA e operações da PSN simuladas no teste de navegador |
| AG-01 | ConsoleAgent | Configuração, inicialização, autenticação de comando e bloqueio PSN | Aprovado | HTTP 200 na raiz, 401 sem credencial e 501 autenticado para `internet_psn` | Testado com o processo local |
| AG-02 | ConsoleAgent | Heartbeat com a configuração da estação | Bloqueado | `ConnectError` ao acessar a API em `127.0.0.1:8000` | A integração equivalente passou com o backend de testes |
| MEDIA-01 | WebRTC | Negociação e vídeo direto no cliente de teste | Aprovado | Teste de regressão em `test_direct.py` | Fonte de teste, sem captura de console físico |
| MEDIA-02 | Controles | Validação de mensagens, descarte de sequência velha/duplicada, callback e revogação | Aprovado | Testes do agente e de sessão no backend | Entrega física, perda de comandos e dois consoles simultâneos ficaram bloqueados |
| HW-01 | PS4 LAN | Descoberta por broadcast | Reprovado | `Nenhum PS4 respondeu em broadcast` | A disposição e o estado do hardware precisam de confirmação local |
| HW-02 | PS4/PS5 reais | PIN, mídia, comandos físicos, expiração, falha de rede e isolamento | Bloqueado | Sem console alcançável nem conta de teste validada | Nenhuma métrica de hardware aferida |
| WAN-01 | PSN WAN | Sessão completa via internet | Bloqueado | HTTP 501 no ConsoleAgent | A negociação e o transporte ainda precisam de implementação |
| WEB-03 | Navegador | Jornada comercial de ponta a ponta com serviços e dados da estação | Não executado | API configurada indisponível | As suítes do backend e a verificação de tela usaram ambientes controlados |

## Correções

| Arquivo | Causa e impacto | Correção e evidência |
|---|---|---|
| `agent/consoleagent/links.py` | A consulta direta a `session.codec` interrompia a negociação quando a sessão não expunha esse atributo | O repasse H.264 é selecionado quando o codec está disponível. O teste existente voltou a receber vídeo pela trilha de fallback |
| `backend/requirements-dev.txt` | O ambiente sem plugin assíncrono acusava 12 falhas antes de executar os testes correspondentes | Dependência `pytest-asyncio` declarada e instalada no ambiente de desenvolvimento |
| `backend/migrations/014_proteger_contas_psn.sql` | A migration 013 criou a tabela pública de metadados sem RLS | Migration aditiva habilita RLS. Aplicação e catálogo confirmados no PostgreSQL isolado |
| `backend/app/routers/psn_accounts.py` | Resposta JSON não estruturada do agente causava falha interna. Era possível enviar rótulos em branco ou tentar concluir vínculo de conta desativada | Responde 502 para resposta inválida, valida o rótulo antes de gravar, verifica duplicidade antes de acionar o agente e bloqueia vínculo desativado. A suíte cobre os novos comportamentos |
| `agent/remoteplay/psn/oauth.py` e `agent/pyremoteplay/oauth.py` | O HTTPX registrava a URL de consulta de perfil com access token em INFO. O OAuth legado registrava o código em DEBUG | Filtro oculta o token nessa URL e o log legado foi removido. Um teste com transporte HTTP simulado verifica a redação |
| `agent/tests/test_psn_foundation.py`, `backend/tests/test_psn_accounts.py` e `frontend/e2e/psn-accounts.spec.ts` | Lacunas de regressão | Cobertura de redação nos logs, administração PSN, RLS e fluxo no navegador |

## Implementação e pendências

- **Implementado e testado localmente.** Rotas PSN administrativas com MFA e CSRF conforme a configuração do backend, cofre Windows, primitivos STUN/RUDP, callback de DataChannel e vídeo WebRTC com fonte de teste. A listagem API autoriza `operator` para consumo administrativo e os endpoints de alteração exigem `admin`. A navegação para a tela de contas é exibida a partir de `admin`.
- **Implementado, aguardando console real.** Descoberta unicast, registro por PIN, LAN com `DirectLink`, mídia e entrada física, passagem H.264 e retomada da conexão. `remote_play_direct` aceita LAN. `remote_play_native` reutiliza o caminho LAN. `native_remote_play` identifica o adaptador futuro GameBridge.
- **Parcialmente implementado.** O Session Manager já contém as chamadas HTTP de criação e remoção. O UDP consegue sondar candidatos com um verificador fornecido pelo chamador e o RUDP tem serialização, ACK, contadores e fila de retransmissão. O código de recepção ainda entrega os pacotes de controle à camada superior sem ordenar ou eliminar duplicatas. Campos de repouso e tempo acordado existem no painel e no payload do backend, sem execução no agente. O bypass de recodificação H.264 ainda chama o decodificador para alimentar o caminho de fallback e as checagens. O teto de bitrate ajusta a codificação local, enquanto o passthrough depende do fluxo de origem. O ajuste atual de bitrate do encoder é global no processo e precisa ser isolado antes de usar tetos diferentes em sessões simultâneas.
- **Ainda a implementar para WAN PSN.** Abrir e manter o canal de notificações push, obter o contexto e fazer a negociação com o Session Manager. Integrar oferta, resposta autenticada, seleção e confirmação dos pares UDP para controle e dados. Adaptar o início de sessão Remote Play para consumir os transportes negociados em vez de abrir uma conexão LAN. Implementar tratamento de duplicação e ordem onde o protocolo exigir, limpeza em falhas, reconexão, testes de NAT e interoperabilidade separada com PS4 e PS5. Preservar o bloqueio de `internet_psn` até existir prova desse caminho completo.
- **Desempenho.** DataChannel usa entrega não ordenada sem retransmissão e pode reduzir latência de entrada. Verificar perda de eventos de liberação, neutralização de comandos ao revogar e comportamento do caminho HTTP em falhas. Para H.264, medir tempo até o primeiro IDR, recuperação após perda e custo da decodificação paralela. Evitar mudanças de decodificação antes de medir o efeito nas checagens de imagem e no fallback.

## Roteiro Windows para PS4

### Preparação

1. Confirme o destino de `DATABASE_URL` no ambiente local e restaure a disponibilidade do PostgreSQL configurado. No PowerShell, inspecione o estado antes de aplicar as migrações. Execute a linha de aplicação após confirmar o destino e revisar as migrations pendentes. Use um banco descartável separado para `pytest` do backend, pois os testes removem e recriam schemas.

```powershell
Set-Location E:\LocadoraOnline\locaplay\backend
.\.venv\Scripts\python.exe -m app.migrate --status
.\.venv\Scripts\python.exe -m app.migrate
.\.venv\Scripts\python.exe -m app.migrate --status
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

2. Em outros terminais, inicie o frontend e o agente. Confira `http://localhost:8000/health`, a raiz do agente e o status online na página de agentes. Configure localmente os dois tokens do ConsoleAgent e entre no painel usando uma conta administrativa com MFA.

```powershell
Set-Location E:\LocadoraOnline\locaplay\frontend
npm run dev
```

```powershell
Set-Location E:\LocadoraOnline\locaplay\agent
..\backend\.venv\Scripts\python.exe -m consoleagent
```

### A. LAN

1. Conecte o PC do agente e o PS4 à mesma LAN. No PS4, abra **Configurações → Configurações de conexão do Uso remoto**, habilite **Uso remoto** e abra **Adicionar dispositivo** para exibir o PIN de pareamento. Mantenha a conta PSN correta selecionada. Confirme o IP nas configurações de rede do console. Se broadcast falhar, teste o IP diretamente. Use o código que identifica o console no painel. [Guia oficial do PlayStation](https://www.playstation.com/pt-br/support/games/remote-play-settings/)

```powershell
Set-Location E:\LocadoraOnline\locaplay\agent
$ps4Ip = Read-Host 'IP local do PS4'
$console = Read-Host 'Identificação do console no painel'
..\backend\.venv\Scripts\python.exe -m consoleagent --discover broadcast --platform PS4
..\backend\.venv\Scripts\python.exe -m consoleagent --discover $ps4Ip --platform PS4
..\backend\.venv\Scripts\python.exe -m consoleagent --psn-login
$pin = Read-Host 'PIN temporário exibido no PS4' -MaskInput
try {
    ..\backend\.venv\Scripts\python.exe -m consoleagent --pair $console --host $ps4Ip --platform PS4 --pin $pin
} finally {
    Remove-Variable -Name pin
}
..\backend\.venv\Scripts\python.exe -m consoleagent --check $console --mode direct --route lan --host $ps4Ip --platform PS4
```

Use PowerShell 7 para `-MaskInput`. No Windows PowerShell 5.1 use a ação de pareamento no painel para evitar digitar o PIN em texto visível no terminal. Faça a autenticação no navegador e cole a URL de retorno apenas no prompt local ou na tela apropriada. O login CLI cria o perfil usado no pareamento direto. A tela **Contas PSN** exercita outro fluxo, com tokens no cofre DPAPI.

2. No painel, configure o console com agente, IP, `remote_play_native` e rota LAN. Execute descoberta, conexão, imagem, áudio e controle. O teste CLI de controle requer `control_test_button` configurado com uma ação inofensiva na tela atual. Confira cada linha de resultado do `--check`, inclusive controles.
3. Abra uma sessão de teste pelo navegador e confirme vídeo em movimento e áudio audível. Pressione, sustente e solte botões com teclado, mouse conforme o mapeamento e controle USB/Bluetooth. Teste direcionais e extremos/volta ao centro dos analógicos. Faça uma ação com som e mudança visual para conferir sincronização.
4. Abra `chrome://webrtc-internals` antes da conexão. Registre o codec negociado, par ICE selecionado, tipo de candidato, `framesPerSecond`, delta de `bytesReceived`, RTT, jitter e pacotes perdidos. Marque horários de início, falha e retomada. Verifique TURN em uma rede em que o caminho relay seja selecionado. Guarde amostras sem tokens, PIN, URL de OAuth ou dump completo com credenciais de rede.
5. Encerre a sessão e confirme que os botões são liberados, mídia e controles daquela sessão deixam de funcionar e o console aparece disponível para a próxima sessão. Em duas sessões autorizadas, usando dois consoles físicos, envie comandos distintos em cada navegador e confira as duas imagens e saídas de áudio.

### B. Internet PSN

1. Anote a rede do PS4, a rede do agente e a do navegador. Para testar a rota nativa, coloque agente e PS4 em redes distintas, com o navegador capaz de alcançar o frontend. Um teste com agente na LAN do PS4 e navegador remoto mede a perna WebRTC.
2. Vincule uma conta PSN de teste pela tela administrativa. Registre o resultado da renovação do token e, com PS5 compatível e cadastrado na conta, da consulta de dispositivos. No estado atual, a resposta 501 do ConsoleAgent encerra o cenário nativo como bloqueado.
3. Quando a implementação estiver integrada, registre horários e resultados separados para push, oferta/aceitação, seleção de cada par UDP e início da sessão. Confirme vídeo e áudio reais, input recebido pelo console e retomada depois de cortar e restaurar a rede do agente. Repita com PS4 e PS5 em topologias documentadas.

### C. Falhas e segurança

1. Repita descoberta e conexão com o PS4 desligado e em repouso. Use um PIN incorreto e confirme rejeição antes de tentar um novo PIN válido.
2. Com conta de teste, recuse o login na Sony e revogue uma autorização para verificar indicação de expiração e novo vínculo. Confira que os logs e as respostas administrativas apresentam apenas metadados.
3. Durante a sessão, interrompa a rede do console depois de pressionar um botão e restaure a conexão. Faça também a desconexão do navegador. Confirme liberação dos comandos e registre o intervalo até recuperar mídia e controles.
4. Deixe o tempo de teste expirar. Envie ações pelo cliente antigo pelo caminho HTTP e pelo DataChannel, incluindo um pacote duplicado e outro atrasado em teste instrumentado do próprio cliente. Confira a revogação no agente e ausência de resposta física. Abra outro cliente com conta sem permissão e tente reservar/controlar o console com a primeira sessão ativa, verificando que o bloqueio persiste.

## Licenças

O Chiaki-ng utiliza AGPL-3.0 e o diretório `agent/remoteplay` declara AGPL-3.0-only. A biblioteca incorporada `agent/pyremoteplay` declara GPL-3.0. Em redistribuição, preserve avisos/licenças e providencie o código-fonte correspondente conforme a licença aplicável. A seção 13 da AGPL exige oferta do fonte correspondente aos usuários que interagem remotamente com a versão modificada abrangida. O uso comercial também requer revisão do alcance do copyleft na integração e dos direitos de uso de jogos, consoles e PSN para locação. [Chiaki-ng](https://github.com/chiaki-ng/chiaki-ng) · [Texto da AGPL](https://www.gnu.org/licenses/agpl-3.0.html) · [Texto da GPL](https://www.gnu.org/licenses/gpl-3.0.html)
