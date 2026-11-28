from uuid import uuid4

from app.core.db import tx
from conftest import admin_api, login, make_user


def test_owner_invitation_acceptance_and_inventory(world):
    admin, _ = admin_api()
    user = make_user('locador')
    api = login(user)
    assert api.get('/owner/terms').status_code == 403
    assert admin.post(f"/admin/users/{user['id']}/roles", json={'role': 'owner', 'grant': True}).status_code == 200
    assert api.get('/admin/overview').status_code == 403
    assert api.get('/owner/consoles').status_code == 403
    policy = api.get('/owner/terms').json()
    assert policy['accepted_at'] is None
    assert api.post('/owner/enrollment', json={'policy_version_id': policy['id'], 'accepted': False}).status_code == 422
    assert api.post('/owner/enrollment', json={'policy_version_id': str(uuid4()), 'accepted': True}).status_code == 409

    body = {'policy_version_id': policy['id'], 'accepted': True}
    assert api.post('/owner/enrollment', json=body).status_code == 200
    assert api.post('/owner/enrollment', json=body).status_code == 200
    assert api.get('/owner/consoles').json() == []
    with tx() as conn:
        conn.execute('update consoles set owner_user_id=%s where id=%s', (user['id'], world['console']['id']))
        assert conn.execute("select count(*) n from audit_logs where action='owner.terms_accepted'").fetchone()['n'] == 1
    assert [row['id'] for row in api.get('/owner/consoles').json()] == [str(world['console']['id'])]
    other = login(make_user('outra_locadora', roles=('owner',)))
    assert other.post('/owner/enrollment', json=body).status_code == 200
    assert other.get('/owner/consoles').json() == []
    assert admin.post(f"/admin/users/{user['id']}/roles", json={'role': 'operator', 'grant': True}).status_code == 409


def test_diagnostics_batch(world):
    api, _ = admin_api()
    path = f"/admin/consoles/{world['console']['id']}/diagnostics/run-all"
    assert login(make_user('locador', roles=('owner',))).post(path).status_code == 403
    response = api.post(path)
    assert response.status_code == 200, response.text
    results = {item['test_type']: item for item in response.json()['results']}
    assert set(results) == {'discover', 'pair', 'connection', 'video_audio', 'controls', 'heartbeat', 'latency'}
    assert results['connection']['result'] == 'passed'
    assert results['connection']['duration_ms'] >= 0
    assert results['latency']['result'] == 'not_available'


def _owner(username='dono_valida'):
    from conftest import login, make_user
    user = make_user(username, roles=('client', 'owner'))
    api = login(user)
    policy = api.get('/owner/terms').json()
    assert api.post('/owner/enrollment', json={'policy_version_id': policy['id'], 'accepted': True}).status_code == 200
    return api, user


def test_fluxo_de_validacao_do_console_do_proprietario(world, freeze):
    from conftest import at
    freeze(at(2, 7, 0))
    admin, _ = admin_api('chefe_valida')
    api, user = _owner()
    from app.core import security
    from app.core.db import insert
    with tx() as conn:   # agente real liberado para proprietários
        agent = str(insert(conn, 'console_agents', {'name': 'agente-dono', 'host_name': 'pc', 'is_simulated': False, 'status': 'online',
                                                    'endpoint_url': 'https://agente.exemplo', 'outbound_token_enc': security.encrypt('tok'),
                                                    'available_to_owners': True})['id'])
    assert [a['id'] for a in api.get('/owner/agents').json()] == [agent]
    assert api.get('/owner/consoles/code-check', params={'code': 'x'}).json()['valid'] is False
    assert api.get('/owner/consoles/code-check', params={'code': 'PS5-01'}).json()['available'] is False
    assert api.get('/owner/consoles/code-check', params={'code': 'DONO-01'}).json()['available'] is True
    with tx() as conn:   # o jogo do cenário também roda no PS4 (rota PSN do proprietário é só PS4)
        conn.execute("insert into game_platforms(game_id, platform_id) select %s, id from platforms where code='PS4'", (world['game']['id'],))
    c = api.post('/owner/consoles', json={'code': 'DONO-01', 'name': 'PS4 do dono', 'platform_code': 'PS4'})
    assert c.status_code == 201, c.text
    cid = c.json()['id']
    # incompleto: não envia
    r = api.post(f'/owner/consoles/{cid}/submit')
    assert r.status_code == 422 and r.json()['code'] == 'incomplete'
    assert api.put(f'/owner/consoles/{cid}/availability', json={'min_minutes': 10, 'max_minutes': 60, 'rate_unit': 'minute', 'rate_cents': 100}).status_code == 200
    w = api.post(f'/owner/consoles/{cid}/games', json={'game_id': str(world['game']['id']), 'starts_at': at(3, 8).isoformat(), 'ends_at': at(3, 12).isoformat()})
    assert w.status_code == 201, w.text
    missing = api.get(f'/owner/consoles/{cid}/review').json()['missing']
    assert len(missing) == 2 and any('conexão' in m for m in missing) and any('PSN' in m for m in missing)
    r = api.put(f'/owner/consoles/{cid}/connection-settings', json={'console_identifier': 'DONO-01', 'resolution': '720p', 'fps': 30})
    assert r.status_code == 200, r.text
    with tx() as conn:   # conta PSN conectada pelo agente escolhido (login Sony simulado no banco)
        acc = insert(conn, 'psn_accounts', {'agent_id': None, 'label': 'conta-dono', 'status': 'pending', 'owner_user_id': user['id']})
    assert api.put(f'/owner/consoles/{cid}/connection', json={'psn_account_id': str(acc['id'])}).status_code == 200
    assert api.put(f'/owner/consoles/{cid}/hours', json={'hours': [{'weekday': 1, 'opens_at': '08:00', 'closes_at': '22:00'}]}).json()['pending'] is False
    assert api.get(f'/owner/consoles/{cid}/review').json()['missing'] == [], api.get(f'/owner/consoles/{cid}/review').json()['missing']
    # sem aprovação não publica
    assert api.post(f'/owner/consoles/{cid}/publish').status_code == 409
    assert api.post(f'/owner/consoles/{cid}/submit').status_code == 200
    # em análise: edição bloqueada
    assert api.put(f'/owner/consoles/{cid}/availability', json={'min_minutes': 10, 'max_minutes': 60, 'rate_unit': 'minute', 'rate_cents': 200}).status_code == 409
    queue = admin.get('/admin/owner-reviews').json()
    assert [q['id'] for q in queue] == [cid] and queue[0]['status'] == 'submitted'
    # pedir ajustes exige observação
    assert admin.post(f'/admin/owner-reviews/{cid}/reject', json={'notes': ''}).status_code == 422
    assert admin.post(f'/admin/owner-reviews/{cid}/reject', json={'notes': 'Ajuste as artes do jogo.'}).json()['status'] == 'rejected'
    assert api.get(f'/owner/consoles/{cid}/review').json()['status'] == 'rejected'
    assert api.post(f'/owner/consoles/{cid}/submit').status_code == 200
    # antes da aprovação não testa
    assert api.post(f'/owner/consoles/{cid}/diagnostics').status_code == 409
    assert admin.post(f'/admin/owner-reviews/{cid}/approve', json={'agent_id': agent, 'notes': 'ok'}).status_code == 200
    # aprovado: a conta passou a usar o agente; sem o login Sony ainda não testa
    with tx() as conn:
        assert str(conn.execute('select agent_id from psn_accounts where id=%s', (acc['id'],)).fetchone()['agent_id']) == agent
    assert api.post(f'/owner/consoles/{cid}/diagnostics').json()['code'] == 'psn_login_required'
    with tx() as conn:   # login Sony concluído (simulado no banco)
        conn.execute("update psn_accounts set status='linked' where id=%s", (acc['id'],))
    d = api.post(f'/owner/consoles/{cid}/diagnostics')
    assert d.status_code == 202, d.text
    with tx() as conn:
        cfg = conn.execute('select method, agent_id, internal_host from console_connection_configs where console_id=%s', (cid,)).fetchone()
    assert cfg['method'] == 'remote_play_native' and str(cfg['agent_id']) == agent
    assert api.get(f'/owner/consoles/{cid}/diagnostics').json()['run']['status'] == 'queued'
    diag_cancel = f"/owner/consoles/{cid}/diagnostics/{d.json()['id']}/cancel"
    assert api.post(diag_cancel).json()['status'] == 'cancelled'
    assert api.post(diag_cancel).json()['status'] == 'cancelled'
    st = api.get(f'/owner/consoles/{cid}/review').json()
    assert st['status'] == 'approved' and st['approved_at'] and st['agent_linked'] is True
    # edição de console aprovado: fica pendente (tarifa atual continua)
    assert api.put(f'/owner/consoles/{cid}/availability', json={'min_minutes': 10, 'max_minutes': 90, 'rate_unit': 'minute', 'rate_cents': 150}).json()['pending'] is True
    assert api.get(f'/owner/consoles/{cid}/availability').json()['rate_cents'] == 100
    w2 = api.post(f'/owner/consoles/{cid}/games', json={'game_id': str(world['game']['id']), 'starts_at': at(4, 8).isoformat(), 'ends_at': at(4, 12).isoformat()})
    assert w2.status_code == 201 and w2.json()['status'] == 'pending_review'
    st = api.get(f'/owner/consoles/{cid}/review').json()
    assert st['status'] == 'changes_pending' and st['pending']['rate']['rate_cents'] == 150 and len(st['pending_windows']) == 1
    freeze(at(3, 13))
    blocked = api.post(f'/owner/consoles/{cid}/publish')
    assert blocked.status_code == 409 and blocked.json()['code'] == 'assignment_pending_review'
    assert api.post(f'/owner/consoles/{cid}/submit').status_code == 200
    assert admin.post(f'/admin/owner-reviews/{cid}/approve', json={'notes': ''}).status_code == 200
    assert api.get(f'/owner/consoles/{cid}/availability').json()['rate_cents'] == 150
    with tx() as conn:
        assert conn.execute("select count(*) n from console_game_assignments where console_id=%s and status='active'", (cid,)).fetchone()['n'] == 2
    assert api.get(f'/owner/consoles/{cid}/history').status_code == 200
    assert api.get('/owner/report').status_code == 200
    # horários num console aprovado: ficam pendentes
    assert api.put(f'/owner/consoles/{cid}/hours', json={'hours': [{'weekday': 2, 'opens_at': '10:00', 'closes_at': '20:00'}]}).json()['pending'] is True
    # exclusão sem reservas futuras
    assert api.delete(f'/owner/consoles/{cid}', json={'reason': 'Vendi o console'}).status_code == 200
    assert api.get('/owner/consoles').json() == []


def test_exclusoes_do_proprietario(world, freeze):
    from conftest import at
    from app.core.db import insert
    freeze(at(2, 7, 0))
    api, user = _owner('dono_exclui')
    with tx() as conn:
        conn.execute("insert into game_platforms(game_id, platform_id) select %s, id from platforms where code='PS4'", (world['game']['id'],))
    cid = api.post('/owner/consoles', json={'code': 'EXCL-01', 'name': 'PS4 exclui', 'platform_code': 'PS4'}).json()['id']
    # conta PSN (sem agente) associada e depois excluída
    acc = api.post('/owner/psn-accounts', json={'label': 'conta-x', 'console_id': cid})
    assert acc.status_code == 201, acc.text
    assert api.delete(f"/owner/psn-accounts/{acc.json()['id']}", json={'reason': 'Conta cadastrada errada'}).status_code == 200
    assert api.get('/owner/psn-accounts').json() == []
    # jogo em revisão + período, depois exclusões
    g = api.post(f'/owner/consoles/{cid}/game-drafts', json={'title': 'Jogo do dono', 'min_minutes': 10, 'max_minutes': 60, 'genres': []})
    assert g.status_code == 201, g.text
    w = api.post(f'/owner/consoles/{cid}/games', json={'game_id': g.json()['id'], 'starts_at': at(3, 8).isoformat(), 'ends_at': at(3, 12).isoformat()})
    assert w.status_code == 201, w.text
    assert api.delete(f"/owner/consoles/{cid}/games/{w.json()['id']}", json={'reason': 'Não vou mais oferecer'}).status_code == 200
    assert api.get(f'/owner/consoles/{cid}/games').json()['assignments'] == []
    assert api.delete(f"/owner/consoles/{cid}/game-drafts/{g.json()['id']}", json={'reason': 'Não vou mais oferecer'}).status_code == 200
    assert api.get(f'/owner/consoles/{cid}/games').json()['drafts'] == []
    # só PSN (PS4): rota local é recusada
    assert api.put(f'/owner/consoles/{cid}/connection-settings', json={'network_route': 'lan'}).status_code == 422


def test_login_sony_do_proprietario_antes_da_aprovacao(world, freeze, monkeypatch):
    from conftest import at
    from app.core import security
    from app.core.db import insert
    from app.routers import psn_accounts
    from app.services import psn_oauth
    freeze(at(2, 7, 0))
    admin, _ = admin_api('chefe_login')
    api, user = _owner('dono_login')
    with tx() as conn:
        agent = str(insert(conn, 'console_agents', {'name': 'agente-login', 'host_name': 'pc', 'is_simulated': False, 'status': 'online',
                                                    'endpoint_url': 'https://agente.exemplo', 'outbound_token_enc': security.encrypt('tok')})['id'])
    cid = api.post('/owner/consoles', json={'code': 'DONO-LOG', 'name': 'PS4 login', 'platform_code': 'PS4'}).json()['id']
    acc = api.post('/owner/psn-accounts', json={'console_id': cid, 'label': 'conta-login'}).json()
    sent = []
    def send_agent(target, suffix, payload=None, method='POST'):
        sent.append((target[0], suffix, payload))
        return {'ok': True, 'account': {'account_id': 'QUJD', 'online_id': 'dono_psn'}}

    monkeypatch.setattr(psn_accounts, '_send_agent', send_agent)
    # sem iniciar: não conclui
    assert api.post(f"/owner/psn-accounts/{acc['id']}/login/finish", json={'redirect_url': 'https://x.example/abc'}).json()['code'] == 'login_expired'
    start = api.post(f"/owner/psn-accounts/{acc['id']}/login/start")
    assert start.status_code == 200 and start.json()['login_url'].startswith(psn_oauth.AUTHORIZE_URL)
    assert api.post(f"/owner/psn-accounts/{acc['id']}/login/finish", json={'redirect_url': 'https://evil.example/redirect?code=abc'}).status_code == 422
    creds = {'access_token': 'AT', 'refresh_token': 'RT', 'expires_at': 99}
    monkeypatch.setattr(psn_oauth, 'login', lambda url: (creds, {'account_id': 'QUJD', 'online_id': 'dono_psn'}))
    r = api.post(f"/owner/psn-accounts/{acc['id']}/login/finish", json={'redirect_url': f'{psn_oauth.REDIRECT}?code=abc'})
    assert r.status_code == 200, r.text
    assert r.json() == {'id': acc['id'], 'label': 'conta-login', 'status': 'linked', 'online_id': 'dono_psn'}
    assert sent == []   # ainda sem agente: guardado cifrado no servidor
    with tx() as conn:
        row = conn.execute('select agent_id, credentials_enc from psn_accounts where id=%s', (acc['id'],)).fetchone()
        assert row['agent_id'] is None
        assert '"refresh_token": "RT"' in security.decrypt(row['credentials_enc'])
        assert '"refresh_token"' not in row['credentials_enc']
        logged = conn.execute("select new_data from audit_logs where table_name='psn_accounts' and new_data->>'credentials_enc' is not null").fetchall()
        assert all(x['new_data']['credentials_enc'] == '[REDACTED]' for x in logged)
    # teste da conta sem agente: renova pela Sony
    monkeypatch.setattr(psn_oauth, 'refresh', lambda rt: ({**creds, 'access_token': 'AT2'}, {'account_id': 'QUJD', 'online_id': 'dono_psn'}) if rt == 'RT' else None)
    assert api.post(f"/owner/psn-accounts/{acc['id']}/test").json()['ok'] is True
    # Aprovação e novo login funcionam sem comunicação com o agente.
    with tx() as conn:
        conn.execute("update consoles set owner_review_status='submitted' where id=%s", (cid,))
    assert admin.post(f'/admin/owner-reviews/{cid}/approve', json={'agent_id': agent, 'notes': 'ok'}).status_code == 200
    assert api.post(f"/owner/psn-accounts/{acc['id']}/login/start").status_code == 200
    assert api.post(f"/owner/psn-accounts/{acc['id']}/login/finish", json={'redirect_url': f'{psn_oauth.REDIRECT}?code=novo'}).status_code == 200
    assert sent == []

    # O teste da conta entrega o acesso antes de pedir a validação ao agente.
    assert api.post(f"/owner/psn-accounts/{acc['id']}/test").json()['ok'] is True
    assert [call[1] for call in sent] == ['/import/credentials', '/test']
    assert sent[0][2]['refresh_token'] == 'RT' and sent[0][2]['label'] == 'conta-login'
    with tx() as conn:
        row = conn.execute('select agent_id, status, credentials_enc from psn_accounts where id=%s', (acc['id'],)).fetchone()
    assert str(row['agent_id']) == agent and row['status'] == 'linked' and row['credentials_enc'] is None
