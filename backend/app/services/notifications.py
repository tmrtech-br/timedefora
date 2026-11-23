"""Notificações in-app e e-mail: templates, preferências, deduplicação, fila de entrega com backoff."""
import html
import string
from datetime import timedelta

from psycopg.types.json import Jsonb

from ..config import settings
from ..core import timeutil
from ..core.db import get_pool
from .email_provider import EmailSendError, send_email

# Eventos cujo e-mail é transacional essencial (não depende de preferência opcional).
ESSENTIAL_EMAIL = {'verify_email', 'email_change', 'password_reset', 'password_changed', 'payment_approved',
                   'payment_rejected', 'hold_expired', 'turn_soon_5', 'turn_ready', 'reservation_cancelled',
                   'refund_completed', 'needs_resolution', 'console_failure', 'schedule_changed', 'new_login',
                   'console_not_ready', 'staff_incident'}
OPTIONAL_EMAIL_PREF = {'queue_changed': 'email_queue_updates', 'turn_soon_15': 'email_reminders',
                       'turn_soon_10': 'email_reminders', 'turn_soon_1': 'email_reminders'}
NO_EMAIL = {'session_ending', 'session_started', 'session_ended'}


class _SafeDict(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def render(template: str, variables: dict, escape: bool) -> str:
    vals = {k: (html.escape(str(v)) if escape else str(v)) for k, v in variables.items()}
    return string.Formatter().vformat(template, (), _SafeDict(vals))


def _template(conn, code: str, channel: str) -> dict | None:
    return conn.execute('select * from notification_templates where code=%s and channel=%s and active',
                        (code, channel)).fetchone()


def notify(conn, user_id: str, event: str, variables: dict, dedupe: str, link: str | None = None,
           template: str | None = None, email_to: str | None = None, in_app: bool = True, email: bool = True) -> None:
    """Enfileira notificação. Idempotente por dedupe (evento+entidade+canal)."""
    template = template or event
    user = conn.execute('select id, email, full_name, username, status from users where id=%s', (user_id,)).fetchone()
    if not user:
        return
    prefs = conn.execute('select * from notification_preferences where user_id=%s', (user_id,)).fetchone() or {}
    base = {'nome_usuario': user['username'], 'site': settings.frontend_url, **variables}
    if link:
        base['link'] = settings.frontend_url.rstrip('/') + link
    if in_app and prefs.get('in_app_enabled', True):
        t = _template(conn, template, 'in_app')
        if t:
            conn.execute(
                'insert into notifications(user_id, event_code, title, body, link, dedupe_key) values (%s,%s,%s,%s,%s,%s) '
                'on conflict (dedupe_key) do nothing',
                (user_id, event, render(t['subject'], base, False), render(t['body_text'], base, False), link, f'{dedupe}:in_app'))
    if not email or event in NO_EMAIL:
        return
    pref_col = OPTIONAL_EMAIL_PREF.get(event)
    if event not in ESSENTIAL_EMAIL and pref_col and not prefs.get(pref_col, True):
        return
    if _template(conn, template, 'email') is None:
        return
    conn.execute(
        'insert into notification_deliveries(user_id, channel, event_code, template_code, dedupe_key, to_address, payload) '
        "values (%s,'email',%s,%s,%s,%s,%s) on conflict (dedupe_key) do nothing",
        (user_id, event, template, f'{dedupe}:email', email_to or user['email'], Jsonb(base)))


def process_deliveries(limit: int = 50, only_id: str | None = None) -> dict:
    """Envia e-mails pendentes com retry exponencial. Chamado pelo worker (e logo após eventos urgentes)."""
    sent = failed = 0
    pool = get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            q = ("select * from notification_deliveries where status in ('pending','failed') and attempts < max_attempts "
                 "and next_attempt_at <= %s " + ("and id=%s " if only_id else '') +
                 "order by next_attempt_at limit %s for update skip locked")
            params = (timeutil.now(), only_id, limit) if only_id else (timeutil.now(), limit)
            rows = conn.execute(q, params).fetchall()
            for r in rows:
                conn.execute("update notification_deliveries set status='sending', attempts=attempts+1 where id=%s", (r['id'],))
    for r in rows:
        with pool.connection() as conn:
            t = _template(conn, r['template_code'], 'email')
        try:
            if not t:
                raise EmailSendError('Template ausente')
            pid = send_email(r['to_address'], render(t['subject'], r['payload'], False),
                             render(t['body_text'], r['payload'], False), render(t['body_html'] or '', r['payload'], True))
            with pool.connection() as conn:
                conn.execute("update notification_deliveries set status='sent', sent_at=%s, provider_message_id=%s, last_error=null where id=%s",
                             (timeutil.now(), pid, r['id']))
            sent += 1
        except EmailSendError as e:
            backoff = timedelta(seconds=30 * (2 ** r['attempts']))
            with pool.connection() as conn:
                conn.execute("update notification_deliveries set status='failed', last_error=%s, next_attempt_at=%s where id=%s",
                             (str(e)[:300], timeutil.now() + backoff, r['id']))
            failed += 1
    return {'sent': sent, 'failed': failed}
