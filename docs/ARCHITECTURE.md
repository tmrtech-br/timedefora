# Arquitetura e rastreabilidade

## Visão alvo
```
Navegador Next.js / React
  ├── Catálogo, conta, checkout, fila, player privado WebRTC, player público embed
  └── API HTTPS / WebSocket
        ├── FastAPI (auth, catálogo, agenda, reservas, pagamentos, RBAC)
        ├── PostgreSQL/Supabase (constraints, RLS, auditoria)
        ├── Redis / workers (avisos, dedupe, expiração e cronômetros)
        ├── Mercado Pago sandbox (webhook com assinatura e idempotência)
        ├── E-mail transacional (notificações)
        └── ConsoleAgent local (mTLS, secrets manager, heartbeat)
              ├── ConsoleStreamingAdapter: simulated [parcialmente implementado]
              ├── chiaki_web_remote_play [placeholder; avaliação legal]
              ├── native_remote_play [placeholder]
              └── hdmi_capture + canal de controle [placeholder]
                    └── PS4/PS5/console licenciado + captura
```

Controle administrativo, mídia/WebRTC e entradas do gamepad são planos separados. API de pagamentos não encaminha comando por tecla. Um token temporário por usuário/reserva/console será emitido e validado no agente, sendo revogado no término. Não existem credenciais PSN no frontend.

## Status funcional desta entrega
Legenda: `DEMO` = fluxo visual em memória no navegador, `API` = endpoint funcional separado, `PENDENTE` = projeto futuro, não chamar de pronto.

| Área do prompt | Status | Evidência / próxima etapa |
|---|---|---|
| 1 negócio, isolamento console/jogo | API parcial | tabelas separadas, agenda; falta operação real |
| 2 visual e responsividade | DEMO | interface baseada na referência e CSS mobile |
| 3 autenticação, Google, e-mail, MFA, LGPD | PENDENTE | login local fictício; implementar Supabase Auth |
| 4 dashboard | DEMO | hero, cards, aviso de simulação |
| 5 catálogo e detalhes | DEMO + API | busca, filtros, jogo demo; CRUD real ainda faltante |
| 6 Twitch/Kick spectator | PENDENTE | botão, indisponibilidade explícita |
| 7 console Remote Play/HDMI | DEMO | seleção por console, adaptação dinâmica de campos |
| 7 GameBridge Native e Chiaki | API parcial | interface abstrata, simulador, placeholders |
| 7 associação console-jogo | DEMO + API | relação por intervalo na API, bloqueio de conflito |
| 8 preços e pagamentos | DEMO | cards 10/30 min, sem cobrança; Mercado Pago não integrado |
| 9 agenda, holds, FIFO, concorrência | API parcial | reserva de intervalo, transação, conflito; falta fila e holds persistentes |
| 10 sala de espera / notificações | PENDENTE | projeto workers + e-mail |
| 11 exclusividade, no-show, cronômetro | DEMO + API parcial | sessão demo, início só na janela; falta expiração server-side automática |
| 12 cancelamento, reembolso | PENDENTE | regras e revisão legal |
| 13 player privado, controles e WebRTC | DEMO | seletor teclado/gamepad, tela simulada, sem vídeo real |
| 14 painel admin e RBAC | DEMO | cadastro/edit de consoles e jogos, sem RBAC real |
| 15 PostgreSQL e migrations | PARCIAL | migration fundacional, API SQLite para demonstração |
| 16 infraestrutura, Docker/CI | PENDENTE | separar envs, agente e pipelines |
| 17 privacidade e licenças | PENDENTE | bloqueio de cobrança/hardware; revisão jurídica |
| 18 notificações | PENDENTE | arquitetura workers |
| 19 testes | API parcial | testes pytest: intervalo/exclusão/console não validado |
| 20 plano em fases | DOCUMENTADO | evolução abaixo |
| 21 entrega em fases | FASE 1 PARCIAL | código executável, outras etapas pendentes |
| Adendo streaming substituível | API parcial | contrato e adapters, nada de hardware real |

## Sequência recomendada
1. **Fase 1**: esta entrega: interface responsiva, estados demo, esquema e contratos.
2. **Fase 2**: Supabase Auth, validação e-mail, Google OAuth, RBAC + MFA admin; substituir localStorage por API protegida.
3. **Fase 3**: schema PostgreSQL completo, console agents, dispositivos HDMI, pareamento guardando secrets, CRUD + agenda intervalar persistente, auditoria.
4. **Fase 4**: transações com constraints de exclusão, fila FIFO, hold/expiração, preparo, idempotência, concorrência e websockets.
5. **Fase 5**: checkout Mercado Pago sandbox, webhooks confirmados, compensação e reembolso.
6. **Fase 6**: notificação in-app/e-mail, jobs idempotentes, alertas, sala de espera e no-show.
7. **Fase 7**: simulador integrado end-to-end por API, input autorizados + WebRTC com testes reais de expiração/revogação.
8. **Fase 8**: stream público licenciado, monitoramento, testes E2E, hardening, deploy.
9. **Fase 9**: Remote Play/HDMI via hardware real e autorização comercial, começando PS4 privado.

## Invariantes de produção ainda a implementar
- `reserve` precisa conferir toda a agenda por console e aplicar constraints de não-sobreposição no PostgreSQL, não apenas por associação.
- Endpoints privados exigirão autenticação e autorização server-side. API demo expõe reservas sem login e só pode rodar localmente.
- `sendInput` deve exigir token efêmero por usuário/sessão, verificado no ConsoleAgent, não apenas a presença do session ID.
- Terminação não pode depender do browser; background workers e agente devem revogar ao expirar.
- Preço e disponibilidade só podem ser fixados pelo backend; simulação frontend não é venda.
- Mudança de adaptador com reservas/sessões ativas deve ser bloqueada e auditada.
- Sem prova de licença comercial, nunca habilitar venda/publicação de jogo.
