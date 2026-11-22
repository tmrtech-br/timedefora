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
}


def get_settings(conn) -> dict:
    out = dict(DEFAULTS)
    for r in conn.execute('select key, value from global_settings').fetchall():
        out[r['key']] = r['value']
    return out
