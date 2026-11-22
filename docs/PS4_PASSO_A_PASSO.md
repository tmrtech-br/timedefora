# PS4 no LocaPlay — passo a passo para o primeiro teste real

> Objetivo: cadastrar um PS4 próprio, um jogo, reservar e **jogar pelo navegador**.
> Ambiente: rede privada (sua casa/escritório), console e conta PSN **seus**. Nada de venda real nesta fase.

## Onde estamos (honestamente)

| Parte | Situação |
|---|---|
| Site, reservas, fila, pagamento simulado, sala de espera, painel | Pronto |
| Cadastro de console com método **Remote Play — Chiaki**, testes e publicação | Pronto (tela e regras) |
| Protocolo API ↔ agente (`backend/app/gamebridge/agent_client.py`) | Pronto |
| **ConsoleAgent** (programa no PC ao lado do PS4: descobre, liga, transmite vídeo e recebe comandos) | **Não existe ainda — é o que vamos construir** |
| Vídeo do console no navegador (WebRTC) | Não existe ainda (hoje a tela de jogo é simulada) |

Sem o ConsoleAgent o painel não consegue validar vídeo/áudio/controle, e o sistema **corretamente** impede publicar o console.
Por isso o caminho tem 4 fases. A Fase 0 é só sua e pode começar já.

---

## Fase 0 — validar o Remote Play fora do LocaPlay (você, sem código)

Se o PS4 não funcionar bem no Chiaki-NG direto no PC, não vai funcionar no navegador. Esta fase mede o teto de qualidade.

### 0.1 Material
- PS4 (ou PS4 Pro) com conta PSN **sua**, logada.
- PC Windows na **mesma rede** do PS4 (é o PC que será o "agente"). Ideal: PS4 e PC **no cabo**.
- Controle DualShock 4 (USB) para testar no PC.

### 0.2 Configurar o PS4
1. **Configurações → Configurações de conexão de Uso Remoto → Ativar Uso Remoto**: ligado.
2. **Configurações → Gerenciamento de conta → Ativar como seu PS4 principal**: ativar.
3. **Configurações → Configurações de economia de energia → Definir recursos disponíveis no modo de repouso**:
   - *Permanecer conectado à Internet*: ligado
   - *Ativar ligar o PS4 pela rede*: ligado
4. **Configurações → Rede → Ver status da conexão**: anote o **endereço IP**.
5. No roteador, reserve esse IP para o PS4 (reserva DHCP / IP fixo), para ele não mudar.

### 0.3 Instalar e parear o Chiaki-NG no PC
1. Baixe o **chiaki-ng** do repositório oficial: https://github.com/streetpea/chiaki-ng (aba *Releases*, versão Windows).
2. Abra o chiaki-ng. O PS4 deve aparecer na lista (descoberta automática). Se não aparecer, adicione manualmente pelo IP anotado.
3. O chiaki-ng pede o **PSN Account ID** — use a opção de login PSN dentro do próprio chiaki-ng para obtê-lo.
4. No PS4: **Configurações → Configurações de conexão de Uso Remoto → Adicionar dispositivo**. Aparece um **código de 8 dígitos**; digite no chiaki-ng.
5. Clique no PS4 no chiaki-ng e jogue alguns minutos.

### 0.4 O que anotar e me mandar
- Funcionou? (sim/não, mensagem de erro se houver)
- Resolução/FPS configurados no chiaki-ng (comece com **720p / 60 fps**).
- Sensação de atraso do controle (nenhum / leve / ruim).
- Travadas ou artefatos na imagem.
- PS4 e PC estão no cabo ou Wi-Fi?
- Teste também: deixe o PS4 em **modo de repouso** e veja se o chiaki-ng consegue acordá-lo.

> **Importante (jurídico):** os termos da PlayStation tratam o Uso Remoto como uso pessoal. Alugar acesso a um console via Remote Play
> pode violar esses termos, e o Chiaki-NG é licenciado em **AGPL-3.0** (obriga a publicar o código de quem o distribui/modifica como serviço).
> Para testes internos com console e conta próprios não há problema prático; **antes de vender**, é preciso parecer jurídico.
> Alternativa sem Remote Play: placa de captura HDMI + controle emulado (método "Captura HDMI" já previsto no sistema).

---

## PS4 em outra rede (Remote Play pela internet)

O agente não precisa estar ao lado do PS4: no cadastro do console, campo **Rota de rede**:

| Rota | Quando usar | O que configurar |
|---|---|---|
| **Mesma rede do agente** (padrão) | Operação real | IP interno do PS4 ou descoberta na LAN |
| **Outra rede — via PSN** | Testes; PS4 na casa de outra pessoa | Agente logado na **mesma conta PSN** do PS4; identificação do console. Sem abrir portas. |
| **Outra rede — portas abertas** | Quando a via PSN não conectar | No roteador do PS4: IP fixo para o PS4 e redirecionar **TCP/UDP 9295–9304** para ele; IP público ou DDNS (ex.: No-IP, DuckDNS) no cadastro |

Cuidados nas rotas pela internet: mais atraso (o vídeo atravessa a internet duas vezes: PS4 → agente → jogador),
ligar o PS4 do repouso pode não funcionar (deixe *Permanecer conectado à Internet* ativo) e a qualidade depende da
**velocidade de upload** da internet onde o PS4 está (mínimo ~15 Mbps de upload para 720p/60).

Teste antes no chiaki-ng: com o PC fora da rede do PS4 (ex.: celular roteando 4G), use a conexão remota do chiaki-ng
(via PSN) ou adicione o console manualmente pelo IP público/DDNS.

## Fase 1 — ConsoleAgent v0 (eu desenvolvo; você instala no PC)

Programa Python (FastAPI) que roda no PC ao lado do PS4 e implementa o protocolo que a API já espera:

```
POST /v1/consoles/{id}/health | discover | pair | connect | test/video-audio | test/controls
     /stream/start | /stream/stop | /stream/status | /metrics | /input | /input/revoke | /disconnect
Authorization: Bearer <token API→agente>
```

Entregas da v0:
- Heartbeat do agente para a API (o painel mostra o agente **online**).
- **Descoberta real do PS4** na rede (protocolo de descoberta do Remote Play): estado *ligado* / *repouso* / *desligado*, nome e ID do console.
- **Acordar o PS4** do modo de repouso.
- Demais ações respondendo como **simuladas** (marcadas assim na interface), para exercitar o fluxo completo cadastro → testes → reserva → jogar.

Você vai: instalar Python no PC do agente, copiar a pasta do agente, colar os tokens gerados no painel e rodar um comando.

## Fase 2 — vídeo e controle reais

- Agente abre a sessão Remote Play (via chiaki-ng) e envia **vídeo + áudio ao navegador por WebRTC**.
- Comandos do navegador (controle/teclado) → agente → **controle virtual** que o chiaki-ng enxerga como DualShock 4.
- Métricas reais (FPS, bitrate, latência) na sala de jogo.
- Para acesso fora da sua rede: servidor TURN.

## Fase 3 — cadastrar e jogar pelo LocaPlay (você, no painel)

Quando o agente estiver rodando:

1. **Painel → Agentes e dispositivos → Novo agente**: nome, host do PC, endpoint (`https://IP-do-PC:porta`), localização.
   Clique em **Rotacionar tokens** na linha do agente e copie os dois tokens para o arquivo de configuração do agente (aparecem uma única vez).
2. **Painel → Consoles e conexão → Novo console**: plataforma **PS4**, nome (ex.: "PS4 nº 01").
3. No console criado → **Método de conexão**: *Remote Play — Chiaki (experimental)*; agente = o PC do passo 1;
   descoberta automática ou IP do PS4; resolução 720p, 60 fps, H.264. Salve com um motivo.
4. **Testes e diagnóstico**: rode *Descobrir console*, *Parear* (código de 8 dígitos do PS4), *Testar conexão*, *Testar imagem e áudio* e os demais testes da linha.
   Só com vídeo, áudio, controle e heartbeat aprovados o botão **Publicar** funciona.
5. **Painel → Jogos → Novo**: título, plataforma **PS4**, capa. Em **Licenciamento**, registre a licença como *autorizada*
   (para teste interno, use uma observação como "teste interno — console e conta próprios"). Depois **Publicar**.
6. **Painel → Vínculos e calendário → Novo vínculo**: PS4 nº 01 + o jogo, início/fim da janela.
7. **Painel → Preços e cupons**: confirme que existem pacotes (ex.: 10 min e 30 min).
8. No site como cliente: **Jogos → o jogo → Reservar** (fila) → pagamento **simulado** → **Sala de espera** → **Começar a jogar**.

---

## Próximo passo

1. Você: faça a **Fase 0** e me mande as anotações da seção 0.4.
2. Eu: começo a **Fase 1** (ConsoleAgent v0) em paralelo — não depende do resultado da Fase 0 para a parte de descoberta/heartbeat.
