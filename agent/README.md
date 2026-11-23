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
| **Conectar** pela rota `internet_psn` (abre a interface do chiaki-ng e executa um roteiro de teclas) | 🧪 experimental · ⏳ calibrar o roteiro |
| **Controle virtual DS4** para o jogador (botão PS e touchpad bloqueados) | ✅ implementado · ⏳ validar |
| **Preparação** antes da sessão: acordar + conectar + roteiro para abrir o jogo | ✅ implementado · ⏳ validar |
| **Testes do painel**: imagem (captura real da janela), áudio (pico real) e controles (a tela precisa reagir) | ✅ implementado · ⏳ validar |
| Vídeo do console no navegador do jogador (WebRTC) | ⏳ próxima etapa |

Regras de honestidade: o agente **nunca simula**. "Pronto" só com imagem real capturada; o teste de imagem/áudio só
aprova com imagem **e** som medidos; o teste de controles só aprova se a tela mudar depois de apertar um botão.

## As 3 formas de ligar o agente ao console

A rota é escolhida no painel (**Consoles e conexão → rota de rede**):

| Rota | Quando usar | O que o agente faz |
|---|---|---|
| `lan` | PC do agente na **mesma casa** do console (modelo de produção, menor atraso) | acorda pelo IP local, `chiaki stream <apelido> <IP>` |
| `internet_port_forward` | PC em outra casa e **acesso ao roteador** do console | igual, usando IP público/DDNS. Liberar no roteador do console: **UDP 987, TCP 997, TCP/UDP 9295–9297** (PS4). Não funciona com CGNAT. |
| `internet_psn` | PC em outra casa, **sem mexer no roteador** | abre o chiaki-ng gráfico e aperta as teclas de `psn_gui_steps` para escolher o console em *Remote Connection via PSN*. Exige PS4 como **console principal** da conta PSN e o chiaki-ng logado na PSN. Frágil: se a tela do chiaki-ng mudar, recalibre. |

## Instalação (Windows)

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
       "psn_gui_steps": ["wait:3", "down", "enter"],
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
..\backend\.venv\Scripts\python -m consoleagent --check PS4-118 --route lan --host 192.168.0.20
..\backend\.venv\Scripts\python -m consoleagent --check PS4-118 --route internet_psn      # calibra psn_gui_steps
```
O `--check` faz o mesmo que o painel (acordar, conectar, imagem, áudio, controles) mostrando cada etapa.
Logs do chiaki-ng: `agent\logs\` (sem senhas).

## Rodar
Na raiz do projeto, `python dev.py` (sobe o agente quando `agent/config.json` existe), ou só o agente:
`..\backend\.venv\Scripts\python -m consoleagent`. Em ~30 s aparece **online** no painel.

Painel → Consoles e conexão → (console) → Testes: **Verificar heartbeat → Descobrir → Pareamento (confere o registro)
→ Conexão → Imagem e áudio → Controles**. "Conexão" leva até 1 min: se aparecer "em andamento", clique de novo.

## Produção
- Endpoint do agente em **HTTPS** (proxy reverso/túnel); a API recusa `http://` fora de desenvolvimento.
- `config.json` contém segredos: nunca versione nem compartilhe (está no `.gitignore`).
- Um chiaki-ng por console; o PC precisa ficar com sessão do Windows aberta (a janela do chiaki-ng é capturada).

## Testes
```powershell
cd E:\LocadoraOnline\locaplay\agent
..\backend\.venv\Scripts\python -m pytest -q tests
```
Integração real API ⇄ agente: `backend/tests/test_console_agent_integracao.py`.

## Licença e uso
O agente **executa** o chiaki-ng (AGPL-3.0) como programa separado, sem incorporar o código. Antes de uso comercial:
análise da licença e dos termos da PlayStation sobre Remote Play.
