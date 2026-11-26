"""Processa lotes de diagnóstico fora do ciclo de sessões."""
import logging
import threading
from datetime import timedelta

from psycopg.types.json import Jsonb

from .core import security, timeutil
from .core.context import actor_id_var
from .core.db import audit_event, one, tx
from .core.deps import Principal
from .core.errors import AppError, forbidden
from .core.permissions import action_key, is_allowed
from .routers.admin import PairIn, run_diagnostic_batch

log = logging.getLogger('locaplay.diagnostics')


def _claim():
    now = timeutil.now()
    with tx() as conn:
        conn.execute('''
            update console_diagnostic_runs set status=case when status='cancelling' then 'cancelled' else 'failed' end,
              pairing_code_enc=null, finished_at=%s,
              error='Execução interrompida. Inicie um novo diagnóstico.'
            where status in ('running','cancelling') and started_at<%s
        ''', (now, now - timedelta(minutes=20)))
        return one(conn, '''
            update console_diagnostic_runs set status='running', started_at=%s
            where id=(
                select j.id from console_diagnostic_runs j
                where j.status='queued' and not exists (
                    select 1 from game_sessions s where s.console_id=j.console_id and s.status in ('ready','active')
                )
                order by j.created_at limit 1 for update of j skip locked
            )
            returning id, console_id, requested_by, pairing_code_enc, test_type
        ''', (now,))


def _principal(conn, actor_id) -> Principal:
    row = one(conn, '''
        select u.*, coalesce(up.overrides,'{}'::jsonb) overrides,
          coalesce((select array_agg(r.code) from role_assignments ra join roles r on r.id=ra.role_id
                    where ra.user_id=u.id and ra.revoked_at is null),'{}') roles
        from users u left join user_permissions up on up.user_id=u.id
        where u.id=%s and u.deleted_at is null and u.status='active'
    ''', (actor_id,))
    if not row:
        raise forbidden()
    p = Principal(str(actor_id), '', row['username'], row['full_name'], row['email'], row['status'],
                  bool(row['email_verified_at']), roles=set(row['roles']), permissions=row['overrides'])
    if not p.has('admin') or not is_allowed(p.permissions, 'level:admin', 'menu:consoles',
                                          action_key('POST', '/admin/consoles/{cid}/diagnostic-runs')):
        raise forbidden()
    return p


def process_one() -> bool:
    job = _claim()
    if not job:
        return False
    actor = str(job['requested_by'])
    status, error = 'completed', None

    def save_result(result):
        with tx(actor) as conn:
            conn.execute('''
                update console_diagnostic_runs set results=results || %s
                where id=%s and status='running'
            ''', (Jsonb([result]), job['id']))

    try:
        with tx(actor) as conn:
            p = _principal(conn, job['requested_by'])
        body = PairIn(code=security.decrypt(job['pairing_code_enc'])) if job['pairing_code_enc'] else None
        token = actor_id_var.set(actor)
        try:
            run_diagnostic_batch(job['console_id'], body, p, save_result, test_type=job['test_type'], run_id=job['id'])
        finally:
            actor_id_var.reset(token)
    except AppError as exc:
        status, error = 'failed', exc.message
    except Exception:
        status, error = 'failed', 'A execução foi interrompida. Consulte os logs da aplicação.'
        log.exception('Falha no diagnóstico (execução=%s)', job['id'])
    with tx(actor) as conn:
        finished = one(conn, '''
            update console_diagnostic_runs set status=case when status='cancelling' then 'cancelled' else %s end,
                error=case when status='cancelling' then null else %s end, pairing_code_enc=null, finished_at=%s
            where id=%s and status in ('running','cancelling') returning status
        ''', (status, error, timeutil.now(), job['id']))
        if finished:
            audit_event(conn, 'console.diagnostics_finished', 'console_diagnostic_runs', job['id'],
                        details={'status': finished['status'], 'console_id': str(job['console_id'])})
    return True


class DiagnosticWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name='locaplay-diagnostics')
        self._stopping = threading.Event()

    def run(self):
        while not self._stopping.is_set():
            try:
                if process_one():
                    continue
            except Exception:
                log.exception('Falha na fila de diagnósticos.')
            self._stopping.wait(3)

    def stop(self):
        self._stopping.set()
