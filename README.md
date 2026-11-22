# LocaPlay — locadora online de tempo de videogame

Plataforma web para alugar tempo em consoles físicos e jogar no navegador: catálogo, filas e reservas com
regras de janela, pagamentos (Mercado Pago), avisos por e-mail, sessão exclusiva com controle revogado no
servidor, transmissão pública para espectadores e painel administrativo completo. Banco: **PostgreSQL/Supabase**.

> **Estado honesto:** tudo que depende de console real, Chiaki, capturadora HDMI, credenciais do Mercado Pago,
> Google OAuth, provedor de e-mail ou canal Twitch/Kick está **implementado no código e bloqueado por dependência
> externa** até ser configurado/validado. Em desenvolvimento o sistema roda com **simulador** (console e pagamento),
> sempre identificado como simulado na interface. Veja `docs/MATRIZ_REQUISITOS.md`.

## Stack
- **Frontend:** Next.js 15 (App Router), React 19, TypeScript, CSS próprio (design system em `globals.css`), Lucide, fonte Poppins auto-hospedada.
- **Backend:** Python 3.11+, FastAPI, psycopg 3 (pool), Argon2id, TOTP, AES-GCM.
- **Banco:** PostgreSQL 15+ / Supabase (59 tabelas, constraints de exclusão de intervalos, auditoria por trigger, RLS).
- **GameBridge:** contrato versionado `ConsoleStreamingAdapter` com adaptadores `simulated`, `remote_play_chiaki`, `hdmi_capture`, `native_remote_play`.

```
locaplay/
├─ backend/
│  ├─ app/main.py              API (middleware de segurança, CSRF, erros)
│  ├─ app/routers/             auth, me (perfil/LGPD), catalog, play (reservas/sessões/webhooks), admin
│  ├─ app/services/            scheduling (motor de agenda), payments, sessions, notifications, auth, google_oauth...
│  ├─ app/gamebridge/          contrato + adaptadores (isolados do negócio)
│  ├─ app/worker.py            avisos 15/10/5/1, expiração de holds e sessões, no-show, heartbeat, e-mails
│  ├─ app/migrate.py, seed.py  migrations versionadas e dados base/demo
│  ├─ migrations/001..007      schema completo (Supabase)
│  └─ tests/                   62 testes (PostgreSQL real)
├─ frontend/
│  ├─ src/app/                 32 rotas (home, catálogo, jogo, checkout, sala de espera, jogar, perfil, admin…)
│  ├─ src/components/          shell, cards, admin
│  └─ e2e/                     testes Playwright + screenshots
└─ docs/                       Supabase, matriz de requisitos, auditoria inicial, evidencias/ (screenshots)
```

## Pré-requisitos
Node 20+, Python 3.11+, PostgreSQL 15+ (ou Docker, ou um projeto Supabase).

## Ambiente local em um comando (Windows/Linux)
```bash
python dev.py            # prepara o que faltar e sobe PostgreSQL (5433) + API (8000) + Next (3000); Ctrl+C encerra tudo
python dev.py --setup    # só prepara (banco, .venv, npm, .env, migrations, seed)
python dev.py --db       # sobe só o PostgreSQL (HeidiSQL/pgAdmin: 127.0.0.1:5433, usuário postgres, sem senha, banco locaplay)
python dev.py --demo     # recria os dados demonstrativos (SIMULADOS)
```
Usa um cluster PostgreSQL próprio de desenvolvimento (fora do repositório, `LOCAPLAY_PGDATA`), encerra processos esquecidos nas portas 8000/3000 e gera `backend/.env` na primeira vez (a senha do admin aparece no terminal).

## Banco de dados
**Supabase (recomendado):** siga `docs/SUPABASE.md` (cria o projeto, pega a connection string do *Session pooler* e roda as migrations).

**Local:** `docker compose up -d db` e use `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/locaplay`.

## Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env        # preencha APP_SECRET_KEY e DATABASE_URL
set -a; source .env; set +a # Windows PowerShell: carregue as variáveis manualmente
python -m app.migrate                       # aplica migrations
python -m app.seed --admin                  # papéis, plataformas, políticas, templates + superadmin (ADMIN_EMAIL/ADMIN_PASSWORD)
python -m app.seed --demo --demo-queue      # OPCIONAL: jogos/consoles SIMULADOS e fila demonstrativa
uvicorn app.main:app --reload --port 8000   # docs em http://localhost:8000/docs
```
O worker roda dentro da API (`RUN_WORKER=true`). Para escalar, rode `python -m app.worker` separado — há lock no banco para uma única execução.

## Frontend
```bash
cd frontend
npm install
cp .env.example .env.local      # API_URL=http://localhost:8000
npm run dev                     # http://localhost:3000
```
O navegador só fala com `/api/*` (mesma origem); o Next encaminha para a API. Cookies de sessão são HttpOnly.

**Primeiro acesso ao painel:** entre com o superadmin → Configurações → ative a autenticação em dois fatores → `/admin`.

## Testes
```bash
# Backend (usa um banco SEPARADO; ele é apagado e recriado)
cd backend && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/locaplay_test pytest -q
# Frontend
cd frontend && npm run lint && npm run build
# E2E (com API + frontend rodando e seed --demo --demo-queue)
cd frontend && npx playwright install chromium && E2E_ADMIN_EMAIL=... E2E_ADMIN_PASSWORD=... npm run e2e
# (sem download de navegador: CHROME_PATH=/caminho/do/chrome npm run e2e)
```

## Integrações e o que falta configurar
| Integração | Código | Para ativar |
|---|---|---|
| Mercado Pago (Pix/cartão, Checkout Pro) | criação de preferência, webhook com assinatura `x-signature` + antirreplay, consulta servidor-a-servidor, conciliação, estorno | `PAYMENT_PROVIDER=mercadopago`, `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET`; cadastrar a URL `{API_PUBLIC_URL}/webhooks/mercadopago` |
| E-mail | SMTP e Resend; fila com retry/backoff | `EMAIL_PROVIDER=smtp` ou `resend` + credenciais |
| Google OAuth | OIDC com PKCE, sem vínculo automático por e-mail | `GOOGLE_CLIENT_ID/SECRET` e URI `{FRONTEND_URL}/api/auth/google/callback` |
| Twitch/Kick (espectador) | embed oficial com estado offline | cadastrar canal no admin e liberar o domínio (`parent`) no player |
| Remote Play (Chiaki) / HDMI | adaptadores que delegam ao ConsoleAgent via HTTPS | desenvolver/instalar o ConsoleAgent no PC dos consoles, análise da licença AGPL-3.0 do Chiaki-NG, hardware e autorização |

## Limitações conhecidas
- Nenhum console real foi conectado; nenhum adaptador de hardware está "operacional".
- O ConsoleAgent (processo no PC ao lado dos consoles) não faz parte deste repositório; o protocolo que ele deve implementar está em `app/gamebridge/agent_client.py`.
- Sessão interativa: sem vídeo WebRTC real (simulador). Entradas de teclado/gamepad já passam pelo servidor com token efêmero.
- "Tempo real" das filas é por atualização periódica (5 s) — sem WebSocket.
- Upload de avatar grava em disco (`MEDIA_DIR`); em hospedagem sem disco persistente, trocar por Supabase Storage.
- Políticas (termos, privacidade, cancelamento) são **rascunhos** e precisam de revisão jurídica. Licenças de jogos/imagens/transmissão não foram obtidas; as artes atuais derivam da imagem de referência e devem ser substituídas.
- Plano gratuito do Supabase: 500 MB e pausa após 7 dias sem uso; amostras de telemetria são limpas após 7 dias.

## Próximas etapas
1. Criar o projeto Supabase e rodar migrations/seed (docs/SUPABASE.md).
2. Configurar e-mail transacional e Mercado Pago sandbox; testar Pix/cartão de teste.
3. Hospedar API (Render/Railway/Fly) e frontend (Vercel) com HTTPS e `COOKIE_SECURE=true`.
4. Desenvolver o ConsoleAgent e validar um PS4/PS5 próprio em rede privada (Fase A do adendo GameBridge).
5. WebRTC (STUN/TURN) entre navegador e agente; revisão jurídica e licenças antes de vender.
