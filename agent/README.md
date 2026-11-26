# LocaPlay ConsoleAgent

Programa que roda no **PC ao lado do console** (ou num PC com acesso a ele) e faz a ponte entre a API LocaPlay e o PS4/PS5.

```
[Site/API LocaPlay] ⇄ HTTPS ⇄ [ConsoleAgent] ─┬─ chiaki-ng (processo separado) ⇄ PS4/PS5
                                               ├─ controle virtual DS4 (ViGEmBus) → chiaki-ng
                                               └─ testes reais: captura da janela + medidor de áudio do Windows
```

## O que a versão 0.2 (Parte 2) faz

| Função | Situação |
|---|---|
| Heartbeat, autenticação nos dois sentidos, descoberta do console (Parte 1) | ✅ validado com o PC real |
| **Acordar** o console em repouso (pacote WAKEUP do Remote Play, com a chave de registro) | ✅ implementado · ⏳ validar com o PS4-118 |
| **Conectar** pelo chiaki-ng — rotas `lan` e `internet_port_forward` (linha de comando) | ✅ implementado · ⏳ validar |
| **Conectar** pela rota `internet_psn` (abre a interface do chiaki-ng já mandando conectar ao console do cadastro; até `psn_connect_attempts` tentativas) | 🧪 experimental · ⏳ validar |
| **Controle virtual DS4** para o jogador (botão PS e touchpad bloqueados) | ✅ implementado · ⏳ validar |
| **Preparação** antes da sessão: acordar + conectar + roteiro para abrir o jogo | ✅ implementado · ⏳ validar |
| **Testes do painel**: imagem (captura real da janela), áudio (pico real) e controles (a tela precisa reagir) | ✅ implementado · ⏳ validar |
| **Vídeo e áudio no navegador do jogador (WebRTC)**: captura da janela do chiaki-ng (até 30 qps) + som do PC | ✅ testado com janela real e Edge real (VP8, 30 qps) · ⏳ validar com o PS4 |
| Analógicos do controle do jogador (zona morta, ~15 envios/s por eixo) | ✅ implementado |

Regras de honestidade: o agente **nunca simula**. "Pronto" só com imagem real capturada; o teste de imagem/áudio só
aprova com imagem **e** som medidos; o teste de controles só aprova se a tela mudar depois de apertar um botão.

## Remote Play DIRETO — vários consoles no mesmo PC (recomendado para a locadora)

Método **"Remote Play direto"** no painel. O agente fala o protocolo Remote Play com cada console, sem chiaki-ng:

```
                 ┌─ sessão PS4 nº1 ─► imagem/som ─► WebRTC ─► jogador 1
PC (agente) ─────┼─ sessão PS4 nº2 ─► imagem/som ─► WebRTC ─► jogador 2
                 └─ sessão PS5 nº3 ─► …
comando do jogador 2 ─► API ─► agente ─► sessão nº2 ─► só o console nº2
```
- **Sem janelas, sem monitor, sem controle virtual do Windows**: cada console tem o seu controle dentro da sessão.
- **Só rede local**: PC e consoles no mesmo roteador (cabo recomendado; fixe o IP de cada console no roteador).
- Biblioteca **pyremoteplay** incorporada em `agent/pyremoteplay` (GPL-3.0, cópia modificada — ver `NOTICE.md`).

Primeira configuração (uma vez por PC e uma vez por console):
### Diagnóstico do PS4 principal pela PSN

No painel **Contas PSN**, vincule e valide a conta no ConsoleAgent e clique em **Diagnosticar PS4 via PSN**. Para validar a rota pela internet, use redes distintas para o PS4 e o agente. Deixe o PS4 ligado ou em repouso com acesso à rede habilitado, ative o Uso remoto e configure-o como PS4 principal da conta.

O diagnóstico abre uma sessão temporária na Sony, solicita a entrada do PS4 principal e aguarda a notificação com o DUID. A resposta indica a etapa que falhou ou mostra o DUID recebido. O agente solicita o encerramento da sessão temporária ao terminar. Esse diagnóstico pode acordar o PS4 em repouso.

A troca de candidatos UDP, o pareamento remoto e a transmissão ainda precisam ser integrados ao transporte PSN. Os botões de conexão e pareamento pela rota nativa via internet continuam bloqueados.

### Configuração da conta e dos consoles

1. **Conta PSN** (uma vez por PC; a mesma conta logada nos consoles):
   `..\backend\.venv\Scripts\python -m consoleagent --psn-login` → abra o link, faça login, cole o endereço final.
2. **Registrar cada console** com o PIN (console LIGADO: Configurações → Configurações da Conexão de Uso Remoto →
   Adicionar Dispositivo): pelo painel (**Testes → Pareamento**, com o PIN no campo) ou no terminal:
   `python -m consoleagent --pair PS4-118 --host 192.168.0.20 --pin 12345678`.
3. **Testar**: `python -m consoleagent --check PS4-118 --host 192.168.0.20` (modo direto é o padrão) e os testes do painel.

O registro (chave e ID da conta, não a senha) fica em `agent/data/remoteplay_profiles.json` — segredo, fora do git.
A chave de registro salva também serve para **acordar** o console: não precisa preencher `regist_key` neste modo.

Status: compatibilidade atualizada e testada **sem console** (decodificação de vídeo/áudio, protocolo, criptografia,
controle, WebRTC). **Falta validar com PS4/PS5 reais.** PS5 com firmware recente tem erro conhecido de versão (a corrigir).

## As 3 rotas do modo chiaki-ng (console em outra rede, testes)

A rota é escolhida no painel (**Consoles e conexão → rota de rede**):

| Rota | Quando usar | O que o agente faz |
|---|---|---|
| `lan` | PC do agente na **mesma casa** do console (modelo de produção, menor atraso) | acorda pelo IP local, `chiaki stream <apelido> <IP>` |
| `internet_port_forward` | PC em outra casa e **acesso ao roteador** do console | igual, usando IP público/DDNS. Liberar no roteador do console: **UDP 987, TCP 997, TCP/UDP 9295–9297** (PS4). Não funciona com CGNAT. |
| `internet_psn` | PC em outra casa, **sem mexer no roteador** | **PS4:** a PSN só mostra o console principal da conta, com nome fixo *Main PS4 Console* (nunca o apelido), então a conexão automática do chiaki-ng é desligada nesta abertura e o agente escolhe o console na lista: espera a lista da PSN carregar, ↑ (dá a volta até o último item, que é a entrada da PSN) e Enter — padrão `["wait:12", "up", "enter"]`, sobreponível em `psn_gui_steps`. **PS5:** usa a conexão automática nativa pelo apelido. A configuração do usuário é restaurada logo depois. A transmissão só conta quando o log de sessão do chiaki-ng (`%APPDATA%\Chiaki\Chiaki\log`) mostra o vídeo chegando — o menu do chiaki-ng aberto **não** é conexão; sem sessão em 45 s a tentativa é encerrada. A 1ª tentativa costuma falhar com o console em repouso (ele acorda durante ela), por isso o agente tenta de novo (`psn_connect_attempts`, padrão 3, com 15 s de intervalo para a PSN apagar a sessão anterior). O painel repete o teste de conexão sozinho enquanto estiver em andamento. Exige PS4 como **console principal** da conta PSN e o chiaki-ng logado na PSN. |

**Janela oculta:** com `chiaki_hide_window` (padrão `true`) a janela do chiaki-ng é movida para fora da área visível (não é minimizada, para a captura continuar funcionando). Se a captura falhar com a janela fora da tela, o agente a traz de volta sozinho e registra o aviso no log.

## Instalação (Windows)

**Atalho:** na pasta `agent`, rode `powershell -ExecutionPolicy Bypass -File .\instalar.ps1`. Ele instala as dependências,
confere ViGEmBus, controle virtual, chiaki-ng e `config.json`, e lista **o que ainda falta**. Pode rodar quantas vezes quiser.

1. **chiaki-ng** instalado (padrão `C:\Program Files\chiaki-ng\chiaki.exe`) e o console **registrado nele**
   (no console: Configurações → Configurações da Conexão de Uso Remoto → Adicionar Dispositivo → PIN no chiaki-ng).
   Use como apelido no chiaki-ng a **identificação do console no painel** (ex.: `PS4-118`).
2. Dependências do agente (no venv do backend):
   ```powershell
   cd E:\LocadoraOnline\locaplay\agent
   ..\backend\.venv\Scripts\python -m pip install -r requirements.txt
   ```
   O `vgamepad` precisa do driver **ViGEmBus** (o instalador dele oferece; requer administrador). Sem ele o agente
   responde "controle virtual indisponível". **Desconecte controles físicos** do PC do agente: o chiaki-ng deve usar o virtual.
3. `config.json` (copie de `config.example.json`): tokens do painel e o bloco `consoles`:
   ```json
   "consoles": {
     "PS4-118": {
       "nickname": "PS4-118",
       "regist_key": "2ebf539d",
       "passcode": "",
       "games": { "slug-do-jogo": ["ps", "wait:2", "dpad_right", "cross"] }
     }
   }
   ```
   - `regist_key`: chave de registro do console no chiaki-ng (texto hexadecimal), usada **só para acordar** pelas rotas
     diretas. No chiaki-ng: Configurações → exportar configurações (arquivo .ini) → campo `rp_regist_key` do console.
     Segredo: fica só neste PC, nunca vai para a API.
   - `passcode`: senha de 4 dígitos de login do console, se houver.
   - `games`: roteiro do controle para abrir cada jogo a partir da tela inicial (`ps`, nomes de botão, `wait:N`, `hold:botão:N`).
     Sem roteiro, a preparação conecta e avisa para conferir o jogo na tela (`require_game_script: true` torna obrigatório).
   - `control_test_button`: botão inofensivo para o teste de controles (ex.: `dpad_right` no menu inicial).

## Diagnóstico no terminal (útil na casa do console)

```powershell
cd E:\LocadoraOnline\locaplay\agent
..\backend\.venv\Scripts\python -m consoleagent --list                                   # consoles registrados no chiaki-ng
..\backend\.venv\Scripts\python -m consoleagent --discover 192.168.0.20                   # procura o console
..\backend\.venv\Scripts\python -m consoleagent --psn-login                              # Remote Play direto: conta PSN (1×)
..\backend\.venv\Scripts\python -m consoleagent --pair PS4-118 --host 192.168.0.20 --pin 12345678
..\backend\.venv\Scripts\python -m consoleagent --check PS4-118 --host 192.168.0.20                  # modo direto
..\backend\.venv\Scripts\python -m consoleagent --check PS4-118 --mode chiaki --route lan --host 192.168.0.20
..\backend\.venv\Scripts\python -m consoleagent --check PS4-118 --mode chiaki --route internet_psn   # calibra psn_gui_steps
```
O `--check` faz o mesmo que o painel (acordar, conectar, imagem, áudio, controles) mostrando cada etapa.
Logs do chiaki-ng: `agent\logs\` (sem senhas).

## Rodar
Na raiz do projeto, `python dev.py` (sobe o agente quando `agent/config.json` existe), ou só o agente:
`..\backend\.venv\Scripts\python -m consoleagent`. Em ~30 s aparece **online** no painel.

Painel → Consoles e conexão → (console) → Testes: **Verificar heartbeat → Descobrir → Pareamento (confere o registro)
→ Conexão → Imagem e áudio → Controles**. "Conexão" leva até 1 min: se aparecer "em andamento", clique de novo.

## Vídeo no navegador (WebRTC)
- Navegador → API (`/sessions/{id}/webrtc`, só com o token de controle da sessão) → agente → resposta. O vídeo vai **direto**
  do agente para o navegador; os comandos continuam passando pela API (que valida cada um).
- **Remote Play direto:** a imagem e o som vêm da própria sessão de cada console (sem captura de tela, sem misturar sons).
- **chiaki-ng:** a janela precisa ficar **visível** (nem minimizada nem coberta) e o áudio é toda a saída de som do PC.
  `stream_audio: false` desliga o áudio.
- Rede: `ice_servers` (agente) e `WEBRTC_ICE_SERVERS` (API) iguais. Para jogadores em 4G/NAT restritivo, configure um **TURN**.
- Banda de subida do local do agente: ~3–6 Mbit/s por jogador em 720p.

## Vários consoles no mesmo PC
Use o **Remote Play direto** (acima). No modo chiaki-ng isso NÃO funciona: confirmado no código do chiaki-ng que cada
instância lê e soma **todos** os controles do PC — comandos de um jogador iriam para todos os consoles.
Limites que continuam valendo no modo direto:
1. **Processador:** cada console = decodificar o vídeo do console + codificar o vídeo do navegador. Estimativa: 4–6 consoles em 720p.
2. **Telas:** as janelas do chiaki-ng não podem se sobrepor (a captura é da região da tela). Ex.: 2 janelas de 1280×720 lado a lado num monitor/dummy HDMI 2560×1440.
3. **Hardware:** cada console = decodificar o Remote Play + codificar o vídeo do navegador. Estimativa: 2–3 consoles em 720p num PC com CPU de 6+ núcleos.
4. **Rede:** subida somada de todos os jogadores (ver acima). **PSN:** no PS4, a conexão via PSN só funciona com o console principal
   da conta — vários PS4 pela PSN exigem contas/perfis diferentes no chiaki-ng (`profile`).
Recomendação: validar com 1 PS4; depois testar o 2º console no mesmo PC antes de vender os dois.

## Produção
- Endpoint do agente em **HTTPS** (proxy reverso/túnel); a API recusa `http://` fora de desenvolvimento.
- `config.json` contém segredos: nunca versione nem compartilhe (está no `.gitignore`).
- O PC precisa ficar com a sessão do Windows aberta e sem descanso de tela/suspensão (a janela do chiaki-ng é capturada).

## Testes
```powershell
cd E:\LocadoraOnline\locaplay\agent
..\backend\.venv\Scripts\python -m pytest -q tests
```
Integração real API ⇄ agente: `backend/tests/test_console_agent_integracao.py`.

## Licença e uso
O agente **executa** o chiaki-ng (AGPL-3.0) como programa separado, sem incorporar o código. Antes de uso comercial:
análise da licença e dos termos da PlayStation sobre Remote Play.
