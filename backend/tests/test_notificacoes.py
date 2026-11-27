from app.core.db import all_, insert, one, tx

from conftest import login, make_user


def test_limpar_notificacoes_oculta_sem_apagar_e_registra_auditoria():
    player = make_user('notificado')
    other = make_user('outro_notificado')
    api, other_api = login(player), login(other)
    initial_count = len(api.get('/me/notifications').json())
    assert api.post('/me/notifications/read-all').status_code == 200

    def add(conn, user, suffix):
        return insert(conn, 'notifications', {'user_id': user['id'], 'event_code': 'test', 'title': 'Aviso',
                                              'body': 'Conteúdo preservado', 'dedupe_key': f'test:{suffix}'})

    with tx() as conn:
        first = add(conn, player, 'first')
        already_read = add(conn, player, 'read')
        other_message = add(conn, other, 'other')
    assert api.post(f"/me/notifications/{already_read['id']}/read").status_code == 200
    assert api.get('/me/session').json()['user']['unread_notifications'] == 1
    assert api.delete('/me/notifications').status_code == 204
    assert api.delete('/me/notifications').status_code == 204
    assert api.get('/me/notifications').json() == []
    assert api.get('/me/notifications?unread=true').json() == []
    assert api.get('/me/session').json()['user']['unread_notifications'] == 0
    assert str(other_message['id']) in [item['id'] for item in other_api.get('/me/notifications').json()]

    with tx() as conn:
        new = add(conn, player, 'new')
        saved = all_(conn, "select body from notifications where user_id=%s and event_code='test' and hidden_by_user_at is not null", (player['id'],))
        assert saved == [{'body': 'Conteúdo preservado'}] * 2
        events = all_(conn, "select details from audit_logs where action='notifications.cleared_by_user' and actor_user_id=%s", (player['id'],))
        assert events == [{'details': {'count': initial_count + 2}}]
        snapshot = one(conn, """select new_data->>'body' as body from audit_logs where table_name='notifications'
                                and record_id=%s and 'hidden_by_user_at' = any(changed_fields)""", (str(first['id']),))
        assert snapshot == {'body': 'Conteúdo preservado'}
    assert [item['id'] for item in api.get('/me/notifications?unread=true').json()] == [str(new['id'])]
    assert api.post('/me/notifications/read-all').status_code == 200
    assert api.get('/me/session').json()['user']['unread_notifications'] == 0
