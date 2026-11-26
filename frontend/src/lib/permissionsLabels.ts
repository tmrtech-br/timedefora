const RESOURCES: Record<string, [string, string]> = {
  users: ['usuários', 'usuário'], consoles: ['consoles', 'console'], 'psn-accounts': ['contas PSN', 'conta PSN'],
  games: ['jogos', 'jogo'], agents: ['agentes', 'agente'], payments: ['pagamentos', 'pagamento'],
  incidents: ['incidentes', 'incidente'], sessions: ['sessões', 'sessão'], reservations: ['reservas', 'reserva'],
  platforms: ['plataformas', 'plataforma'], assignments: ['vínculos', 'vínculo'], blackouts: ['bloqueios', 'bloqueio'],
  packages: ['pacotes', 'pacote'], coupons: ['cupons', 'cupom'], channels: ['transmissões', 'transmissão'],
  'capture-devices': ['capturadoras', 'capturadora'], 'control-adapters': ['adaptadores', 'adaptador'],
  'notification-templates': ['modelos de notificação', 'modelo de notificação'],
  'notification-deliveries': ['entregas de notificação', 'entrega de notificação'],
  'data-requests': ['solicitações LGPD', 'solicitação LGPD'], policies: ['políticas', 'política'],
  settings: ['parâmetros', 'parâmetro'], refunds: ['estornos', 'estorno'], webhooks: ['webhooks', 'webhook'],
  queues: ['filas', 'fila'], 'cancellation-requests': ['solicitações de cancelamento', 'solicitação de cancelamento'],
};
const LABELS: Record<string, string> = {
  'GET /admin/overview': 'Consultar visão geral',
  'GET /admin/calendar': 'Consultar calendário',
  'GET /admin/audit': 'Consultar auditoria',
  'GET /admin/connection-methods': 'Listar métodos de conexão',
  'GET /admin/reports/summary': 'Consultar resumo financeiro',
  'GET /admin/reports/export.csv': 'Exportar relatório CSV',
  'GET /admin/users/{uid}/permissions': 'Consultar permissões do usuário',
  'PUT /admin/users/{uid}/permissions': 'Alterar permissões do usuário',
  'POST /admin/users/{uid}/roles': 'Alterar papéis do usuário',
  'POST /admin/users/{uid}/suspension': 'Suspender ou reativar usuário',
  'POST /admin/consoles/{cid}/diagnostic-runs': 'Agendar diagnóstico de console',
  'GET /admin/consoles/{cid}/diagnostic-runs/{run_id}': 'Consultar diagnóstico de console',
  'POST /admin/consoles/{cid}/diagnostic-runs/{run_id}/cancel': 'Cancelar diagnóstico de console',
  'POST /admin/consoles/{cid}/tests/{test_type}': 'Executar teste de console',
  'DELETE /admin/consoles/{cid}/tests': 'Limpar histórico de diagnósticos',
  'POST /admin/consoles/{cid}/diagnostics/run-all': 'Executar todos os diagnósticos diretamente',
  'PUT /admin/consoles/{cid}/connection': 'Configurar conexão do console',
  'POST /admin/consoles/{cid}/connection/rollback/{change_id}': 'Restaurar configuração de conexão',
  'POST /admin/consoles/{cid}/publish': 'Publicar console',
  'POST /admin/consoles/{cid}/unpublish': 'Despublicar console',
  'POST /admin/consoles/{cid}/status': 'Alterar status do console',
  'PUT /admin/consoles/{cid}/hours': 'Definir horários operacionais do console',
  'POST /admin/psn-accounts/{account_id}/login/start': 'Iniciar vínculo PSN',
  'POST /admin/psn-accounts/{account_id}/login/finish': 'Concluir vínculo PSN',
  'POST /admin/psn-accounts/{account_id}/test': 'Testar autenticação PSN',
  'POST /admin/psn-accounts/{account_id}/devices': 'Consultar dispositivos na PSN',
  'POST /admin/psn-accounts/{account_id}/devices/ps4-lan': 'Buscar PS4 na rede local',
  'POST /admin/psn-accounts/{account_id}/diagnose/ps4-psn': 'Diagnosticar PS4 via PSN',
  'POST /admin/psn-accounts/{account_id}/import/chiaki': 'Importar credencial Chiaki',
  'GET /admin/psn-accounts/options': 'Consultar opções de contas PSN',
  'POST /admin/agents/{aid}/rotate-credentials': 'Rotacionar credenciais do agente',
  'POST /admin/payments/{pid}/refund': 'Reembolsar pagamento',
  'POST /admin/payments/{pid}/reconcile': 'Conciliar pagamento',
  'POST /admin/reservations/{rid}/cancel': 'Cancelar reserva',
  'POST /admin/reservations/{rid}/reschedule': 'Remarcar reserva',
  'POST /admin/sessions/{sid}/terminate': 'Encerrar sessão',
  'POST /admin/assignments/{aid}/cancel': 'Cancelar vínculo de jogo',
  'POST /admin/cancellation-requests/{crid}/decide': 'Decidir solicitação de cancelamento',
  'POST /admin/data-requests/{did}/resolve': 'Resolver solicitação LGPD',
  'POST /admin/notification-deliveries/{did}/retry': 'Reenviar notificação',
  'POST /admin/games/{gid}/license': 'Registrar licença comercial do jogo',
  'POST /admin/incidents/{iid}/resolve': 'Resolver incidente',
  'POST /admin/console-onboardings/{cid}/publish': 'Publicar cadastro de console',
  'PUT /admin/console-onboardings/{cid}/owner-agent': 'Autorizar agente do proprietário',
  'GET /admin/support/tickets': 'Listar chamados de suporte',
  'PATCH /admin/support/tickets/{tid}': 'Atualizar chamado de suporte',
};

export function permissionLabel(route: string): string {
  if (LABELS[route]) return LABELS[route];
  const match = /^(GET|POST|PATCH|PUT|DELETE) \/admin\/([^/]+)(\/\{[^/]+\})?$/.exec(route);
  if (!match || !RESOURCES[match[2]]) return route;
  const [, method, resource, id] = match;
  const [plural, singular] = RESOURCES[resource];
  if (method === 'GET') return id ? `Ver ${singular}` : `Listar ${plural}`;
  return `${({ POST: 'Cadastrar', PATCH: 'Editar', PUT: 'Editar', DELETE: 'Excluir' } as Record<string, string>)[method]} ${singular}`;
}
