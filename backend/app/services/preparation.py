"""Preparação do console antes da sessão (acordar o console e garantir o jogo da reserva aberto).

Regras:
- Só prepara com o console LIVRE (sem sessão ativa de outro jogador) — nunca atrapalha quem está jogando.
- Janela: a partir de `setup_minutes` (mínimo 1 min) antes do início.
- Falha definitiva se o adaptador não suporta a preparação, ou se o console não ficar pronto até
  PREP_GRACE após o início. Nesse caso a sessão NÃO começa: reserva → "Em resolução" (o cliente não perde
  tempo), incidente automático, cliente e equipe (operador/admin) notificados.
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
PREP_GRACE = timedelta(seconds=60)
PERMANENT = {'not_implemented', 'not_configured', 'unsupported_platform'}


def lead(conn) -> timedelta:
    return timedelta(minutes=max(1, int(get_settings(conn).get('setup_minutes', 2) or 0)))


def _row(conn, r) -> dict:
    p = conn.execute('select * from console_preparations where reservation_id=%s for update', (r['id'],)).fetchone()
    if p:
        return p
    conn.execute('insert into console_preparations(reservation_id, console_id) values (%s,%s) on conflict (reservation_id) do nothing',
                 (r['id'], r['console_id']))
    return conn.execute('select * from console_preparations where reservation_id=%s for update', (r['id'],)).fetchone()


def _console_busy(conn, r) -> bool:
    return bool(conn.execute("""select 1 from game_sessions where console_id=%s and status in ('ready','active')
                                and reservation_id<>%s""", (r['console_id'], r['id'])).fetchone())


def ensure(conn, r: dict, n=None) -> str:
    """Executa/atualiza a preparação da reserva. Retorna 'ready', 'pending' ou 'failed'."""
    n = n or timeutil.now()
    p = _row(conn, r)
    if p['status'] in ('ready', 'failed'):
        return p['status']
    if n < r['starts_at'] - lead(conn):
        return 'pending'
    if _console_busy(conn, r):
        if n >= r['starts_at'] + PREP_GRACE:
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
            return 'ready'
        msg, permanent = (res.message or 'Console não ficou pronto.'), False
        if res.ok and res.simulated:
            msg, permanent = 'O agente respondeu de forma SIMULADA; um console real não pode ser liberado assim.', True
    except AdapterError as e:
        msg, permanent = e.message, e.code in PERMANENT
    conn.execute('update console_preparations set attempts=%s, last_message=%s where id=%s', (attempts, msg[:500], p['id']))
    if permanent or n >= r['starts_at'] + PREP_GRACE:
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
                         dedupe=f"console_not_ready:{r['id']}", link=f"/sessoes/{r['id']}")
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
