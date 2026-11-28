"""Parte 2 do ConsoleAgent com dublês de chiaki-ng, controle virtual e captura (nenhum hardware envolvido).

Os dublês reproduzem o comportamento observável (processo abre, imagem aparece, console acorda);
a validação com o PS4 real é feita depois, pelos testes do painel.
"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consoleagent import discovery  # noqa: E402
from consoleagent.config import AgentConfig, ConfigError, load  # noqa: E402
from consoleagent.media import Frame  # noqa: E402
from consoleagent.runtime import Deps  # noqa: E402
from consoleagent.server import create_app  # noqa: E402

TOKEN = 'api-para-agente-123'
H = {'Authorization': f'Bearer {TOKEN}'}
PS4 = b'HTTP/1.1 {code}\nhost-id:AABBCCDDEEFF\nhost-type:PS4\nhost-name:PS4-118\nsystem-version:12020001\n'


class FakeChiaki:
    """Link no modo chiaki-ng (mesma interface de consoleagent.links), sem processo real."""
    kind = 'chiaki'
    path = 'C:/fake/chiaki.exe'
    unavailable_reason = ''

    def __init__(self, registered=('PS4-118',), frames_until_video=2):
        self.hosts = list(registered)
        self.available = True
        self._running = False
        self.started = []
        self.frames_until_video = frames_until_video
        self.world = None

    def registered(self, t):
        return t.nickname.lower() in {h.lower() for h in self.hosts}

    def regist_key(self, t):
        return t.regist_key

    @property
    def running(self):
        return self._running

    @property
    def pid(self):
        return 4242 if self._running else None

    def start(self, t, sleep=None):
        from consoleagent.chiaki import ChiakiError
        if t.direct:
            self.started.append(('direct', t.nickname, t.host, t.passcode))
        else:
            if not t.psn_gui_steps:
                raise ChiakiError('Rota PSN: configure "psn_gui_steps" no config.json do agente.')
            self.started.append(('psn', tuple(t.psn_gui_steps)))
        self._running = True

    def stop(self):
        self._running = False

    def frame(self):
        return self.world.frame(self.pid)

    def audio_peak(self, seconds=1.5):
        return self.world.audio(self.pid, seconds)

    def new_pad(self):
        return self.world.pad

    def video_frame(self):
        return None

    def audio_track(self):
        return None

    def pair(self, t, pin):
        from consoleagent.links import ChiakiLink
        return ChiakiLink.pair(self, t, pin)

    def log_tail(self, lines=8):
        return ''


class FakePad:
    def __init__(self):
        self.events, self.resets, self.closed = [], 0, False

    def apply(self, command):
        if command.get('name') in ('ps', 'touchpad'):
            raise PermissionError('Comando bloqueado por segurança.')
        self.events.append(('apply', command['name'], command.get('pressed', command.get('value'))))

    def press(self, name, hold=0.12):
        self.events.append(('press', name))

    def reset(self):
        self.resets += 1

    def close(self):
        self.closed = True


class World:
    """Console falso: estado de energia, imagem e áudio."""

    def __init__(self, power='em repouso', chiaki=None, audio=0.4):
        self.power = power
        self.chiaki = chiaki or FakeChiaki()
        self.pad = FakePad()
        self.woken = []
        self.frame_calls = 0
        self.audio_peak = audio

    def discover(self, host, platform, timeout):
        if self.power is None:
            return []
        code = '200 Ok' if self.power == 'ligado' else '620 Server Standby'
        return [discovery.parse_response(PS4.replace(b'{code}', code.encode()), host or '192.168.0.20')]

    def wake(self, host, key, platform):
        discovery.wakeup_message(key, platform)            # valida a chave como o real
        self.woken.append((host, key))
        self.power = 'ligado'

    def frame(self, pid):
        if not pid:
            return Frame(False, 'Janela do chiaki-ng não encontrada.')
        self.frame_calls += 1
        if self.frame_calls < self.chiaki.frames_until_video:
            return Frame(False, 'Imagem preta.', 1.0, 0.5, (1280, 720))
        return Frame(True, 'Imagem recebida (1280×720).', 90.0, 40.0, (1280, 720))

    def audio(self, pid, seconds=1.5):
        return self.audio_peak, f'pico {self.audio_peak}'

    def deps(self):
        self.chiaki.world = self
        return Deps(link=self.chiaki, discover=self.discover, wake=self.wake, sleep=lambda s: None)


def make(world, **kw):
    consoles = kw.pop('consoles', {'PS4-118': {'nickname': 'PS4-118', 'regist_key': '2ebf539d', 'passcode': '1234',
                                               'games': {'gta-v': ['ps', 'wait:1', 'dpad_right', 'cross']}}})
    kw = {'wake_timeout_seconds': 5, 'stream_timeout_seconds': 5, **kw}
    c = AgentConfig(api_url='http://127.0.0.1:8000', agent_token='a', api_to_agent_token=TOKEN, consoles=consoles, **kw)
    return TestClient(create_app(c, deps=world.deps()))


def call(client, action, body=None, console='c1'):
    return client.post(f'/v1/consoles/{console}/{action}', json=body or {}, headers=H)


def until_done(client, action, body, tries=50):
    for _ in range(tries):
        r = call(client, action, body).json()
        if not r.get('data', {}).get('running'):
            return r
        time.sleep(0.05)
    raise AssertionError('job não terminou')


LAN = {'target': {'route': 'lan', 'host': '192.168.0.20', 'platform_code': 'PS4', 'console_identifier': 'PS4-118'}}
PSN = {'target': {'route': 'internet_psn', 'host': None, 'platform_code': 'PS4', 'console_identifier': 'PS4-118'}}


def test_preparar_rota_direta_acorda_conecta_e_abre_o_jogo():
    w = World(power='em repouso')
    c = make(w)
    r = until_done(c, 'console/prepare', {**LAN, 'game': {'slug': 'gta-v', 'title': 'GTA V'}})
    assert r['ok'] is True and r['simulated'] is False, r
    assert w.woken == [('192.168.0.20', '2ebf539d')]                       # acordou com a chave do agente
    assert w.chiaki.started == [('direct', 'PS4-118', '192.168.0.20', '1234')]
    assert [e for e in w.pad.events if e[0] == 'press'] == [('press', 'ps'), ('press', 'dpad_right'), ('press', 'cross')]
    assert 'Console acordado' in r['message'] and 'Roteiro de abertura de "GTA V"' in r['message']
    # Chamada repetida (a API repete) é idempotente: não reabre o chiaki-ng nem repete o roteiro
    r2 = call(c, 'console/prepare', {**LAN, 'game': {'slug': 'gta-v', 'title': 'GTA V'}}).json()
    assert r2['ok'] and len(w.chiaki.started) == 1 and len([e for e in w.pad.events if e[0] == 'press']) == 3


def test_roteiro_do_painel_tem_prioridade_e_sem_roteiro_a_preparacao_falha():
    w = World(power='ligado')
    c = make(w)
    game = {'slug': 'gta-v', 'title': 'GTA V', 'launch': {'steps': ['ps', 'cross'], 'images': {}}}
    r = until_done(c, 'console/prepare', {**LAN, 'game': game})
    assert r['ok'] is True and 'roteiro do painel' in r['message'], r
    assert [e for e in w.pad.events if e[0] == 'press'] == [('press', 'ps'), ('press', 'cross')]
    # teste do roteiro pelo painel roda de novo mesmo com o jogo já aberto
    r = until_done(c, 'script/test', {**LAN, 'game': game})
    assert r['ok'] is True and len([e for e in w.pad.events if e[0] == 'press']) == 4
    # jogo sem roteiro (nem no painel nem no config.json): não libera o console
    r = until_done(make(World(power='ligado')), 'console/prepare', {**LAN, 'game': {'slug': 'outro', 'title': 'Outro'}})
    assert r['ok'] is False and 'Sem roteiro para abrir "Outro"' in r['message'], r


def test_sem_registro_no_chiaki_falha_com_instrucao():
    w = World(chiaki=FakeChiaki(registered=()))
    r = until_done(make(w), 'connect', LAN)
    assert r['ok'] is False and 'não está registrado no chiaki-ng' in r['message'] and not w.chiaki.started


def test_console_em_repouso_sem_chave_nao_acorda():
    w = World(power='em repouso')
    r = until_done(make(w, consoles={'PS4-118': {'nickname': 'PS4-118'}}), 'connect', LAN)
    assert r['ok'] is False and 'regist_key' in r['message'] and not w.woken


def test_sem_imagem_no_prazo_falha():
    w = World(power='ligado', chiaki=FakeChiaki(frames_until_video=10 ** 9))
    r = until_done(make(w, stream_timeout_seconds=0.2), 'connect', LAN)
    assert r['ok'] is False and 'Sem imagem' in r['message']


def test_rota_psn_exige_roteiro_e_usa_interface():
    w = World()
    r = until_done(make(w), 'connect', PSN)
    assert r['ok'] is False and 'psn_gui_steps' in r['message']
    w2 = World()
    consoles = {'PS4-118': {'nickname': 'PS4-118', 'psn_gui_steps': ['wait:2', 'down', 'enter']}}
    r = until_done(make(w2, consoles=consoles), 'connect', PSN)
    assert r['ok'] is True and w2.chiaki.started == [('psn', ('wait:2', 'down', 'enter'))] and not w2.woken
    r = call(make(w2, consoles=consoles), 'discover', PSN).json()
    assert r['ok'] is True and 'registrado no chiaki-ng' in r['message']


def test_sessao_do_jogador_controle_exclusivo_e_bloqueios():
    w = World(power='ligado')
    c = make(w)
    assert until_done(c, 'connect', LAN)['ok']
    btn = {'type': 'button', 'name': 'cross', 'pressed': True}
    assert call(c, 'input', {'session_id': 's1', 'command': btn}).status_code == 403        # antes de liberar
    r = call(c, 'stream/start', {**LAN, 'session_id': 's1'}).json()
    assert r['ok'] and r['state'] == 'streaming'
    assert call(c, 'input', {'session_id': 's1', 'command': btn}).status_code == 200
    assert call(c, 'input', {'session_id': 's2', 'command': btn}).status_code == 403        # outra sessão
    r = call(c, 'input', {'session_id': 's1', 'command': {'type': 'button', 'name': 'ps'}})
    assert r.status_code == 403 and r.json()['code'] == 'blocked_command'
    call(c, 'stream/stop', {'session_id': 's1'})
    assert call(c, 'input', {'session_id': 's1', 'command': btn}).status_code == 403        # revogado
    assert w.chiaki.running                                                                 # conexão mantida p/ o próximo
    call(c, 'disconnect')
    assert not w.chiaki.running and w.pad.closed


def test_teste_video_audio_exige_imagem_e_som_reais():
    w = World(power='ligado', audio=0.0)
    c = make(w)
    assert until_done(c, 'connect', LAN)['ok']
    r = call(c, 'test/video-audio').json()
    assert r['ok'] is False and r['data']['video_ok'] is True and r['data']['audio_ok'] is False
    w.audio_peak = 0.3
    r = call(c, 'test/video-audio').json()
    assert r['ok'] is True and r['data']['audio_peak'] == 0.3


def test_teste_de_controles_so_aprova_com_reacao_medida():
    w = World(power='ligado')
    c = make(w)
    assert until_done(c, 'connect', LAN)['ok']
    r = call(c, 'test/controls').json()
    assert r['ok'] is False and 'control_test_button' in r['message']


def test_pareamento_confere_registro():
    assert call(make(World()), 'pair', LAN).json()['ok'] is True
    r = call(make(World(chiaki=FakeChiaki(registered=()))), 'pair', LAN).json()
    assert r['ok'] is False and 'Adicionar Dispositivo' in r['message']


def test_mensagem_wakeup():
    m = discovery.wakeup_message('2ebf539d', 'PS4').decode()
    assert m.startswith('WAKEUP * HTTP/1.1\n') and f'user-credential:{int("2ebf539d", 16)}\n' in m and '00020020' in m
    with pytest.raises(ValueError):
        discovery.wakeup_message('xyz!', 'PS4')


def test_config_valida_consoles(tmp_path):
    import json
    p = tmp_path / 'config.json'
    base = {'api_url': 'http://x', 'agent_token': 'a', 'api_to_agent_token': 'b'}
    p.write_text(json.dumps({**base, 'consoles': {'PS4-118': {'regist_key': 'nao-hex'}}}), encoding='utf-8')
    with pytest.raises(ConfigError):
        load(p)
    p.write_text(json.dumps({**base, 'consoles': {'PS4-118': {'passcode': '12'}}}), encoding='utf-8')
    with pytest.raises(ConfigError):
        load(p)
    p.write_text(json.dumps({**base, 'consoles': {'PS4-118': {'regist_key': '2ebf539d', 'passcode': '1234'}}}), encoding='utf-8')
    assert load(p).consoles['PS4-118']['regist_key'] == '2ebf539d'
