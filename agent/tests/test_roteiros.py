"""Roteiros de abertura com leitura de tela (sem hardware: tela e controle são dublês)."""
import numpy as np
import pytest
from PIL import Image

from consoleagent import vision
from consoleagent.runtime import Fail, Screen, run_pad_steps


class Pad:
    def __init__(self):
        self.pressed = []

    def press(self, name, hold=0.12):
        self.pressed.append(name)


def _scene(seed=1, w=1280, h=720):
    rng = np.random.default_rng(seed)
    return (rng.random((h, w)) * 255).astype('uint8')


def test_imagem_de_referencia_e_encontrada_na_tela_e_nao_em_outra():
    tela = _scene(1)
    recorte = Image.fromarray(tela[300:400, 500:700])
    ref = vision.decode_reference('jogo', {'png': vision.png_base64(recorte), 'width': 1280})
    assert vision.match_score(Image.fromarray(tela), ref) > 0.9
    assert vision.match_score(Image.fromarray(_scene(2)), ref) < vision.MATCH_THRESHOLD
    # tela em outra escala (janela do chiaki-ng menor): ainda encontra
    menor = Image.fromarray(tela).resize((960, 540))
    assert vision.match_score(menor, ref) > vision.MATCH_THRESHOLD


def test_texto_tolera_acentos_e_erros_pequenos_do_ocr():
    assert vision.contains_text('Biblioteca | Far Cry 5 | Iniciar', 'far cry 5')
    assert vision.contains_text('Seja bem-vindo de volta', 'Seja bem vindo')
    assert vision.contains_text('Grand Theft Auto V', 'Grand Theft Auto 5') is False
    assert vision.contains_text('Far Crv 5', 'Far Cry 5')
    assert vision.contains_text('Far Cry 4', 'Far Cry 5') is False


class FakeScreen(Screen):
    """Tela que muda a cada toque no controle."""

    def __init__(self, pad, screens):
        super().__init__(link=None)
        self.pad, self.screens = pad, screens

    def has_text(self, wanted):
        self.last_text = self.screens[min(len(self.pad.pressed), len(self.screens) - 1)]
        return vision.contains_text(self.last_text, wanted)


def test_navega_ate_o_jogo_pelo_texto_e_confirma():
    pad = Pad()
    screen = FakeScreen(pad, ['Seja bem-vindo', 'Início | TV e vídeo', 'Início | Spotify', 'Início | Far Cry 5', 'Far Cry 5 - Menu'])
    run_pad_steps(pad, ['press_if_text:cross:Seja bem-vindo', 'press_until_text:dpad_right:10:Far Cry 5', 'cross',
                        'wait_text:5:Menu'], sleep=lambda s: None, screen=screen)
    assert pad.pressed == ['cross', 'dpad_right', 'dpad_right', 'cross']
    assert screen.confirmed


def test_falha_quando_o_jogo_nao_aparece():
    pad = Pad()
    screen = FakeScreen(pad, ['Início | TV e vídeo'])
    with pytest.raises(Fail, match='Far Cry 5'):
        run_pad_steps(pad, ['press_until_text:dpad_right:3:Far Cry 5'], sleep=lambda s: None, screen=screen)
    assert pad.pressed == ['dpad_right'] * 3


def test_pula_o_toque_quando_a_tela_nao_esta_presente():
    pad = Pad()
    run_pad_steps(pad, ['press_if_text:cross:Seja bem-vindo', 'ps'], sleep=lambda s: None,
                  screen=FakeScreen(pad, ['Início']))
    assert pad.pressed == ['ps']


class FakeInfo:
    def __init__(self, raw):
        self.address, self.host_id, self.host_name, self.raw = '192.168.0.9', 'ABC123', 'PS4-118', raw


def test_sistema_confirma_o_jogo_aberto_pelo_codigo_ou_nome():
    from consoleagent.runtime import System, Target
    states = [{}, {}, {'running-app-titleid': 'CUSA05904', 'running-app-name': 'Far Cry® 5'}]
    calls = []

    def discover(host, platform, timeout):
        calls.append(host)
        return [FakeInfo(states[min(len(calls) - 1, len(states) - 1)])]

    t = Target(console_id='c1', route='internet_psn', host=None, platform='PS4', identifier='PS4-118', nickname='PS4-118')
    pad, screen = Pad(), Screen(link=None, system=System(t, discover))
    run_pad_steps(pad, ['wait_app:30:CUSA05904'], sleep=lambda s: None, screen=screen)
    assert screen.confirmed and calls[0] is None          # sem IP cadastrado: achou pelo nome na rede local
    assert System(t, discover).is_running('Far Cry 5')
    with pytest.raises(Fail, match='Aberto agora: Far Cry® 5'):
        run_pad_steps(pad, ['wait_app:0:CUSA00001'], sleep=lambda s: None, screen=Screen(link=None, system=System(t, discover)))
