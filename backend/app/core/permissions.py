"""Permissões administrativas derivadas das rotas e limitadas pelo papel."""

ADMIN_MENUS = {
    'overview': ('', 'Visão geral', 'operator'),
    'games platforms': ('jogos', 'Jogos', 'operator'),
    'consoles connection-methods': ('consoles', 'Consoles e conexão', 'operator'),
    'console-onboardings': ('cadastro-console', 'Cadastro de console', 'superadmin'),
    'psn-accounts': ('contas-psn', 'Contas PSN', 'admin'),
    'agents capture-devices control-adapters': ('agentes', 'Agentes e dispositivos', 'operator'),
    'assignments blackouts calendar': ('agenda', 'Vínculos e calendário', 'operator'),
    'packages coupons': ('precos', 'Preços e cupons', 'operator'),
    'channels': ('transmissoes', 'Transmissões', 'operator'),
    'queues': ('filas', 'Filas', 'operator'),
    'reservations': ('reservas', 'Reservas', 'operator'),
    'sessions incidents': ('sessoes', 'Sessões e incidentes', 'operator'),
    'payments refunds webhooks reports cancellation-requests': ('financeiro', 'Financeiro e relatórios', 'admin'),
    'users': ('usuarios', 'Usuários e permissões', 'operator'),
    'notification-templates notification-deliveries': ('notificacoes', 'Notificações', 'admin'),
    'support': ('suporte', 'Suporte', 'operator'),
    'data-requests': ('lgpd', 'Solicitações LGPD', 'admin'),
    'audit': ('auditoria', 'Auditoria', 'admin'),
    'settings': ('parametros', 'Parâmetros', 'admin'),
    'policies': ('configuracoes', 'Configurações avançadas e políticas', 'admin'),
    'owner-reviews': ('aprovacoes', 'Aprovação de consoles', 'admin'),
    'owner-payouts': ('repasses', 'Repasses a proprietários', 'admin'),
}
RESOURCE_MENUS = {
    resource: section for resources, (section, _, _) in ADMIN_MENUS.items()
    for resource in resources.split()
}


def menu_key(section: str) -> str:
    return f'menu:{section or "overview"}'


def route_menu(path: str) -> str | None:
    parts = path.split('/')
    if len(parts) >= 3 and parts[1] == 'admin' and parts[2] in RESOURCE_MENUS:
        return menu_key(RESOURCE_MENUS[parts[2]])
    return None


def action_key(method: str, path: str) -> str:
    return f'action:{method}:{path}'


def is_allowed(overrides: dict[str, bool], *keys: str | None) -> bool:
    return all(overrides.get(key, True) for key in keys if key is not None)
