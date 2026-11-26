"""Regressões da revisão de 26/11 do Remote Play pela PSN (sem hardware, sem rede)."""
import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from consoleagent.config import AgentConfig  # noqa: E402
from consoleagent.links import LinkError  # noqa: E402
from consoleagent.media import Frame  # noqa: E402
from consoleagent.runtime import ConsoleRuntime, Deps, Job, Target  # noqa: E402
from remoteplay.psn.accounts import AccountError, PsnAccountStore  # noqa: E402
from remoteplay.psn.media import stream_options  # noqa: E402
from remoteplay.psn.oauth import OAuthCredentialsRejected, OAuthError  # noqa: E402
from remoteplay.psn.play_session import Ps4Control  # noqa: E402


class Cipher:
    def encrypt(self, b):
        return b'SEALED:' + b[::-1]

    def decrypt(self, b):
        return b[len(b'SEALED:'):][::-1]


def cfg(**kw):
    return AgentConfig(api_url='http://127.0.0.1:8000', agent_token='a', api_to_agent_token='t', **kw)


class FlakyPsnLink:
    """Imita o PsnLink: start() só volta com imagem, e falha quando o console ainda está acordando."""
    kind = 'direct'
    available = True
    unavailable_reason = ''

    def __init__(self, failures):
        self.failures, self.starts, self.stops, self._on = failures, 0, 0, False

    def start(self, t, sleep=None):
        self.starts += 1
        if self.starts <= self.failures:
            raise LinkError('Aguardar entrada do console. Tempo esgotado.')
        self._on = True

    def stop(self):
        self.stops += 1
        self._on = False

    @property
    def running(self):
        return self._on

    def frame(self):
        return Frame(True, 'imagem ok')

    def new_pad(self):
        return type('Pad', (), {'reset': lambda s: None, 'close': lambda s: None})()

    def log_tail(self):
        return ''


def psn_target():
    return Target(console_id='c1', route='internet_psn', host=None, platform='PS4', identifier='ps4',
                  nickname='ps4', psn_account_id='acc')


def test_psn_link_failure_is_retried():
    link = FlakyPsnLink(failures=1)
    rt = ConsoleRuntime(cfg(psn_connect_attempts=3), Deps(link=link, sleep=lambda s: None))
    message = rt._bringup(psn_target(), Job('connect', None))
    assert link.starts == 2 and 'Conectado' in message


def test_psn_link_failure_gives_up_after_attempts():
    link = FlakyPsnLink(failures=5)
    rt = ConsoleRuntime(cfg(psn_connect_attempts=2), Deps(link=link, sleep=lambda s: None))
    with pytest.raises(LinkError):
        rt._bringup(psn_target(), Job('connect', None))
    assert link.starts == 2


def test_lan_link_failure_is_not_retried():
    link = FlakyPsnLink(failures=1)
    rt = ConsoleRuntime(cfg(psn_connect_attempts=3), Deps(link=link, sleep=lambda s: None))
    t = psn_target()
    t.route, t.host = 'lan', '192.168.0.10'     # sem PSN: a falha sobe na hora
    rt.d.discover = lambda *a: [type('C', (), {'state': 'ligado'})()]
    with pytest.raises(LinkError):
        rt._bringup(t, Job('connect', None))
    assert link.starts == 1


@pytest.mark.asyncio
async def test_transient_renewal_failure_keeps_account_linked(tmp_path):
    s = PsnAccountStore(tmp_path / 'v', protector=Cipher())
    s.upsert('a', 'teste01', access_token='old', refresh_token='r', expires_at=0, status='linked')

    async def offline(refresh):
        raise OAuthError('A Sony não respondeu durante a autenticação. Tente novamente.')

    with pytest.raises(AccountError, match='temporária'):
        await s.access_token('a', offline)
    assert s.get('a')['status'] == 'linked'

    async def rejected(refresh):
        raise OAuthCredentialsRejected('invalid_grant')

    with pytest.raises(AccountError, match='recusou'):
        await s.access_token('a', rejected)
    assert s.get('a')['status'] == 'expired'


def test_store_reloads_changes_written_by_another_instance(tmp_path):
    path = tmp_path / 'v'
    routes = PsnAccountStore(path, protector=Cipher())
    routes.upsert('a', 'teste01', access_token='old', refresh_token='r1', expires_at=0, status='linked')
    other = PsnAccountStore(path, protector=Cipher())
    time.sleep(0.01)
    other.update('a', access_token='new', refresh_token='r2', expires_at=9999999999)
    # Gravação posterior pela primeira instância não pode devolver os tokens antigos ao disco.
    routes.upsert('b', 'teste02', status='pending')
    fresh = PsnAccountStore(path, protector=Cipher())
    assert fresh.get('a')['refresh_token'] == 'r2' and fresh.get('b')['label'] == 'teste02'


def test_refresh_lock_works_across_event_loops(tmp_path):
    s = PsnAccountStore(tmp_path / 'v', protector=Cipher())
    s.upsert('a', 'teste01', access_token='old', refresh_token='r', expires_at=0, status='linked')
    calls = []

    async def renew(refresh):
        calls.append(refresh)
        await asyncio.sleep(0.05)
        return {'access_token': 'new', 'refresh_token': refresh, 'expires_at': time.time() + 3600}

    results = []
    threads = [threading.Thread(target=lambda: results.append(asyncio.run(s.access_token('a', renew))))
               for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(5)
    assert results == ['new'] * 4 and len(calls) == 1


@pytest.mark.parametrize('resolution,fps,kbps,expected', [
    ('720p', 60, 0, {'resolution': '720p', 'fps': 60, 'quality': 'medium'}),
    ('1080p', 30, 15000, {'resolution': '720p', 'fps': 30, 'quality': 'very_high'}),
    ('540p', 45, 5000, {'resolution': '540p', 'fps': 30, 'quality': 'low'}),
    (None, None, 500, {'resolution': '720p', 'fps': 30, 'quality': 'very_low'}),
])
def test_stream_options_follow_console_settings(resolution, fps, kbps, expected):
    assert stream_options(resolution, fps, kbps) == expected


class FullChannel:
    def __init__(self):
        self.sent = []

    async def send_ctrl(self, payload, wait_ack=False):
        if payload[4:6] == b'\x00\xfe':
            raise BufferError('Fila RUDP de envio confiável cheia (16 mensagens).')
        self.sent.append(payload)

    async def recv(self, timeout):
        await asyncio.sleep(0.01)          # nada chega do console: o leitor manda heartbeat
        raise TimeoutError


@pytest.mark.asyncio
async def test_control_reader_survives_full_send_queue():
    control = Ps4Control(FullChannel(), cipher=None, initial=b'')
    await asyncio.sleep(0.05)
    assert not control._reader.done() and control.error is None
    await control.close()


@pytest.mark.asyncio
async def test_standby_sends_ctrl_message():
    channel = FullChannel()
    control = Ps4Control(channel, cipher=None, initial=b'')
    assert await control.standby()
    assert channel.sent[-1] == b'\x00\x00\x00\x00\x00\x50\x00\x00'
    await control.close()


class StandbyLink(FlakyPsnLink):
    def __init__(self):
        super().__init__(failures=0)
        self._on, self.standbys = True, 0

    def standby(self):
        self.standbys += 1
        return True


def test_stream_stop_with_standby_only_for_active_session():
    from fastapi.testclient import TestClient
    from consoleagent.server import create_app

    link = StandbyLink()
    app = create_app(cfg(), deps=Deps(link=link, sleep=lambda s: None))
    client = TestClient(app)
    headers = {'Authorization': 'Bearer t'}
    body = {'method': 'remote_play_native', 'target': {'route': 'internet_psn', 'platform_code': 'PS4',
                                                       'psn_account_id': 'acc'}}
    assert client.post('/v1/consoles/c1/stream/start', json={**body, 'session_id': 's1'}, headers=headers).json()['ok']
    old = client.post('/v1/consoles/c1/stream/stop', json={**body, 'session_id': 's0', 'standby': True}, headers=headers)
    assert old.json()['ok'] and link.standbys == 0 and app.state.runtimes['c1'].session_id == 's1'
    res = client.post('/v1/consoles/c1/stream/stop', json={**body, 'session_id': 's1', 'standby': True}, headers=headers)
    assert res.json()['data']['standby'] is True and link.standbys == 1 and link.stops >= 1
    assert app.state.runtimes['c1'].session_id is None


def test_stream_stop_notifies_console_even_after_session_marked_stop():
    """Session.stop marca o stop_event (compartilhado) antes de chamar stream.stop: o aviso ainda precisa sair."""
    from pyremoteplay.stream import RPStream

    stream = RPStream.__new__(RPStream)
    stream._stop_event = asyncio.Event()
    stream._stop_event.set()                       # como a sessão deixa antes de chamar stream.stop()
    calls = []
    stream._disconnect = lambda: calls.append('disconnect')
    stream._protocol = type('P', (), {'close': lambda self: calls.append('close')})()
    stream._cb_stop = None
    stream.stop()
    stream.stop()                                  # idempotente
    assert calls == ['disconnect', 'close']


def test_device_disconnect_stops_session_that_never_ran():
    from pyremoteplay.device import RPDevice

    stopped = []
    session = type('S', (), {'is_stopped': False, 'is_running': False,
                             'stop': lambda self: stopped.append(True)})()
    dev = RPDevice.__new__(RPDevice)
    dev._session = session
    dev.disconnect()
    assert stopped == [True] and dev._session is None


def test_failed_bringup_releases_half_open_connection():
    class HalfOpen(FlakyPsnLink):
        def start(self, t, sleep=None):
            self.starts += 1
            self._on = False                      # conectou mas nunca transmitiu

    link = HalfOpen(failures=0)
    rt = ConsoleRuntime(cfg(stream_timeout_seconds=0.01), Deps(link=link, sleep=lambda s: None))
    t = psn_target()
    t.route, t.host = 'lan', '192.168.0.10'
    rt.d.discover = lambda *a: [type('C', (), {'state': 'ligado'})()]
    job = rt.start_job(t, 'connect', wait=5)
    assert job.state == 'failed' and link.stops >= 1


def test_refusal_messages_are_actionable():
    from consoleagent.links import _explain_refusal
    from pyremoteplay.errors import RPErrorHandler

    busy = RPErrorHandler()(0x80108B13)
    assert 'reinicie o PS4' in _explain_refusal(busy)
    assert 'outra sessão' in _explain_refusal(RPErrorHandler()(0x80108B10))
