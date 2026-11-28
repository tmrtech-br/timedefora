"""Fluxo padrão de abertura do jogo (sem hardware): um PS4 simulado reage aos botões e informa o estado."""
import pytest

from consoleagent.presence import Presence, StateReader, normalize_title, parse_profile2
from consoleagent.standard_flow import FlowError, open_game


class FakePS4:
    """Telas: welcome → home (foco 0 = Novidades) → jogo. recent = jogos do menu, do mais recente ao mais antigo."""

    def __init__(self, screen='welcome', recent=('CUSA05904', 'CUSA00411'), running='', appear_offline=False):
        self.screen, self.recent, self.running = screen, list(recent), running
        self.appear_offline, self.focus, self.presses, self.dialog, self.drop = appear_offline, 0, [], None, []
        if running:
            self.recent.remove(running) if running in self.recent else None
            self.recent.insert(0, running)

    # controle
    def press(self, name, hold=0.12):
        self.presses.append(name)
        if self.drop and name in self.drop:              # toque perdido pela rede
            self.drop.remove(name)
            return
        if self.dialog:
            if name == 'cross':
                self._launch(self.dialog)
            self.dialog = None
            return
        if self.screen == 'welcome':
            if name == 'ps':                              # "pressione PS" → perfis
                self.screen = 'profiles'
        elif self.screen == 'profiles':
            if name == 'cross':
                self.screen, self.focus = 'home', 0
        elif self.screen == 'game' and name == 'ps':
            self.screen, self.focus = 'home', 1          # volta ao menu com foco no jogo aberto
        elif self.screen == 'home':
            if name == 'dpad_left':
                self.focus = max(0, self.focus - 1)
            elif name == 'dpad_right':
                self.focus = min(len(self.recent), self.focus + 1)
            elif name == 'cross' and self.focus >= 1:
                chosen = self.recent[self.focus - 1]
                if chosen == self.running:
                    self.screen = 'game'
                elif self.running:
                    self.dialog = chosen                  # "Fechar o aplicativo atual?"
                else:
                    self._launch(chosen)

    def _launch(self, title):
        self.running, self.screen = title, 'game'
        self.recent.remove(title)
        self.recent.insert(0, title)

    # estado (presença)
    def read(self):
        online = self.screen not in ('welcome', 'profiles') and not self.appear_offline
        return Presence(online, self.running if online else '', 'Jogo ' + self.running if self.running else '', 'psn')


def run(ps4, expected='CUSA05904', **kw):
    clock = [0.0]

    def sleep(s):
        clock[0] += s

    return open_game(ps4, StateReader(ps4), lambda: True, expected, sleep=sleep, clock=lambda: clock[0], settle=0, **kw)


def test_caminhos_1_e_2_seleciona_o_perfil_e_abre_o_ultimo_jogo():
    ps4 = FakePS4('welcome')
    r = run(ps4)
    assert r.title_id == 'CUSA05904' and r.path == 'perfil+menu' and r.tile == 1
    assert ps4.presses[:2] == ['ps', 'cross'] and ps4.presses.count('ps') == 1
    assert 'dpad_left' not in ps4.presses                 # depois do perfil o foco já está em "Novidades"


def test_caminho_3_no_menu_abre_o_jogo():
    ps4 = FakePS4('home')
    ps4.focus = 2                                         # foco em qualquer lugar do menu
    r = run(ps4)
    assert r.title_id == 'CUSA05904' and r.path == 'menu'


def test_jogo_certo_ja_aberto_nao_aperta_nada():
    ps4 = FakePS4('game', running='CUSA05904')
    r = run(ps4)
    assert r.path == 'já aberto' and ps4.presses == []


def test_outro_jogo_aberto_fecha_e_abre_o_certo():
    ps4 = FakePS4('game', recent=('CUSA05904', 'CUSA00411'), running='CUSA00411')
    r = run(ps4)
    assert r.title_id == 'CUSA05904' and r.tile == 2 and r.path == 'outro jogo fechado'


def test_jogo_esperado_nao_e_o_ultimo_tenta_os_proximos_icones():
    ps4 = FakePS4('home', recent=('CUSA00411', 'CUSA05904'))
    r = run(ps4)
    assert r.title_id == 'CUSA05904' and r.tile == 2


def test_perfil_aparecendo_offline_falha_com_orientacao():
    with pytest.raises(FlowError, match='status "Online"'):
        run(FakePS4('welcome', appear_offline=True))


def test_jogo_fora_dos_ultimos_icones_falha():
    with pytest.raises(FlowError, match='não estava entre'):
        run(FakePS4('home', recent=('CUSA00411', 'CUSA00001', 'CUSA00002', 'CUSA00003', 'CUSA00004')), max_tiles=3)


def test_reconhecer_abre_o_ultimo_jogo_e_informa():
    ps4 = FakePS4('welcome', recent=('CUSA00411',))
    r = run(ps4, expected='', detect=True)
    assert r.title_id == 'CUSA00411' and r.title_name == 'Jogo CUSA00411'


def test_le_a_presenca_da_psn_e_normaliza_o_codigo():
    p = parse_profile2({'profile': {'onlineId': 'x', 'primaryOnlineStatus': 'online', 'presences': [
        {'onlineStatus': 'online', 'platform': 'PS4', 'npTitleId': 'CUSA05904_00', 'titleName': 'Far Cry® 5'}]}})
    assert (p.online, p.title_id, p.title_name) == (True, 'CUSA05904', 'Far Cry® 5')
    p = parse_profile2({'profile': {'presences': [{'onlineStatus': 'offline'}]}})
    assert p.online is False and p.title_id == ''
    assert normalize_title('ppsa01234_00') == 'PPSA01234' and normalize_title('lixo') == ''


def test_falha_da_psn_nao_vira_offline():
    from consoleagent.presence import PsnPresence

    async def fetch(url):
        return 403, None
    assert PsnPresence('conta', fetch=fetch).read() is None


def test_toque_perdido_pela_rede_refaz_a_navegacao():
    ps4 = FakePS4('home')
    ps4.drop = ['cross']                                  # o primeiro ✕ no ícone se perde
    r = run(ps4)
    assert r.title_id == 'CUSA05904' and r.tile == 1
