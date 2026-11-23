# LocaPlay ConsoleAgent

Programa que roda no **PC ao lado do console** e faz a ponte entre a API LocaPlay e o PS4/PS5.

```
[Site/API LocaPlay] ⇄ HTTPS ⇄ [ConsoleAgent] ⇄ [chiaki-ng] ⇄ [PS4/PS5]
```

## O que esta versão (0.1 — Parte 1) faz

| Função | Situação |
|---|---|
| Heartbeat: aparece **online** em Painel → Agentes e dispositivos | ✅ real |
| Autenticação nos dois sentidos (token agente→API e API→agente) | ✅ real |
| Teste "Verificar heartbeat" (saúde do agente + checa se o chiaki-ng está instalado) | ✅ real |
| Teste "Descobrir console": procura o PS4/PS5 pelo protocolo de descoberta do Remote Play e informa nome, estado (ligado / em repouso) e versão do sistema | ✅ real na rede local e por IP público com a porta UDP 987 (PS4) ou 9302 (PS5) redirecionada |
| Descoberta via PSN (console em outra rede, sem portas abertas) | ⏳ Parte 2 |
| Parear, conectar, vídeo/áudio, controles, iniciar/encerrar sessão | ⏳ Parte 2 — responde **"não disponível"** |

O agente **nunca finge**: o que não está implementado responde "não disponível", e a API não aceita resposta
simulada de um agente real para validar um console. Por isso o console **ainda não pode ser publicado** com este agente.

## Instalar e rodar (desenvolvimento, no mesmo PC da API)

1. **Painel → Agentes e dispositivos → Novo agente**
   - Nome: `PC do PS4`; Host: nome do PC; **Endpoint: `http://127.0.0.1:8765`**; Localização: livre.
   - Ao cadastrar, copie os **dois tokens** (aparecem uma única vez). Perdeu? Use **Rotacionar tokens**.
2. Crie a configuração:
   ```powershell
   cd E:\LocadoraOnline\locaplay\agent
   copy config.example.json config.json
   notepad config.json
   ```
   Cole `agent_token` (agente→API) e `api_to_agent_token` (API→agente). Confira `chiaki_path`.
3. Rode tudo junto: na raiz do projeto, `python dev.py` (sobe o agente automaticamente quando `agent/config.json` existe).
   Ou só o agente: `..\backend\.venv\Scripts\python -m consoleagent`.
4. Em ~30 s o agente aparece **online** no painel.
5. **Painel → Consoles e conexão → (PS4) → Método: Remote Play — Chiaki → Agente: PC do PS4** → escolha a rota de rede → Salvar.
6. **Testes e diagnóstico → Verificar heartbeat** e **Descobrir console**.

### Procurar um console sem configurar nada
```powershell
cd E:\LocadoraOnline\locaplay\agent
..\backend\.venv\Scripts\python -m consoleagent --discover broadcast        # rede local
..\backend\.venv\Scripts\python -m consoleagent --discover 192.168.0.20     # IP do console
```
Se o Windows perguntar sobre o firewall, permita o Python em **redes privadas**.

## Produção
- O endpoint do agente precisa ser **HTTPS** (ex.: proxy reverso ou túnel na frente do agente) — a API recusa `http://` fora de desenvolvimento.
- `config.json` contém segredos: nunca versione nem compartilhe (já está no `.gitignore`).
- Um agente por local; ele pode atender mais de um console daquela rede.

## Testes
```powershell
cd E:\LocadoraOnline\locaplay\agent
..\backend\.venv\Scripts\python -m pytest -q tests
```
Integração real API ⇄ agente: `backend/tests/test_console_agent_integracao.py`.

## Licença e uso
A Parte 2 vai controlar o **chiaki-ng (AGPL-3.0)**. Antes de uso comercial: análise da licença e dos termos da PlayStation sobre Remote Play.
