# Auditoria do projeto recebido (LocaPlay_MVP_Fase1, gerado pelo ChatGPT)

O commit `Baseline` do histórico git preserva o projeto original intacto.

## O que existia
- Frontend Next.js com um único componente (`Dashboard.tsx`) e dados em `localStorage`; login era só um apelido.
- API FastAPI separada, em SQLite, **não conectada ao frontend**; 2 testes.
- Migration PostgreSQL inicial com 11 tabelas, não utilizada.

## Bugs confirmados por teste (todos corrigidos na reescrita)
| # | Bug | Onde | Como foi resolvido |
|---|---|---|---|
| 1 | Sessão vencida sem `/end` travava o console para sempre ("Console already controlled") | main.py | Worker encerra sessões no servidor; índice único parcial; teste test_join_token_input_e_expiracao |
| 2 | API sem autenticação: listava todas as reservas, qualquer um encerrava qualquer sessão | main.py | Sessão por cookie, RBAC, verificação de dono (IDOR) |
| 3 | Duração arbitrária (7 min aceita), sem preço no servidor | main.py | Pacotes resolvidos no servidor |
| 4 | Jogo sem licença era vendido | main.py | Bloqueio por `commercial_license_status` |
| 5 | Console novo nunca podia ser validado; HDMI aceito sem capturadora/controle; jogo PS5 vinculável a Switch; sem edição/troca de método | main.py | Fluxo de testes, trigger de publicação, validação de plataforma, troca bloqueada |
| 6 | Horários comparados como texto | main.py | `timestamptz` e constraints de intervalo no PostgreSQL |
| 7 | Recarregar a página reiniciava a sessão com tempo cheio | Dashboard.tsx | Cronômetro e fim definidos pelo servidor |
| 8 | Aba "Vinculação" do admin não tinha efeito | Dashboard.tsx | Vínculos por janela no banco |
| 9 | "Assistir ao vivo" abria a compra; "Como funciona" e "Planos" quebrados; "Cadastrar" = "Entrar" | Dashboard.tsx | Rotas reais; E2E verifica cada botão |
| 10 | No celular o card de preços cobria "Assistir ao vivo" | globals.css | Layout responsivo; E2E mobile |
| 11 | Sem URLs (botão voltar saía do site) | Dashboard.tsx | 32 rotas do App Router |
| 12 | Modal sem Esc/role=dialog, favoritos sem rótulo | Dashboard.tsx | Componentes acessíveis |

## Bugs encontrados durante a reescrita (pelos testes)
- `console_ref` usava o id da configuração em vez do id do console (o agente real receberia o console errado).
- Colunas `tstzrange` quebravam a serialização JSON nas respostas do admin.
- O cooldown de reenvio de código comparava o relógio da aplicação com o `now()` do banco.
- O `TRUNCATE … CASCADE` de testes apagava os templates (ajustado no fixture).
- O player não enviava o header CSRF nos comandos de controle (todo comando era recusado).
- O componente `Field` incluía dica e erro no nome acessível do campo.
