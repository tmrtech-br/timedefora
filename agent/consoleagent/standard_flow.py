"""Abertura padrão do jogo no PS4/PS5, sem roteiro nem imagem: decide o caminho pelo estado do console.

Caminhos (o estado vem da presença PSN e/ou do DDP local, ver presence.py):
1. Console em repouso: a conexão Remote Play acorda (~40 s) e ele para em "Seja bem-vindo" → caminho 2.
2. "Seja bem-vindo" (conta offline na PSN): ✕ no último perfil → menu do console (foco em "Novidades").
3. Menu do console (conta online, sem jogo): → até o ícone do jogo → ✕.
Jogo certo já aberto: só espera ficar pronto. Outro jogo aberto: PS → menu → ícone → ✕ → ✕ (confirma fechar o atual).
No menu do PS4 o 1º ícone à direita de "Novidades" é o último jogo usado; os seguintes, os usados antes.
Confirmação: o title ID informado pelo console precisa ser o esperado; ele surge no início do carregamento, então ainda
espera a imagem assentar antes de liberar o jogador.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .presence import Presence, StateReader, normalize_title


class FlowError(Exception):
    pass


@dataclass
class FlowResult:
    title_id: str
    title_name: str
    path: str                  # perfil+menu | menu | já aberto | outro jogo fechado
    tile: int                  # ícone usado (0 = jogo já estava aberto)
    message: str


def _read(state: StateReader, sleep: Callable, tries: int = 3) -> Presence | None:
    for i in range(tries):
        p = state.read()
        if p is not None:
            return p
        if i < tries - 1:
            sleep(2)
    return None


def _wait_title(state: StateReader, sleep: Callable, clock: Callable, limit: float, ignore: str) -> Presence | None:
    """Espera o console informar um jogo aberto diferente de `ignore` (o que já estava aberto)."""
    deadline = clock() + limit
    while clock() < deadline:
        p = state.read()
        if p is not None and p.title_id and p.title_id != ignore:
            return p
        sleep(3)
    return None


def open_game(pad, state: StateReader, frame_ok: Callable[[], bool], expected: str = '', *, woke: bool = False,
              detect: bool = False, sleep: Callable = time.sleep, clock: Callable = time.monotonic,
              progress: Callable[[str], None] = lambda s: None, max_tiles: int = 4, settle: float = 45.0,
              launch_timeout: float = 75.0) -> FlowResult:
    """Abre `expected` (ex.: CUSA05904) ou, com detect=True, o último jogo usado e informa qual abriu."""
    expected = normalize_title(expected)
    if not detect and not expected:
        raise FlowError('Código do jogo (CUSA/PPSA) não informado: reconheça o jogo no menu Roteiros.')
    if not state.available:
        raise FlowError('Sem como ler o estado do console (conta PSN não vinculada e console fora da rede local).')

    progress('lendo o estado do console')
    p = _read(state, sleep)
    path = 'menu'
    # ------------------------------------------------ "Seja bem-vindo": seleciona o último perfil
    if (p is not None and p.online is False) or ((p is None or p.online is None) and woke):
        path = 'perfil+menu'
        for attempt in (1, 2):
            progress(f'selecionando o perfil (tentativa {attempt})')
            pad.press('cross')
            deadline = clock() + 25
            while clock() < deadline:
                sleep(3)
                p = state.read()
                if p is not None and p.online:
                    break
            if p is not None and p.online:
                break
        if p is not None and p.online is False and p.source == 'psn':
            raise FlowError('A conta continua offline na PSN depois de selecionar o perfil. Confira se o perfil do console '
                            'está com o status "Online" (Perfil > Definir status online) e se não há outra tela aberta.')
        sleep(3)                                            # menu termina de montar
        p = _read(state, sleep) or p

    current = p.title_id if p else ''
    if not detect and current == expected:
        progress('jogo já aberto; conferindo a imagem')
        return _ready(frame_ok, sleep, 3, FlowResult(expected, p.title_name, 'já aberto', 0, 'O jogo já estava aberto.'))

    # ------------------------------------------------ menu do console → ícone do jogo
    first = 2 if current else 1             # outro jogo aberto ocupa o 1º ícone (último usado)
    for tile in range(first, max_tiles + 1):
        progress(f'abrindo o jogo pelo menu (ícone {tile})')
        if current or tile > first or path == 'menu':
            pad.press('ps')                                 # volta ao menu do console (com ou sem jogo aberto)
            sleep(3)
        for _ in range(8):                                  # foco em "Novidades" (primeiro item da fila)
            pad.press('dpad_left')
            sleep(0.3)
        for _ in range(tile):
            pad.press('dpad_right')
            sleep(0.6)
        pad.press('cross')
        if current:
            sleep(2.5)
            pad.press('cross')                              # "Fechar o aplicativo atual?" → OK
        progress('aguardando o console abrir o jogo')
        opened = _wait_title(state, sleep, clock, launch_timeout, current)
        if opened is None:
            raise FlowError(f'O console não informou nenhum jogo aberto em {int(launch_timeout)} s após selecionar o ícone {tile}.')
        if detect or opened.title_id == expected:
            msg = f'{opened.title_name or opened.title_id} ({opened.title_id}) aberto pelo ícone {tile}.'
            result = FlowResult(opened.title_id, opened.title_name, 'outro jogo fechado' if current else path, tile, msg)
            progress('jogo aberto; aguardando carregar')
            return _ready(frame_ok, sleep, settle, result)
        current = opened.title_id                           # abriu outro jogo: tenta o próximo ícone
    raise FlowError(f'O jogo {expected} não estava entre os {max_tiles} últimos jogos usados no console. '
                    'Abra o jogo uma vez no console para ele voltar ao início do menu.')


def _ready(frame_ok: Callable[[], bool], sleep: Callable, settle: float, result: FlowResult) -> FlowResult:
    """O title ID surge no carregamento: espera assentar e exige imagem do console antes de liberar."""
    sleep(settle)
    for _ in range(10):
        if frame_ok():
            return result
        sleep(3)
    raise FlowError(f'{result.title_id} aberto, mas sem imagem do console depois do carregamento.')
