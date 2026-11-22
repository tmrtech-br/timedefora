"""Leitura de global_settings com valores padrão documentados."""
DEFAULTS = {
    'hold_minutes': 5,                        # expiração da reserva provisória
    'setup_minutes': 2,                       # preparação/limpeza entre jogadores
    'queue_lead_minutes': 0,                  # antecedência mínima do início em modo fila (0 = assim que o console estiver livre)
    'scheduled_lead_minutes': 10,             # antecedência mínima para horário fixo
    'booking_horizon_days': 14,               # até quantos dias à frente é possível reservar
    'max_pending_holds_per_user': 2,
    'max_future_reservations_per_user': 6,
    'cancel_full_refund_min_minutes_before': 120,
    'no_show_tolerance_minutes': 0,           # 0 = intervalo continua alocado até o fim (sem extensão)
    'reminder_minutes': [15, 10, 5, 1],
    'session_end_warnings_seconds': [600, 300, 60, 30],
    'sales_paused': False,
    'sales_paused_reason': '',
    'featured_window_days': 7,
    'featured_metric': 'minutes_played',      # minutes_played | sessions_sold | revenue
    'agent_heartbeat_timeout_seconds': 90,
    'support_hours_text': 'Atendimento por chamado no site. Horário de resposta: 9h às 21h (horário de Fortaleza).',
    # ---- Parâmetros liga/desliga (menu "Parâmetros" do painel). Aplicados no servidor, não só na interface.
    'disabled_platforms': [],                 # códigos de plataforma desligados (ex.: ["XBOX_SERIES"]): consoles e jogos somem da venda
    'signup_enabled': True,                   # novos cadastros (e-mail e Google)
    'google_login_enabled': True,             # botão "Entrar com Google"
    'queue_mode_enabled': True,               # compra em modo fila
    'scheduled_mode_enabled': True,           # compra em horário fixo
    'coupons_enabled': True,                  # aplicação de cupons no checkout
    'keyboard_mouse_enabled': True,           # jogar com teclado e mouse (controle sempre permitido)
    'public_streams_enabled': True,           # botão/links "Assistir ao vivo"
    'support_tickets_enabled': True,          # abertura de novos chamados (mensagens em chamados abertos continuam)
}

# Parâmetros expostos ao público (para a interface esconder o que estiver desligado).
PUBLIC_FLAGS = ('sales_paused', 'sales_paused_reason', 'signup_enabled', 'google_login_enabled', 'queue_mode_enabled',
                'scheduled_mode_enabled', 'coupons_enabled', 'keyboard_mouse_enabled', 'public_streams_enabled',
                'support_tickets_enabled', 'disabled_platforms')


def disabled_platforms(conn) -> list[str]:
    v = get_settings(conn).get('disabled_platforms') or []
    return [str(x) for x in v] if isinstance(v, list) else []


def require_enabled(conn, key: str, message: str) -> None:
    """Bloqueia a ação quando o parâmetro estiver desligado (409 feature_disabled)."""
    from ..core.errors import AppError
    if not get_settings(conn).get(key, True):
        raise AppError(409, 'feature_disabled', message)


def get_settings(conn) -> dict:
    out = dict(DEFAULTS)
    for r in conn.execute('select key, value from global_settings').fetchall():
        out[r['key']] = r['value']
    return out
