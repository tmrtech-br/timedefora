"""Infraestrutura de testes: banco PostgreSQL real (TEST_DATABASE_URL), migrations aplicadas do zero,
relógio do servidor controlável e cliente HTTP com cookies + CSRF."""
import os
from datetime import datetime, timedelta

import psycopg
import pyotp
import pytest

TEST_DB = os.getenv('TEST_DATABASE_URL', 'postgresql://postgres@/locaplay_test?host=/tmp')
os.environ['DATABASE_URL'] = TEST_DB
os.environ.setdefault('APP_SECRET_KEY', 'test-secret-key-for-automated-tests-000000')
os.environ['RUN_WORKER'] = 'false'
os.environ['PAYMENT_PROVIDER'] = 'simulated'
os.environ['EMAIL_PROVIDER'] = 'dev'
os.environ['MP_WEBHOOK_SECRET'] = 'whsec-test'

from fastapi.testclient import TestClient  # noqa: E402

from app import migrate, seed  # noqa: E402
from app.core import security, timeutil  # noqa: E402
from app.core.db import close_pool, get_pool, insert, one, tx  # noqa: E402
from app.core.deps import CSRF_COOKIE  # noqa: E402
from app.main import app  # noqa: E402

FORTALEZA = timeutil.TZ


def at(day: int, hour: int, minute: int = 0, month: int = 12, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=FORTALEZA)


@pytest.fixture(scope='session', autouse=True)
def database():
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute('drop schema if exists public cascade')
        c.execute('drop schema if exists extensions cascade')
        c.execute('create schema public')
    migrate.migrate(TEST_DB, verbose=False)
    with tx() as conn:
        seed.base(conn)
    yield
    close_pool()


BUSINESS_TABLES = ['session_events', 'session_input_tokens', 'session_connections', 'game_sessions', 'refunds', 'payment_events',
                   'payments', 'webhook_events', 'queue_entries', 'reservation_holds', 'coupon_redemptions', 'cancellation_requests',
                   'service_incidents', 'reservations', 'coupons', 'price_packages', 'blackout_windows', 'console_game_assignments',
                   'streaming_channels', 'console_operating_hours', 'console_connection_tests', 'console_health_samples',
                   'remote_play_pairings', 'console_method_changes', 'console_connection_configs', 'consoles', 'control_adapters',
                   'capture_devices', 'console_agents', 'game_genres', 'game_platforms', 'favorites', 'games', 'notifications',
                   'notification_deliveries', 'dev_mailbox', 'support_messages', 'support_tickets', 'data_subject_requests',
                   'policy_acceptances', 'linked_accounts', 'oauth_states', 'mfa_recovery_codes', 'mfa_factors',
                   'password_reset_tokens', 'email_verification_codes', 'auth_sessions', 'role_assignments',
                   'notification_preferences', 'users', 'rate_limit_buckets', 'global_settings']


@pytest.fixture(autouse=True)
def clean(database):
    timeutil.set_now(None)
    with get_pool().connection() as c:
        c.execute('alter table audit_logs disable trigger audit_logs_no_update')
        c.execute('truncate ' + ', '.join(BUSINESS_TABLES) + ', audit_logs restart identity cascade')
        c.execute('alter table audit_logs enable trigger audit_logs_no_update')
    with tx() as conn:
        seed.base(conn)
    from app.gamebridge.registry import _ADAPTERS
    sim = _ADAPTERS['simulated']
    sim._streams.clear(); sim._revoked.clear(); sim.inputs.clear(); sim.fail_health.clear(); sim.fail_prepare.clear()
    yield
    timeutil.set_now(None)


@pytest.fixture
def freeze():
    def _f(dt: datetime):
        timeutil.set_now(dt)
        return dt
    return _f


class Api:
    """TestClient com envio automático do header CSRF (double-submit)."""

    def __init__(self):
        self.c = TestClient(app)

    def _h(self, headers=None):
        h = dict(headers or {})
        tok = self.c.cookies.get(CSRF_COOKIE)
        if tok:
            h['X-CSRF-Token'] = tok
        return h

    def get(self, url, **kw): return self.c.get(url, **kw)
    def post(self, url, json=None, headers=None, **kw): return self.c.post(url, json=json, headers=self._h(headers), **kw)
    def put(self, url, json=None, headers=None, **kw): return self.c.put(url, json=json, headers=self._h(headers), **kw)
    def patch(self, url, json=None, headers=None, **kw): return self.c.patch(url, json=json, headers=self._h(headers), **kw)
    def delete(self, url, headers=None, **kw): return self.c.delete(url, headers=self._h(headers), **kw)


def make_user(username='jogador1', email=None, password='SenhaForte123', roles=('client',), verified=True) -> dict:
    username = username if len(username) >= 3 else username + '_jg'
    email = email or f'{username.lower()}@teste.com'
    with tx() as conn:
        u = insert(conn, 'users', {'full_name': f'Pessoa {username}', 'username': username, 'email': email,
                                   'password_hash': security.hash_password(password),
                                   'status': 'active' if verified else 'pending_verification',
                                   'email_verified_at': timeutil.now() if verified else None})
        for r in roles:
            conn.execute('insert into role_assignments(user_id, role_id) select %s, id from roles where code=%s', (u['id'], r))
        conn.execute('insert into notification_preferences(user_id) values (%s)', (u['id'],))
    return {**u, 'password': password}


def login(user: dict) -> Api:
    api = Api()
    r = api.post('/auth/login', json={'email': user['email'], 'password': user['password']})
    assert r.status_code == 200, r.text
    return api


def admin_api(username='chefe', role='superadmin') -> tuple[Api, dict]:
    u = make_user(username, roles=('client', role))
    api = login(u)
    secret = api.post('/me/mfa/setup').json()['secret']
    code = pyotp.TOTP(secret).at(timeutil.now())
    r = api.post('/me/mfa/confirm', json={'code': code})
    assert r.status_code == 200, r.text
    return api, u


@pytest.fixture
def world(freeze):
    """Cenário padrão: PS5 nº 01 simulado/validado/publicado com GTA VI em 02/12/2026 08:00–10:00 (Fortaleza),
    pacotes 10/30 min, setup configurável (padrão 0 nos testes de borda)."""
    freeze(at(2, 7, 0))
    n = timeutil.now()
    with tx() as conn:
        conn.execute("insert into global_settings(key, value) values ('setup_minutes', '0')")
        ag = insert(conn, 'console_agents', {'name': 'sim-1', 'host_name': 'sim', 'is_simulated': True, 'status': 'online'})
        plat = one(conn, "select id from platforms where code='PS5'")
        c = insert(conn, 'consoles', {'code': 'PS5-01', 'name': 'PS5 nº 01', 'platform_id': plat['id'], 'status': 'online', 'agent_id': ag['id']})
        insert(conn, 'console_connection_configs', {'console_id': c['id'], 'method': 'simulated', 'agent_id': ag['id'], 'connection_status': 'online',
                                                    'video_validated_at': n, 'audio_validated_at': n, 'control_validated_at': n,
                                                    'heartbeat_validated_at': n, 'validated_at': n})
        conn.execute('update consoles set is_published=true where id=%s', (c['id'],))
        g = insert(conn, 'games', {'slug': 'gta-vi', 'title': 'GTA VI', 'status': 'published', 'is_demo': True, 'min_minutes': 10, 'max_minutes': 120})
        insert(conn, 'game_platforms', {'game_id': g['id'], 'platform_id': plat['id']})
        a = insert(conn, 'console_game_assignments', {'console_id': c['id'], 'game_id': g['id'], 'starts_at': at(2, 8), 'ends_at': at(2, 10)})
        insert(conn, 'price_packages', {'name': '10 min', 'minutes': 10, 'price_cents': 3000})
        insert(conn, 'price_packages', {'name': '30 min', 'minutes': 30, 'price_cents': 5000})
    return {'console': c, 'game': g, 'assignment': a, 'agent': ag, 'platform': plat}


def reserve(api: Api, world, minutes, mode='queue', start_at=None, **extra):
    body = {'game_id': str(world['game']['id']), 'minutes': minutes, 'mode': mode, 'accept_policy': True, **extra}
    if start_at is not None:
        body['start_at'] = start_at.isoformat()
    return api.post('/reservations', json=body)


def pay(api: Api, reservation_id, outcome='approved'):
    r = api.post(f'/reservations/{reservation_id}/checkout', json={'method': 'pix'})
    assert r.status_code == 200, r.text
    return api.post(f"/payments/simulated/{r.json()['payment_id']}/notify", json={'outcome': outcome})


def last_email(to: str) -> dict | None:
    with get_pool().connection() as c:
        return c.execute('select * from dev_mailbox where to_address=%s order by id desc limit 1', (to,)).fetchone()
