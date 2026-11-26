"""Rota PSN do chiaki-ng: log de sessão (transmissão real x menu aberto), nova tentativa e formato do registro."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consoleagent import chiaki  # noqa: E402
from consoleagent.chiaki import SessionLog, _decode_bytearray  # noqa: E402

from test_parte2 import PSN, FakeChiaki, World, make, until_done  # noqa: E402


def _write(p: Path, *lines):
    with p.open('a', encoding='utf-8') as f:
        for ln in lines:
            f.write(f'[2026-11-24 21:41:31:000] {ln}\n')


def test_log_de_sessao_distingue_conectando_transmitindo_e_encerrada(tmp_path):
    s = SessionLog(time.time(), tmp_path)
    assert s.poll() is None                                      # chiaki-ng aberto no menu, sem sessão
    p = tmp_path / 'chiaki_session_2026-11-24_21-41-31-000.log'
    _write(p, '[I] >> Created session', '[E] remote/stun.h: Failed to receive STUN response')
    assert s.poll() == 'connecting'
    _write(p, '[I] StreamConnection successfully received streaminfo')
    assert s.poll() == 'streaming'
    _write(p, '[I] Session has quit')
    assert s.poll() == 'quit' and 'STUN' in s.last_error


def test_falha_ao_iniciar_pela_psn_conta_como_encerrada(tmp_path):
    s = SessionLog(time.time(), tmp_path)
    p = tmp_path / 'chiaki_session_x.log'
    _write(p, '[I] >> Created session',
           '[E] chiaki_holepunch_session_start: Timed out waiting for holepunch session start notifications.',
           '[E] !! Failed to start session')
    assert s.poll() == 'quit'


def test_log_antigo_nao_conta(tmp_path):
    p = tmp_path / 'chiaki_session_velho.log'
    _write(p, '[I] StreamConnection successfully received streaminfo')
    assert SessionLog(time.time() + 60, tmp_path).poll() is None


def test_bytearray_do_qsettings():
    assert _decode_bytearray('@ByteArray(,\xccD\x90)\x93)') == bytes.fromhex('2ccc44902993')
    if chiaki.winutil.IS_WIN:
        for mac in (bytes.fromhex('2ccc44902993'), bytes.fromhex('00aabbccdd00')):
            value, _ = chiaki._encode_bytearray(mac)
            assert _decode_bytearray(value) == mac               # com byte zero vira REG_BINARY (UTF-16)


class FlakyPsn(FakeChiaki):
    """1ª tentativa: a sessão cai (console acordando); 2ª: transmite."""

    def start(self, t, sleep=None):
        self.started.append('psn')
        self._running = True
        return 'chiaki-ng mandado conectar a "PS4-118".'

    @property
    def running(self):
        if len(self.started) == 1 and self.world.frame_calls >= 2:
            return False
        return self._running


def test_rota_psn_tenta_de_novo_quando_a_primeira_cai():
    w = World(chiaki=FlakyPsn(frames_until_video=4))
    r = until_done(make(w, consoles={'PS4-118': {'nickname': 'PS4-118'}}), 'connect', PSN)
    assert r['ok'] is True, r
    assert w.chiaki.started == ['psn', 'psn'] and 'tentativa 2' in r['message']


def test_rota_psn_desiste_depois_das_tentativas():
    w = World(chiaki=FlakyPsn(frames_until_video=10 ** 9))
    r = until_done(make(w, consoles={'PS4-118': {'nickname': 'PS4-118'}}, stream_timeout_seconds=0.1,
                        psn_connect_attempts=2), 'connect', PSN, tries=200)
    assert r['ok'] is False and len(w.chiaki.started) == 2


def _driver(monkeypatch, mac):
    calls = {}
    monkeypatch.setattr(chiaki.winutil, 'IS_WIN', True)
    monkeypatch.setattr(chiaki, 'registered_mac', lambda n, p='': mac)
    monkeypatch.setattr(chiaki, 'set_autoconnect', lambda m, p='': calls.setdefault('auto', m) or 'anterior')
    monkeypatch.setattr(chiaki, 'restore_autoconnect', lambda prev, p='': calls.setdefault('restored', prev))
    monkeypatch.setattr(chiaki, 'run_key_steps', lambda steps, w, s: calls.setdefault('keys', list(steps)))
    d = chiaki.ChiakiDriver('x')
    monkeypatch.setattr(d, '_spawn', lambda args, mode: setattr(d, 'mode', mode))
    monkeypatch.setattr(d, 'window', lambda: object())
    monkeypatch.setattr(type(d), 'running', property(lambda self: True))
    return d, calls


def test_ps4_pela_psn_desliga_conexao_automatica_e_escolhe_ultimo_da_lista(monkeypatch):
    d, calls = _driver(monkeypatch, bytes(6))
    msg = d.start_psn_gui('PS4-118', [], platform='PS4', sleep=lambda s: None)
    assert calls['auto'] is None and calls['keys'] == list(chiaki.DEFAULT_PS4_PSN_STEPS) and 'restored' in calls
    assert 'lista' in msg


def test_ps5_pela_psn_usa_conexao_automatica_pelo_apelido(monkeypatch):
    mac = bytes.fromhex('2ccc44902993')
    d, calls = _driver(monkeypatch, mac)
    msg = d.start_psn_gui('PS5-01', [], platform='PS5', sleep=lambda s: None)
    assert calls['auto'] == mac and 'keys' not in calls and '2C:CC' in msg
