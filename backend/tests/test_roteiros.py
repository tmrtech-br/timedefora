"""Roteiros de abertura: proprietário e equipe editam; a preparação envia o roteiro ao agente."""
import base64

from app.core.db import tx
from app.services import launch_scripts
from conftest import admin_api
from test_owner import _owner

PNG = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 64).decode()


def test_roteiro_do_console_do_proprietario(world):
    api, user = _owner('dono_roteiro')
    admin, _ = admin_api('chefe_roteiro')
    cid, gid = str(world['console']['id']), str(world['game']['id'])
    with tx() as conn:   # o console do cenário passa a ser deste proprietário, com o jogo vinculado
        conn.execute('update consoles set owner_user_id=%s where id=%s', (user['id'], cid))
    base = f'/owner/consoles/{cid}/launch-scripts'
    listed = api.get(base).json()
    assert [g['game_id'] for g in listed['games']] == [gid] and listed['games'][0]['steps'] == []
    bad = api.put(f'{base}/{gid}', json={'steps': ['pular'], 'images': {}})
    assert bad.status_code == 422 and 'Passo 1' in bad.json()['message']
    missing = api.put(f'{base}/{gid}', json={'steps': ['wait_image:30:menu'], 'images': {}})
    assert missing.status_code == 422 and 'menu' in missing.json()['message']
    steps = ['PS', 'press_if_text:Cross:Seja bem-vindo', 'press_until_text:dpad_right:20:Far Cry 5', 'cross', 'wait_image:60:Menu']
    ok = api.put(f'{base}/{gid}', json={'steps': steps, 'images': {'menu': {'png': PNG, 'width': 1280}}})
    assert ok.status_code == 200, ok.text
    assert ok.json()['steps'] == ['ps', 'press_if_text:cross:Seja bem-vindo', 'press_until_text:dpad_right:20:Far Cry 5',
                                  'cross', 'wait_image:60:menu']
    # a preparação leva o roteiro salvo ao agente
    with tx() as conn:
        payload = launch_scripts.game_payload(conn, cid, {'id': gid, 'slug': 'x', 'title': 'X'})
    assert payload['launch']['steps'][0] == 'ps' and 'menu' in payload['launch']['images']
    # outro proprietário não vê; a equipe vê e edita
    other, _ = _owner('outro_dono_roteiro')
    assert other.get(base).status_code == 404
    assert admin.get(f'/admin/consoles/{cid}/launch-scripts').json()['games'][0]['steps'][0] == 'ps'
    assert admin.put(f'/admin/consoles/{cid}/launch-scripts/{gid}', json={'steps': ['ps', 'cross'], 'images': {}}).status_code == 200
    assert api.get(base).json()['games'][0]['steps'] == ['ps', 'cross']
    assert api.delete(f'{base}/{gid}').status_code == 200
    with tx() as conn:
        assert 'launch' not in launch_scripts.game_payload(conn, cid, {'id': gid, 'slug': 'x', 'title': 'X'})


def test_jogo_reconhecido_usa_o_fluxo_padrao(world):
    api, user = _owner('dono_reconhece')
    cid, gid = str(world['console']['id']), str(world['game']['id'])
    with tx() as conn:
        conn.execute('update consoles set owner_user_id=%s where id=%s', (user['id'], cid))
    base = f'/owner/consoles/{cid}/launch-scripts/{gid}'
    assert api.put(base + '/title', json={'title_id': 'far cry'}).status_code == 422
    assert api.put(base + '/title', json={'title_id': 'cusa05904_00', 'title_name': 'Far Cry 5'}).json()['title_id'] == 'CUSA05904'
    assert api.put(base, json={'steps': ['ps'], 'images': {}}).status_code == 200      # roteiro salvo não apaga o código
    with tx() as conn:
        payload = launch_scripts.game_payload(conn, cid, {'id': gid, 'slug': 'x', 'title': 'X'})
    assert payload['title_id'] == 'CUSA05904' and 'launch' not in payload
    listed = api.get(f'/owner/consoles/{cid}/launch-scripts').json()['games'][0]
    assert listed['title_id'] == 'CUSA05904' and listed['title_name'] == 'Far Cry 5'
