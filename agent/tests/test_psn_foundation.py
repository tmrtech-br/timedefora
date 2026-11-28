"""Executable offline tests: never impersonate a real Sony console/stream."""
import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from remoteplay.psn.accounts import AccountError, PsnAccountStore
from remoteplay.psn.negotiation import (
    CUSTOM_DATA_UPDATED, SESSION_MESSAGE_CREATED, RemotePeer, accept_control_candidate, wait_for_control_offer,
)
from remoteplay.psn.session_manager import RemoteSession, acknowledge_offer
from remoteplay.psn.registration import RemoteRegistration, build_ps4_request
from remoteplay.psn.play_session import RemotePlaySessionError, initialize_ps4_session
from remoteplay.remote.rudp import SessionResponse
from remoteplay.psn.oauth import REDIRECT, SCOPE, OAuthCredentialsRejected, OAuthError, account_info, login_url, parse_redirect, request_token
from consoleagent.psn_routes import create_psn_router


def test_login_requests_a_fresh_remote_play_device_identifier():
    params = parse_qs(urlsplit(login_url()).query)
    identifier, = params['duid']
    assert len(identifier) == 48
    assert bytes.fromhex(identifier).startswith(bytes.fromhex('0000000700410080'))
    assert params['scope'] == [SCOPE]
    assert parse_qs(urlsplit(login_url()).query)['duid'] != params['duid']


@pytest.mark.asyncio
async def test_control_offer_requires_session_data_and_accepts_missing_local_peer_value():
    payload = (
        'body={"action":"OFFER","reqId":17,"error":0,'
        '"connRequest":{"candidate":[{"addr":"192.0.2.2","port":9296}],"localPeerAddr":}}'
    )

    async def notifications():
        yield SESSION_MESSAGE_CREATED, {'sessionMessage': {'payload': payload}}, None
        yield CUSTOM_DATA_UPDATED, {
            'customData1': base64.b64encode(base64.b64encode(bytes.fromhex('a2' * 16))).decode()
        }, None

    offer = await wait_for_control_offer(notifications())
    assert offer.custom_data == bytes.fromhex('a2' * 16)
    assert offer.request['reqId'] == 17
    assert offer.request['connRequest']['localPeerAddr'] is None


@pytest.mark.asyncio
async def test_control_ack_is_sent_to_the_console_in_the_current_session():
    sid = '0a0a0a0a-1212-4343-ba54-111111111111'
    duid = 'ab' * 32

    def handler(request):
        assert request.method == 'POST'
        assert request.url.path.endswith(f'/{sid}/sessionMessage')
        envelope = json.loads(request.content)
        assert envelope['to'] == [{'accountId': '1234', 'deviceUniqueId': duid, 'platform': 'PS4'}]
        assert json.loads(envelope['payload'].split('body=', 1)[1]) == {
            'action': 'RESULT', 'reqId': 17, 'error': 0, 'connRequest': {},
        }
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await acknowledge_offer(client, 'synthetic', RemoteSession(sid, '1234'), duid, 'PS4', 17)


@pytest.mark.asyncio
async def test_accept_acknowledges_only_the_matching_control_pair(monkeypatch):
    methods = []
    peer = RemotePeer(RemoteSession('0a0a0a0a-1212-4343-ba54-111111111111', '1234'), 'ab' * 32, b'', b'')
    own = {'reqId': 6, 'connRequest': {'sid': 44, 'peerSid': 55,
                                     'candidate': [{'type': 'LOCAL', 'addr': '192.0.2.10', 'port': 52996}]}}
    selected = {'type': 'LOCAL', 'addr': '192.0.2.9', 'port': 9296}

    async def keep_answering(*args):
        await asyncio.Future()

    monkeypatch.setattr('remoteplay.psn.negotiation.answer_control_probes', keep_answering)

    async def notifications():
        for req_id, destination in ((25, 45), (26, 44)):
            payload = json.dumps({'action': 'ACCEPT', 'reqId': req_id, 'error': 0,
                                  'connRequest': {'sid': 55, 'peerSid': destination}})
            yield SESSION_MESSAGE_CREATED, {'sessionMessage': {'payload': f'body={payload}'}}, None

    def handler(request):
        payload = json.loads(request.content)['payload']
        methods.append(json.loads(payload.split('body=', 1)[1]))
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await accept_control_candidate(client, 'synthetic', peer, 'PS4', notifications(), None, own,
                                       {'sid': 55}, selected)

    assert [message['action'] for message in methods] == ['ACCEPT', 'RESULT']
    assert methods[0]['connRequest']['candidate'] == [selected | {'mappedAddr': '192.0.2.10', 'mappedPort': 52996}]
    assert methods[1]['reqId'] == 26


def test_ps4_registration_constructs_encrypted_rudp_http_request():
    request, cipher = build_ps4_request('42', '192.0.2.10', b'1' * 16, b'2' * 16, b'3' * 16, b'4' * 16)
    head, body = request.split(b'\r\n\r\n', 1)
    assert head.startswith(b'POST /sie/ps4/rp/sess/rgst HTTP/1.1\r\n')
    assert f'Content-Length: {len(body)}'.encode() in head
    assert b'HOST: 192.0.2.10' in head
    assert b'Np-AccountId' not in body
    assert b'Np-AccountId: KgAAAAAAAAA=\r\n' in cipher.decrypt(body[480:])


@pytest.mark.asyncio
async def test_ps4_session_initialization_checks_the_remote_nonce():
    class Channel:
        peer = ('192.0.2.2', 9296)
        nonce = b'n' * 16

        async def negotiate_cookie(self):
            return 17

        async def request_session(self, counter, request, *, timeout):
            assert counter == 17
            assert b'Host: 192.0.2.2:9296\r\n' in request
            assert b'RP-Registkey: 0102\r\n' in request
            return SessionResponse(200, {'rp-nonce': base64.b64encode(self.nonce).decode()}, b'', 29)

        async def finish_exchange(self, counter):
            assert counter == 29

    channel = Channel()
    registration = RemoteRegistration(b'\x01\x02', b's' * 16)
    assert await initialize_ps4_session(channel, registration) == b'n' * 16
    channel.nonce = b'invalid'
    with pytest.raises(RemotePlaySessionError, match='nonce'):
        await initialize_ps4_session(channel, registration)


class TestCipher:
    """Fake cipher ONLY for offline tests; production requires WindowsDpapi."""
    def encrypt(self, b):
        return b'SEALED:' + b[::-1]
    def decrypt(self, b):
        if not b.startswith(b'SEALED:'):
            raise ValueError('invalid')
        return b[7:][::-1]


def test_vault_seals_all_secrets_and_returns_only_metadata(tmp_path):
    p = tmp_path / 'psn_accounts.json.dpapi'
    s = PsnAccountStore(p, protector=TestCipher())
    metadata = s.upsert('a', 'teste01', access_token='do-not-print-token', refresh_token='top-secret-refresh',
                        status='linked', account_id='metadata')
    assert 'access_token' not in metadata
    assert 'refresh_token' not in metadata
    assert b'top-secret-refresh' not in p.read_bytes()
    assert b'do-not-print-token' not in p.read_bytes()
    assert metadata['status'] == 'linked'
    assert PsnAccountStore(p, protector=TestCipher()).get('a')['refresh_token'] == 'top-secret-refresh'
    assert s.delete('a')
    assert s.public_get('a') is None


def test_vault_refuses_unencrypted_json(tmp_path):
    p = tmp_path / 'vault'
    p.write_text(json.dumps({'token': 'plaintext'}))
    with pytest.raises(AccountError, match='inválido'):
        PsnAccountStore(p, protector=TestCipher())


def test_sony_redirect_validation():
    valid = 'https://remoteplay.dl.playstation.net/remoteplay/redirect?code=ABC123'
    assert parse_redirect(valid) == 'ABC123'
    for attack in ('http://remoteplay.dl.playstation.net/remoteplay/redirect?code=123',
                   'https://evil.net/remoteplay/redirect?code=123',
                   'https://remoteplay.dl.playstation.net/remoteplay/redirect?error=access_denied'):
        with pytest.raises(OAuthError):
            parse_redirect(attack)


@pytest.mark.asyncio
async def test_profile_request_does_not_log_access_token(caplog):
    token = 'synthetic-private-access-token'
    caplog.set_level(logging.INFO, logger='httpx')
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={'user_id': '123'}))
    async with httpx.AsyncClient(transport=transport) as client:
        assert (await account_info(client, token))['account_id']
    assert '[redacted]' in caplog.text
    assert token not in caplog.text


@pytest.mark.asyncio
async def test_token_exchanges_have_real_http_response_requirement():
    async def handler(req: httpx.Request):
        form = parse_qs(req.content.decode())
        assert form['redirect_uri'] == [REDIRECT]
        assert form['scope'] == [SCOPE]
        if form['grant_type'] == ['authorization_code']:
            return httpx.Response(200, json={'access_token': 'real-response', 'refresh_token': 'rotate', 'expires_in': 120})
        if form['refresh_token'] == ['rotate']:
            return httpx.Response(200, json={'access_token': 'renewed', 'refresh_token': 'next'})
        error = 'invalid_grant' if form['refresh_token'] == ['expired'] else 'invalid_request'
        return httpx.Response(400, json={'error': error})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        t = await request_token(client, code='fake-from-http-mock')
        assert t['refresh_token'] == 'rotate' and t['access_token'] == 'real-response'
        renewed = await request_token(client, refresh_token='rotate')
        assert renewed['access_token'] == 'renewed' and renewed['refresh_token'] == 'next'
        with pytest.raises(OAuthCredentialsRejected):
            await request_token(client, refresh_token='expired')
        with pytest.raises(OAuthError, match='HTTP 400') as failure:
            await request_token(client, refresh_token='bad-request')
        assert not isinstance(failure.value, OAuthCredentialsRejected)


@pytest.mark.asyncio
async def test_agent_rejects_unauthorized_requests_and_never_simulates_psn_devices(tmp_path):
    app = FastAPI()
    app.include_router(create_psn_router('private-agent-token', tmp_path / 'v', TestCipher()))
    t = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=t, base_url='http://test') as c:
        url = '/v1/psn/accounts/a/devices'
        assert (await c.post(url)).status_code == 401
        result = await c.post(url, headers={'Authorization': 'Bearer private-agent-token'})
        assert result.status_code == 422
        assert 'vinculada' in result.json()['message'].lower()


@pytest.mark.asyncio
async def test_ps4_lan_discovery_requires_agent_credentials():
    from consoleagent.discovery import ConsoleInfo

    def discover(host, platform):
        assert host is None and platform == 'PS4'
        return [ConsoleInfo('192.0.2.4', 'ligado', '200', host_name='PS4 teste')]

    app = FastAPI()
    app.include_router(create_psn_router('private-agent-token', discover=discover))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        url = '/v1/psn/accounts/a/devices/ps4-lan'
        assert (await c.post(url)).status_code == 401
        result = await c.post(url, headers={'Authorization': 'Bearer private-agent-token'})
        assert result.status_code == 200
        assert result.json()['devices'][0]['address'] == '192.0.2.4'


@pytest.mark.asyncio
async def test_locks_are_per_account_and_distinct(tmp_path):
    s = PsnAccountStore(tmp_path / 'safe', protector=TestCipher())
    assert s.refresh_lock('teste01') is not s.refresh_lock('teste02')
    assert s.refresh_lock('teste01') is s.refresh_lock('teste01')


@pytest.mark.asyncio
async def test_concurrent_refresh_of_one_account_only_calls_sony_once(tmp_path):
    import time
    s = PsnAccountStore(tmp_path / 'safe', protector=TestCipher())
    s.upsert('a', 'teste01', access_token='expired', refresh_token='refresh', expires_at=0, status='linked')
    s.upsert('b', 'teste02', access_token='valid', refresh_token='refresh-b', expires_at=time.time()+5000, status='linked')
    counter = 0
    async def renew(refresh):
        nonlocal counter
        counter += 1
        await asyncio.sleep(.01)
        return {'access_token': 'renewed', 'refresh_token': refresh, 'expires_at': time.time()+3600}
    results = await asyncio.gather(*[s.access_token('a', renew) for _ in range(8)], s.access_token('b', renew))
    assert results[:8] == ['renewed'] * 8
    assert results[8] == 'valid'
    assert counter == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('expires_at', [9999999999, 0], ids=['valid-token', 'expired-token'])
async def test_login_flow_returns_only_public_metadata(tmp_path, monkeypatch, expires_at):
    from consoleagent import psn_routes
    async def fake_token(client, **kw):
        if 'refresh_token' in kw:
            raise OAuthCredentialsRejected('Sony rejeitou o token de renovação.')
        return {'access_token': 'secret-from-http', 'refresh_token': 'secret-refresh', 'expires_at': expires_at}
    async def fake_info(client, token):
        return {'online_id': 'teste-id', 'account_id': 'public-account-id'}
    monkeypatch.setattr(psn_routes, 'request_token', fake_token)
    monkeypatch.setattr(psn_routes, 'account_info', fake_info)
    app = FastAPI()
    path = tmp_path / 'encrypted'
    app.include_router(create_psn_router('top-secret', path, TestCipher()))
    transport = httpx.ASGITransport(app=app)
    h = {'Authorization': 'Bearer top-secret'}
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as c:
        await c.post('/v1/psn/accounts/a/login/start', json={'label': 'teste01'}, headers=h)
        res = await c.post('/v1/psn/accounts/a/login/finish', headers=h,
                           json={'label': 'teste01', 'redirect_url':
                                 'https://remoteplay.dl.playstation.net/remoteplay/redirect?code=abc'})
        assert res.status_code == 200
        assert res.json()['account']['online_id'] == 'teste-id'
        assert 'access_token' not in res.text and 'refresh_token' not in res.text
        assert b'secret-from-http' not in path.read_bytes()
        res = await c.post('/v1/psn/accounts/a/test', headers=h)
        if expires_at:
            assert res.status_code == 200
            assert res.json()['account']['status'] == 'linked'
            assert 'validado' in res.json()['message']
        else:
            assert res.status_code == 422
            assert res.json()['code'] == 'psn_token_expired'


@pytest.mark.asyncio
async def test_agent_importa_login_sony_feito_pelo_servidor(tmp_path):
    app = FastAPI()
    app.include_router(create_psn_router('private-agent-token', tmp_path / 'v', TestCipher()))
    t = httpx.ASGITransport(app=app)
    body = {'label': 'conta', 'access_token': 'AT', 'refresh_token': 'RT', 'expires_at': 99, 'account_id': 'QUJD', 'online_id': 'dono'}
    async with httpx.AsyncClient(transport=t, base_url='http://test') as c:
        url = '/v1/psn/accounts/acc1/import/credentials'
        assert (await c.post(url, json=body)).status_code == 401
        result = await c.post(url, json=body, headers={'Authorization': 'Bearer private-agent-token'})
        assert result.status_code == 200, result.text
        assert result.json()['account']['status'] == 'linked'
        assert 'RT' not in result.text
    assert PsnAccountStore(tmp_path / 'v', protector=TestCipher()).get('acc1')['refresh_token'] == 'RT'
