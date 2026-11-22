# LocaPlay — MVP visual + arquitetura GameBridge

Projeto inicial executável baseado no prompt unificado e na imagem de referência enviados pelo solicitante. **Esta é a Fase 1 / demonstração técnica**, não uma plataforma comercial pronta. Textos, fila, imagens e métricas do site são ilustrativos. Arte derivada da referência fornecida pelo usuário deve ser substituída por imagens licenciadas antes de publicação.

## Requisitos
- Node.js 20+ e npm, Python 3.11+

## Executar frontend
```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```
Abra http://localhost:3000. O site inclui catálogo pesquisável, favoritos, detalhes, pacotes demonstrativos, login local fictício, criação de reservas locais, sessões com contagem regressiva demonstrativa, interface de fila, perfil, pagamentos demonstrativos, suporte e painel admin com configuração de conexão por console. Os dados desta interface são persistidos no `localStorage` do navegador (apenas para testes). **O frontend não está conectado à API nesta primeira fase.**

## Executar API experimental separada
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
Documentação interativa: http://localhost:8000/docs; health: http://localhost:8000/health.
O protótipo de API usa SQLite local para funcionar sem contas externas. Há uma migration SQL inicial em `backend/migrations/` para PostgreSQL; **não está integrada à API nem representa o schema de produção completo**.

## Testar
```bash
cd backend
pytest -q
```
Para inspecionar tipos de frontend: `cd frontend && npm run lint`. Para criar build: `npm run build`.

## Estrutura
```
locaplay/
├─ frontend/ (Next.js, React, TypeScript, CSS responsivo)
│  ├─ src/app/ (layout, página, estilos)
│  ├─ src/components/Dashboard.tsx (interface navegável)
│  └─ public/assets/ (recortes da imagem fornecida)
├─ backend/
│  ├─ app/main.py (API de demonstração, agenda com transações SQLite)
│  ├─ app/adapters.py (contrato GameBridge, simulador e placeholders)
│  ├─ tests/ (cenários de agenda e publicação)
│  └─ migrations/ (fundação inicial PostgreSQL)
└─ docs/ARCHITECTURE.md (plano de implementação e checklist)
```

## Avisos importantes
- **Sem login real, sem autorização admin real, sem pagamentos, sem emissão de e-mail, sem WebRTC, sem conexão PS4/PS5, sem transmissão Twitch/Kick.** Não use o protótipo na internet para cobrar clientes.
- O painel administrador é deliberadamente visual, sem RBAC. Não exponha dados reais nele.
- O simulador local do frontend é didático e não cria tokens seguros nem aplica fim de sessão no servidor. O motor SQLite no backend, separado, implementa apenas alguns invariantes e precisa da Fase 4 para a segurança de produção.
- Nenhum jogo ou conteúdo comercial foi autorizado para exploração remota. Verifique licenças dos jogos, consoles, bibliotecas e direitos de transmissão/imagem, e conformidade LGPD e CDC antes de operar.
- Para integrar consoles, primeiro valide remotamente seu PS4 em ambiente privado; o modo Chiaki fica atrás de uma abstração e não está implementado.
