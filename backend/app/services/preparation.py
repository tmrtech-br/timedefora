"""Preparação do console antes da sessão (acordar o console e garantir o jogo da reserva aberto).

Regras:
- Só prepara com o console LIVRE (sem sessão ativa de outro jogador) — nunca atrapalha quem está jogando.
- Janela: a partir de `setup_minutes` (mínimo 1 min) antes do início.
- Falha definitiva se o adaptador não suporta a preparação, ou se o console não ficar pronto até a
  tolerância após o início (PREP_GRACE; maior na rota PSN, onde acordar o console do repouso leva minutos).
  Nesse caso a sessão NÃO começa: reserva → "Em resolução" (o cliente não perde tempo), incidente
  automático, cliente e equipe (operador/admin) notificados.
- O tempo do cliente só começa a contar quando o console fica pronto: se a preparação termina depois do
  início, o fim da reserva é empurrado pelo atraso (limitado pela próxima reserva do console).
- Resposta "simulada" de um agente real não conta como console pronto.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from ..core import timeutil
from ..core.db import insert, tx
from ..gamebridge import AdapterError, get_adapter
from . import notifications, scheduling
from .consoles import console_ref
from .settings_store import get_settings

log = logging.getLogger('locaplay.preparation')
PREP_GRACE = timedelta(seconds=90)
# Rota PSN: o agente faz até 3 tentativas (a 1ª quase sempre se perde enquanto o console sai do repouso).
PREP_GRACE_PSN = timedelta(minutes=5)
PERMANENT = {'not_implemented', 'not_configured', 'unsupported_platform'}
# Estados que ocupam o console (mesmos da restrição reservations_no_overlap).
BLOCKING = ('pending_payment', 'confirmed', 'active')


def lead(conn) -> timedelta:
    """Quanto antes do início a preparação começa (acordar + abrir o jogo)."""
    st = get_settings(conn)
    if st.get('prewake_enabled', True):
        return timedelta(minutes=max(1, int(st.get('prep_lead_minutes', 5) or 0)))
    return timedelta(minutes=max(1, int(st.get('setup_minutes', 2) or 0)))


def grace(conn, console_id) -> timedelta:
    """Tolerância após o início para o console ficar pronto (a mais longa entre as conhecidas, na dúvida)."""
    row = conn.execute('select network_route from console_connection_configs where console_id=%s', (console_id,)).fetchone()
    return PREP_GRACE_PSN if not row or row['network_route'] == 'internet_psn' else PREP_GRACE


def _start_clock(conn, r: dict, p: dict, ready_at) -> None:
    """Console pronto depois do início: empurra o fim da reserva pelo atraso, sem invadir a próxima reserva.

    Só compensa atraso do SISTEMA: a preparação precisa ter começado logo que possível (no início, ou no pagamento
    quando ele cai em cima do horário). Preparação que só começou quando o jogador chegou atrasado não estende nada.
    """
    late = ready_at - r['starts_at']
    if late <= timedelta(0):
        return
    due = max(r['starts_at'], r['confirmed_at'] or r['starts_at']) + timedelta(minutes=1)
    if p['created_at'] > due:
        return
    blocked = r['blocked_until'] + late
    cap = scheduling.push_queue_after(conn, r, blocked)
    if cap is not None:
        blocked = min(blocked, cap)
    ends = min(r['ends_at'] + late, blocked)
    if ends <= r['ends_at']:
        return
    conn.execute('update reservations set ends_at=%s, blocked_until=%s where id=%s', (ends, blocked, r['id']))
    log.info('reserva %s: console pronto %ss após o início; fim empurrado para %s',
             r['code'], int(late.total_seconds()), ends.isoformat())


def _row(conn, r, n) -> dict:
    p = conn.execute('select * from console_preparations where reservation_id=%s for update', (r['id'],)).fetchone()
    if p:
        return p
    # created_at pelo relógio do servidor da aplicação: marca quando a preparação começou (ver _start_clock).
    conn.execute('''insert into console_preparations(reservation_id, console_id, created_at) values (%s,%s,%s)
                    on conflict (reservation_id) do nothing''', (r['id'], r['console_id'], n))
    return conn.execute('select * from console_preparations where reservation_id=%s for update', (r['id'],)).fetchone()


def _console_busy(conn, r) -> bool:
    return bool(conn.execute("""select 1 from game_sessions where console_id=%s and status in ('ready','active')
                                and reservation_id<>%s""", (r['console_id'], r['id'])).fetchone())


def ensure(conn, r: dict, n=None) -> str:
    """Executa/atualiza a preparação da reserva. Retorna 'ready', 'pending' ou 'failed'."""
    n = n or timeutil.now()
    p = _row(conn, r, n)
    if p['status'] in ('ready', 'failed'):
        return p['status']
    if n < r['starts_at'] - lead(conn):
        return 'pending'
    limit = r['starts_at'] + grace(conn, r['console_id'])
    if _console_busy(conn, r):
        if n >= limit:
            _fail(conn, r, p, 'O console continuou ocupado pela sessão anterior além do horário de início.')
            return 'failed'
        return 'pending'
    ref = console_ref(conn, r['console_id'])
    adapter = get_adapter(ref.method)
    game = conn.execute('select id, slug, title from games where id=%s', (r['game_id'],)).fetchone() or {}
    attempts = p['attempts'] + 1
    try:
        res = adapter.prepare_console(ref, {'id': str(game.get('id', '')), 'slug': game.get('slug'), 'title': game.get('title')})
        if res.ok and (adapter.simulated or not res.simulated):
            conn.execute("""update console_preparations set status='ready', attempts=%s, simulated=%s, last_message=%s, ready_at=%s
                            where id=%s""", (attempts, adapter.simulated or res.simulated, res.message[:500], n, p['id']))
            _start_clock(conn, r, p, n)
            return 'ready'
        msg, permanent = (res.message or 'Console não ficou pronto.'), False
        if res.ok and res.simulated:
            msg, permanent = 'O agente respondeu de forma SIMULADA; um console real não pode ser liberado assim.', True
    except AdapterError as e:
        msg, permanent = e.message, e.code in PERMANENT
    conn.execute('update console_preparations set attempts=%s, last_message=%s where id=%s', (attempts, msg[:500], p['id']))
    if permanent or n >= limit:
        _fail(conn, r, p, msg)
        return 'failed'
    return 'pending'


def ensure_now(reservation_id) -> str:
    """Versão em transação própria (usada no clique em "Começar a jogar"): a falha fica gravada mesmo que a requisição seja recusada."""
    with tx() as conn:
        r = conn.execute('select * from reservations where id=%s for update', (reservation_id,)).fetchone()
        if not r:
            return 'failed'
        if r['status'] == 'active' or conn.execute('select 1 from game_sessions where reservation_id=%s', (r['id'],)).fetchone():
            return 'ready'          # sessão já liberada antes (reconexão)
        if r['status'] != 'confirmed':
            return 'failed'
        return ensure(conn, r)


def _fail(conn, r: dict, p: dict, message: str) -> None:
    n = timeutil.now()
    info = conn.execute("""select c.code, c.name console_name, g.title, u.username from consoles c, games g, users u
                           where c.id=%s and g.id=%s and u.id=%s""", (r['console_id'], r['game_id'], r['user_id'])).fetchone() or {}
    inc = insert(conn, 'service_incidents', {
        'console_id': r['console_id'], 'reservation_id': r['id'], 'kind': 'console_failure',
        'description': f"Console {info.get('code', '?')} não ficou pronto para a reserva {r['code']} "
                       f"({info.get('title', '?')}, {info.get('username', '?')}): {message}"[:1000]})
    conn.execute("update console_preparations set status='failed', failed_at=%s, last_message=%s, incident_id=%s where id=%s",
                 (n, message[:500], inc['id'], p['id']))
    conn.execute("""update reservations set status='needs_resolution', resolution_notes=%s where id=%s and status='confirmed'""",
                 ('O console não ficou pronto no horário por um problema técnico. Seu tempo não foi consumido: '
                  'a equipe vai remarcar ou reembolsar a reserva.', r['id']))
    scheduling.recompute_queue(conn, r['console_id'])
    notifications.notify(conn, str(r['user_id']), 'console_not_ready',
                         {'jogo': info.get('title', ''), 'codigo': r['code'], 'console': info.get('console_name', '')},
                         dedupe=f"console_not_ready:{r['id']}", link='/suporte')
    notify_staff(conn, 'staff_incident', {'incidente': f"Console {info.get('code', '?')} não ficou pronto",
                                          'detalhe': f"Reserva {r['code']} · {info.get('title', '?')} · cliente {info.get('username', '?')} · {message}"},
                 dedupe=f"staff_incident:{inc['id']}", link='/admin/sessoes')
    log.warning('preparação falhou: reserva %s console %s: %s', r['code'], r['console_id'], message)


def notify_staff(conn, event: str, variables: dict, dedupe: str, link: str) -> None:
    """Notifica operadores e administradores ativos (sino do site + e-mail)."""
    staff = conn.execute("""select distinct u.id from users u join role_assignments ra on ra.user_id=u.id and ra.revoked_at is null
                            join roles ro on ro.id=ra.role_id where ro.code in ('operator','admin','superadmin')
                              and u.status='active' and u.deleted_at is null""").fetchall()
    for s in staff:
        notifications.notify(conn, str(s['id']), event, variables, dedupe=f'{dedupe}:{s["id"]}', link=link)
