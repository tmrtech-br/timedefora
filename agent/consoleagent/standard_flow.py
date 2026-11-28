"""Abertura padrão do jogo no PS4/PS5, sem roteiro nem imagem: decide o caminho pelo estado do console.

Caminhos (o estado vem da presença PSN e/ou do DDP local, ver presence.py):
1. Console em repouso: a conexão Remote Play acorda (~40 s) e ele para em "Seja bem-vindo" → caminho 2.
2. "Seja bem-vindo… pressione PS" (conta offline na PSN): PS mostra os perfis (último já selecionado) → ✕ → menu
   do console (foco em "Novidades").
3. Menu do console (conta online, sem jogo): → até o ícone do jogo → ✕.
Jogo certo já aberto: só espera ficar pronto. Outro jogo aberto: PS → menu → ícone → ✕ → ✕ (confirma fechar o atual).
No menu do PS4 a fila começa em "Store", depois "Novidades"; o 1º ícone à direita de "Novidades" é o último jogo usado
(visto em PS4 real, 28/11/2026). Depois de entrar no perfil o foco já está em "Novidades".
Confirmação: o title ID informado pelo console precisa ser o esperado; ele surge no início do carregamento, então ainda
espera a imagem assentar antes de liberar o jogador.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .presence import Presence, StateReader, normalize_title


class FlowError(Exception):
    def __init__(self, message: str, seen: list | None = None):
        super().__init__(message)
        self.seen = seen or []                   # jogos abertos no caminho: [{title_id, title_name}]


def names_match(console_name: str, wanted: str) -> bool:
    """Nome informado pelo console x nome cadastrado (ignora acentos, ®/™, maiúsculas; números precisam bater)."""
    from .vision import contains_text
    return bool(console_name and wanted) and (contains_text(console_name, wanted) or contains_text(wanted, console_name))


HOLD, GAP = 0.2, 0.6     # pela PSN (internet) toques curtos demais se perdem; o "soltar" é reenviado (links.DirectPad.press)


_trace: Callable[[str], None] = lambda label: None


def _tap(pad, name: str, sleep: Callable, gap: float = GAP) -> None:
    pad.press(name, HOLD)
    sleep(gap)
    _trace(name)                                   # diagnóstico: imagem da tela depois de cada toque


@dataclass
class FlowResult:
    title_id: str
    title_name: str
    path: str                  # perfil+menu | menu | já aberto | outro jogo fechado
    tile: int                  # ícone usado (0 = jogo já estava aberto)
    message: str
    seen: list | None = None   # jogos abertos no caminho (reconhecimento)


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
              progress: Callable[[str], None] = lambda s: None, max_tiles: int = 5, settle: float = 45.0,
              expected_name: str = '',
              launch_timeout: float = 75.0, trace: Callable[[str], None] | None = None) -> FlowResult:
    """Abre `expected` (ex.: CUSA05904). Com detect=True, procura pelo nome (`expected_name`) abrindo os últimos jogos
    usados, um ícone por vez (fecha o errado e tenta o próximo), e informa o código; sem nome, aceita o 1º que abrir."""
    global _trace
    _trace = trace or (lambda label: None)
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
            _tap(pad, 'ps', sleep, 4)                       # "pressione PS": mostra os perfis
            _tap(pad, 'cross', sleep)
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
    tile, retried, seen = first, False, []
    if current:
        seen.append({'title_id': current, 'title_name': p.title_name if p else ''})
        if detect and names_match(p.title_name if p else '', expected_name):
            return _ready(frame_ok, sleep, 3, FlowResult(current, p.title_name, 'já aberto', 0, 'O jogo já estava aberto.', seen))
    while tile <= max_tiles:
        progress(f'abrindo o jogo pelo menu (ícone {tile})' + (' — nova tentativa' if retried else ''))
        if current or tile > first or path == 'menu' or retried:
            _tap(pad, 'ps', sleep, 3)                       # volta ao menu do console (com ou sem jogo aberto)
        steps = tile                                        # a partir de "Novidades"
        if path != 'perfil+menu' or tile > first or retried:
            for _ in range(6):                              # vai ao início da fila ("Store")
                _tap(pad, 'dpad_left', sleep, 0.45)
            steps = tile + 1                                # Store → Novidades → jogos
        for _ in range(steps):
            _tap(pad, 'dpad_right', sleep)
        _tap(pad, 'cross', sleep, 2.0)
        if current:
            _tap(pad, 'cross', sleep)                       # "Fechar o aplicativo atual?" → OK
        progress('aguardando o console abrir o jogo')
        opened = _wait_title(state, sleep, clock, launch_timeout, current)
        if opened is None:
            if not retried:                                 # toque perdido pela rede: refaz a navegação uma vez
                retried = True
                continue
            raise FlowError(f'O console não informou nenhum jogo aberto em {int(launch_timeout)} s após selecionar o ícone {tile} '
                            '(duas tentativas). Confira a tela do console.', seen)
        retried = False
        seen.append({'title_id': opened.title_id, 'title_name': opened.title_name})
        ok = (names_match(opened.title_name, expected_name) if expected_name else True) if detect else opened.title_id == expected
        if ok:
            msg = f'{opened.title_name or opened.title_id} ({opened.title_id}) aberto pelo ícone {tile}.'
            result = FlowResult(opened.title_id, opened.title_name, 'outro jogo fechado' if current else path, tile, msg, seen)
            progress('jogo aberto; aguardando carregar')
            return _ready(frame_ok, sleep, settle, result)
        current = opened.title_id                           # abriu outro jogo: tenta o próximo ícone
        tile += 1
    names = ', '.join(f"{s['title_name'] or s['title_id']} ({s['title_id']})" for s in seen) or 'nenhum'
    wanted = expected_name if detect else expected
    raise FlowError(f'"{wanted}" não estava entre os {max_tiles} últimos jogos do menu do console. Jogos abertos: {names}. '
                    'Abra o jogo uma vez no console para ele voltar ao início do menu, ou escolha o jogo certo na lista.', seen)


def _ready(frame_ok: Callable[[], bool], sleep: Callable, settle: float, result: FlowResult) -> FlowResult:
    """O title ID surge no carregamento: espera assentar e exige imagem do console antes de liberar."""
    sleep(settle)
    for _ in range(10):
        if frame_ok():
            return result
        sleep(3)
    raise FlowError(f'{result.title_id} aberto, mas sem imagem do console depois do carregamento.')
