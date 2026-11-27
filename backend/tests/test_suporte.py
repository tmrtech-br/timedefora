from app.core.db import one, tx

from conftest import admin_api, login, make_user


def test_remover_chamado_oculta_do_jogador_e_preserva_conversa_auditavel():
    player = make_user('jogador_suporte')
    api = login(player)
    other = login(make_user('outro_jogador'))
    staff, _ = admin_api(role='operator')
    created = api.post('/support/tickets', json={
        'subject': 'Ajuda com meu controle',
        'category': 'tecnico',
        'message': 'Meu controle não conecta.',
    })
    assert created.status_code == 201, created.text
    tid = created.json()['id']
    url = f'/support/tickets/{tid}'
    assert staff.post(f'{url}/messages', json={'body': 'Vamos conferir a conexão.'}).status_code == 201
    assert other.delete(url).status_code == 404
    assert api.get('/support/tickets').json()[0]['id'] == tid

    assert api.delete(url).status_code == 204
    assert api.delete(url).status_code == 204
    assert api.get('/support/tickets').json() == []
    assert api.get(url).status_code == 404
    assert api.post(f'{url}/messages', json={'body': 'Ainda preciso de ajuda.'}).status_code == 404
    assert api.get(f'/admin{url}').status_code == 403

    found = staff.get('/admin/support/tickets', params={'q': tid})
    assert found.status_code == 200, found.text
    assert [(row['id'], bool(row['hidden_by_user_at'])) for row in found.json()] == [(tid, True)]
    audited = staff.get(f'/admin{url}').json()
    assert [msg['body'] for msg in audited['messages']] == ['Meu controle não conecta.', 'Vamos conferir a conexão.']

    added = staff.post(f'/admin{url}/messages', json={'body': 'Verificação registrada no histórico.'})
    assert added.status_code == 201, added.text
    assert len(staff.get(f'/admin{url}').json()['messages']) == 3
    assert api.get('/support/tickets').json() == []
    with tx() as conn:
        event = one(conn, """select actor_user_id, count(*) as total from audit_logs
                             where action='support.ticket_hidden_by_user' and record_id=%s group by actor_user_id""", (tid,))
        assert event == {'actor_user_id': player['id'], 'total': 1}
        assert not one(conn, 'select 1 from notifications where dedupe_key=%s', (f"support:{added.json()['id']}",))
