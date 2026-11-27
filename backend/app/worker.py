"""Worker de agendamento (roda dentro da API ou separado: `python -m app.worker`).

Usa advisory lock do PostgreSQL para que apenas UMA instância execute por vez.
Cada etapa é idempotente (dedupe de notificações, estados verificados com FOR UPDATE).
"""
import logging
import threading
import time
from datetime import timedelta

from .config import settings
from .core import timeutil
from .core.db import get_pool, insert, tx
from .diagnostic_worker import DiagnosticWorker
from .gamebridge import AdapterError, get_adapter
from .services import notifications, payments, preparation, scheduling, sessions
from .services.consoles import console_ref
from .services.settings_store import get_settings

log = logging.getLogger('locaplay.worker')
LOCK_KEY = 815_2026


def _remind_before_start(conn, n) -> int:
    count = 0
    rows = conn.execute(
        """select r.*, g.title, c.name console_name, coalesce(np.reminder_minutes, '{15,10,5,1}') mins
           from reservations r join games g on g.id=r.game_id join consoles c on c.id=r.console_id
           left join notification_preferences np on np.user_id=r.user_id
           where r.status='confirmed' and r.starts_at > %s and r.starts_at <= %s""",
        (n, n + timedelta(minutes=15, seconds=30))).fetchall()
    for r in rows:
        remaining = (r['starts_at'] - n).total_seconds() / 60
        thresholds = sorted(set(r['mins']) | {5})
        due = [m for m in thresholds if remaining <= m]
        if not due:
            continue
        m = min(due)  # envia só o aviso mais próximo (evita rajada de avisos atrasados)
        pos = conn.execute('select position from queue_entries where reservation_id=%s', (r['id'],)).fetchone()
        notifications.notify(conn, str(r['user_id']), f'turn_soon_{m}', {
            'minutos': m, 'jogo': r['title'], 'console': r['console_name'], 'duracao': f"{r['minutes']} minutos",
            'posicao': pos['position'] if pos else '—', 'inicio_previsto': timeutil.fmt_time(r['starts_at']),
            'fim_previsto': timeutil.fmt_time(r['ends_at'])},
            dedupe=f"soon:{r['id']}:{m}:{int(r['starts_at'].timestamp())}", link=f"/sessoes/{r['id']}", template='turn_soon')
        count += 1
    return count


def _prepare_upcoming(conn, n) -> int:
    """Prepara (acorda o console e abre o jogo) as reservas que começam em breve, uma por vez por console."""
    rows = conn.execute("""select r.* from reservations r
                           left join console_preparations p on p.reservation_id=r.id
                           where r.status='confirmed' and r.starts_at <= %s and (r.ends_at > %s or p.status='pending')
                             and coalesce(p.status, 'pending')='pending'
                           order by r.starts_at for update of r skip locked""", (n + preparation.lead(conn), n)).fetchall()
    done = 0
    for r in rows:
        try:
            with conn.transaction():
                preparation.ensure(conn, r, n)
            done += 1
        except Exception:  # uma reserva com erro não pode travar as outras
            log.exception('falha ao preparar reserva %s', r['id'])
    return done


def _start_due_sessions(conn, n) -> int:
    count = 0
    rows = conn.execute("""select r.*, g.title from reservations r join games g on g.id=r.game_id
                           left join console_preparations p on p.reservation_id=r.id
                           where r.status='confirmed' and r.starts_at <= %s and (r.ends_at > %s or p.status='pending')
                           order by r.starts_at for update of r skip locked""", (n, n)).fetchall()
    for r in rows:
        busy = conn.execute("select 1 from game_sessions where console_id=%s and status in ('ready','active') and reservation_id<>%s",
                            (r['console_id'], r['id'])).fetchone()
        if busy:
            continue
        if preparation.ensure(conn, r, n) != 'ready':
            continue   # ainda preparando, ou falhou (reserva já foi para resolução e a equipe notificada)
        s = sessions.prepare_session(conn, r)   # relê a reserva: o fim pode ter sido empurrado pelo atraso da preparação
        notifications.notify(conn, str(r['user_id']), 'turn_ready', {'jogo': r['title'], 'duracao': f"{r['minutes']} minutos",
                                                                     'fim_previsto': timeutil.fmt_time(s['contract_ends_at'])},
                             dedupe=f"ready:{r['id']}", link=f"/sessoes/{r['id']}")
        count += 1
    return count


def _end_expired_sessions(conn, n) -> int:
    rows = conn.execute("""select * from game_sessions where status in ('ready','active') and contract_ends_at <= %s
                           for update skip locked""", (n,)).fetchall()
    for s in rows:
        sessions.end_session(conn, s, 'time_up' if s['first_connected_at'] else 'no_show',
                             'expired' if s['first_connected_at'] else 'ended')
    # Reservas confirmadas cujo intervalo passou sem sessão (ausência)
    # (preparação ainda em andamento não é ausência: o tempo do cliente nem começou)
    no_shows = conn.execute("""update reservations r set status='no_show' where status='confirmed' and ends_at <= %s
                               and not exists (select 1 from console_preparations p where p.reservation_id=r.id and p.status='pending')
                               returning id, console_id""", (n,)).fetchall()
    for r in no_shows:
        scheduling.recompute_queue(conn, r['console_id'])
    return len(rows) + len(no_shows)


def _session_warnings(conn, n) -> None:
    st = get_settings(conn)
    rows = conn.execute("""select s.*, g.title from game_sessions s join reservations r on r.id=s.reservation_id
                           join games g on g.id=r.game_id where s.status='active' and s.contract_ends_at > %s
                           and s.contract_ends_at <= %s""", (n, n + timedelta(seconds=601))).fetchall()
    for s in rows:
        left = (s['contract_ends_at'] - n).total_seconds()
        due = [w for w in st['session_end_warnings_seconds'] if left <= w]
        if due:
            w = min(due)
            label = f'{w // 60} minuto(s)' if w >= 60 else f'{w} segundos'
            notifications.notify(conn, str(s['user_id']), 'session_ending', {'restante': label, 'jogo': s['title']},
                                 dedupe=f"ending:{s['id']}:{w}", link=f"/jogar/{s['id']}")


def _console_health(conn, n) -> None:
    st = get_settings(conn)
    timeout = timedelta(seconds=int(st['agent_heartbeat_timeout_seconds']))
    rows = conn.execute("""select c.id, c.status, c.code, cfg.method, ag.id agent_id, ag.is_simulated, ag.last_heartbeat_at
                           from consoles c join console_connection_configs cfg on cfg.console_id=c.id
                           left join console_agents ag on ag.id=cfg.agent_id
                           where c.deleted_at is null and cfg.validated_at is not null
                             and c.status in ('online','degraded','offline')""").fetchall()
    for c in rows:
        ok, simulated, err = False, False, None
        if c['method'] == 'simulated':
            ref = console_ref(conn, c['id'])
            try:
                res = get_adapter('simulated').health_check(ref)
                ok, simulated, err = res.ok, True, (None if res.ok else res.message)
            except AdapterError as e:
                err = e.message
            if c['agent_id']:
                conn.execute("update console_agents set last_heartbeat_at=%s, status='online' where id=%s and is_simulated", (n, c['agent_id']))
        else:
            ok = bool(c['last_heartbeat_at'] and n - c['last_heartbeat_at'] <= timeout)
            err = None if ok else 'Sem heartbeat do ConsoleAgent'
            if not ok and c['agent_id']:
                conn.execute("""update console_agents set status='offline'
                                 where id=%s and status<>'offline' and last_heartbeat_at < %s""",
                             (c['agent_id'], n - timeout))
        conn.execute("""insert into console_health_samples(console_id, agent_id, status, simulated, error) values (%s,%s,%s,%s,%s)""",
                     (c['id'], c['agent_id'], 'online' if ok else 'offline', simulated, err))
        new_status = 'online' if ok else 'offline'
        if new_status != c['status']:
            conn.execute('update consoles set status=%s where id=%s', (new_status, c['id']))
            if not ok and not conn.execute("select 1 from service_incidents where console_id=%s and resolved_at is null and kind='agent_offline'",
                                           (c['id'],)).fetchone():
                insert(conn, 'service_incidents', {'console_id': c['id'], 'kind': 'agent_offline',
                                                   'description': f"Console {c['code']} sem comunicação: {err}"})
                active = conn.execute("select s.user_id, s.id from game_sessions s where s.console_id=%s and s.status in ('ready','active')",
                                      (c['id'],)).fetchall()
                for a in active:
                    notifications.notify(conn, str(a['user_id']), 'console_failure', {'console': c['code']},
                                         dedupe=f"console_failure:{a['id']}", link='/suporte')
    # Limpeza de amostras antigas (plano gratuito do Supabase: 500 MB)
    conn.execute('delete from console_health_samples where checked_at < %s', (n - timedelta(days=7),))


def tick() -> dict:
    n = timeutil.now()
    out = {}
    with get_pool().connection() as lock_conn:
        got = lock_conn.execute('select pg_try_advisory_lock(%s) ok', (LOCK_KEY,)).fetchone()['ok']
        if not got:
            return {'skipped': 'outra instância executando'}
        try:
            with tx() as conn:
                out['holds_expired'] = scheduling.expire_stale_holds(conn)
            with tx() as conn:
                out['sessions_ended'] = _end_expired_sessions(conn, n)
            with tx() as conn:
                out['consoles_prepared'] = _prepare_upcoming(conn, n)
            with tx() as conn:
                out['sessions_started'] = _start_due_sessions(conn, n)
            with tx() as conn:
                consoles = conn.execute("""select distinct console_id from reservations where status in ('confirmed','active')
                                           or (status in ('completed','no_show','expired','cancelled') and updated_at > %s)
                                           union select console_id from queue_entries where status in ('waiting','next','playing')""",
                                        (n - timedelta(minutes=5),)).fetchall()
                for c in consoles:
                    scheduling.recompute_queue(conn, c['console_id'])
            with tx() as conn:
                out['reminders'] = _remind_before_start(conn, n)
                _session_warnings(conn, n)
            with tx() as conn:
                _console_health(conn, n)
            out['emails'] = notifications.process_deliveries()
            out['reconciled'] = payments.reconcile_pending()
        finally:
            lock_conn.execute('select pg_advisory_unlock(%s)', (LOCK_KEY,))
    return out


class WorkerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name='locaplay-worker')
        self._stop = threading.Event()
        self._diagnostics = DiagnosticWorker()

    def run(self):
        self._diagnostics.start()
        while not self._stop.is_set():
            try:
                tick()
            except Exception:  # noqa: BLE001 — o worker não pode morrer; erro vai para o log
                log.exception('Falha no ciclo do worker')
            self._stop.wait(settings.worker_interval_seconds)

    def stop(self):
        self._stop.set()
        self._diagnostics.stop()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    settings.validate()
    DiagnosticWorker().start()
    while True:
        log.info('tick %s', tick())
        time.sleep(settings.worker_interval_seconds)
