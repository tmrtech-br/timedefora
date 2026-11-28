"""Roteiros de abertura dos jogos (por console): validação, leitura para a preparação e chamadas de teste ao agente.

Formato dos passos (o mesmo do config.json do agente), um texto por passo:
- botão ("ps", "cross", "dpad_right"…), "wait:SEGUNDOS", "hold:BOTÃO:SEGUNDOS"
- "wait_text:SEGUNDOS:TEXTO", "wait_image:SEGUNDOS:IMAGEM"          — espera aparecer na tela (senão falha)
- "press_until_text:BOTÃO:MÁX:TEXTO", "press_until_image:BOTÃO:MÁX:IMAGEM" — aperta até aparecer
- "press_if_text:BOTÃO:TEXTO", "press_if_image:BOTÃO:IMAGEM"        — aperta só se estiver na tela
- "boot:CUSA00000"                                                 — abre o jogo pelo código (PS4 na rede local)
- "wait_app:SEGUNDOS:CUSA00000"                                    — o console confirma o jogo aberto (rede local)
"""
from __future__ import annotations

import base64
import binascii
import re

from ..core.errors import unprocessable

BUTTONS = ('cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l2', 'r2', 'l3', 'r3', 'options', 'share', 'ps', 'touchpad',
           'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right')
MAX_STEPS, MAX_IMAGES, MAX_IMAGE_BYTES = 60, 8, 300_000
IMAGE_NAME = re.compile(r'^[a-z0-9][a-z0-9_-]{0,39}$')
_NUM = r'(\d+(?:\.\d+)?)'
_BTN = '(' + '|'.join(BUTTONS) + ')'
PATTERNS = [
    re.compile(rf'^{_BTN}$'),
    re.compile(rf'^wait:{_NUM}$'),
    re.compile(rf'^hold:{_BTN}:{_NUM}$'),
    re.compile(rf'^wait_(text|image):{_NUM}:(.+)$'),
    re.compile(rf'^press_until_(text|image):{_BTN}:(\d+):(.+)$'),
    re.compile(rf'^press_if_(text|image):{_BTN}:(.+)$'),
    re.compile(r'^boot:([A-Z]{4}\d{5})$'),
    re.compile(rf'^wait_app:{_NUM}:(.+)$'),
]


def _step_error(i: int, raw: str, why: str):
    raise unprocessable('invalid_step', f'Passo {i} ("{raw[:60]}"): {why}')


def validate(steps: list, images: dict) -> tuple[list[str], dict]:
    if not isinstance(steps, list) or not isinstance(images, dict):
        raise unprocessable('invalid_script', 'Roteiro inválido.')
    if len(steps) > MAX_STEPS:
        raise unprocessable('too_many_steps', f'Use no máximo {MAX_STEPS} passos.')
    if len(images) > MAX_IMAGES:
        raise unprocessable('too_many_images', f'Use no máximo {MAX_IMAGES} imagens de referência.')
    clean_images = {}
    for name, data in images.items():
        if not IMAGE_NAME.match(str(name)):
            raise unprocessable('invalid_image', f'Nome de imagem "{name}": use letras minúsculas, números, "-" ou "_".')
        try:
            raw = base64.b64decode(str((data or {}).get('png') or ''), validate=True)
            width = int((data or {}).get('width') or 0)
        except (binascii.Error, ValueError, TypeError, AttributeError):
            raise unprocessable('invalid_image', f'Imagem "{name}" inválida.')
        if not raw.startswith(b'\x89PNG') or len(raw) > MAX_IMAGE_BYTES or not 160 <= width <= 3840:
            raise unprocessable('invalid_image', f'Imagem "{name}" inválida (PNG de até {MAX_IMAGE_BYTES // 1000} KB).')
        clean_images[str(name)] = {'png': base64.b64encode(raw).decode('ascii'), 'width': width}
    clean = []
    for i, raw in enumerate(steps, 1):
        text = ' '.join(str(raw or '').split())
        if not text:
            continue
        head, sep, rest = text.partition(':')
        normalized = head.lower() + sep + rest
        # os botões dentro do passo também em minúsculas; o texto procurado fica como foi digitado
        if head.lower().startswith(('press_until_', 'press_if_', 'hold')):
            button, sep2, tail = rest.partition(':')
            normalized = head.lower() + sep + button.lower() + sep2 + tail
        if '_image' in head.lower():
            normalized = normalized.lower()                  # nomes de imagem são sempre minúsculos
        if head.lower() == 'boot':
            normalized = 'boot:' + rest.strip().upper()      # código do jogo: CUSA05904
        match = next((m for p in PATTERNS if (m := p.match(normalized))), None)
        if not match:
            _step_error(i, text, 'formato não reconhecido.')
        if head.lower().startswith(('wait_image', 'press_until_image', 'press_if_image')):
            name = normalized.rsplit(':', 1)[1]
            if name not in clean_images:
                _step_error(i, text, f'a imagem "{name}" não foi cadastrada.')
        if head.lower().startswith('wait') and float(normalized.split(':')[1]) > 180:
            _step_error(i, text, 'espera máxima de 180 segundos.')
        if head.lower().startswith('press_until_') and int(normalized.split(':')[2]) > 60:
            _step_error(i, text, 'no máximo 60 toques.')
        clean.append(normalized)
    return clean, clean_images


TITLE_RE = re.compile(r'^[A-Z]{4}\d{5}$')


def _row(conn, console_id, game_id):
    return conn.execute('select steps, images, title_id, settle_seconds from game_launch_scripts where console_id=%s and game_id=%s',
                        (console_id, game_id)).fetchone()


def for_console(conn, console_id, game_id) -> dict | None:
    """Roteiro salvo para o jogo neste console (passos extras; enviado ao agente na preparação)."""
    row = _row(conn, console_id, game_id)
    if not row or not row['steps']:
        return None
    return {'steps': list(row['steps']), 'images': dict(row['images'] or {})}


def game_payload(conn, console_id, game: dict) -> dict:
    """Jogo como o agente espera. Com o código do jogo reconhecido, o agente usa o fluxo padrão (menu + confirmação
    pelo console); sem ele, o roteiro do painel ou do config.json do agente."""
    from .settings_store import get_settings
    out = {'id': str(game.get('id') or ''), 'slug': game.get('slug'), 'title': game.get('title'),
           'max_tiles': int(get_settings(conn).get('game_detect_max_tiles', 5) or 5)}
    row = _row(conn, console_id, game.get('id')) if game.get('id') else None
    if row and row['title_id']:
        out['title_id'] = row['title_id']
        if row['settle_seconds'] is not None:
            out['settle_seconds'] = row['settle_seconds']
    elif row and row['steps']:
        out['launch'] = {'steps': list(row['steps']), 'images': dict(row['images'] or {})}
    return out
