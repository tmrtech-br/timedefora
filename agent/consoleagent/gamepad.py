"""Controle virtual DualShock 4 (ViGEmBus + biblioteca vgamepad).

O chiaki-ng enxerga esse controle como um DS4 físico ligado ao PC e repassa os comandos ao console.
Comandos do JOGADOR passam por `apply()` (botão PS/touchpad bloqueados). Roteiros internos de preparação
(abrir o jogo) usam `press()` e podem usar o botão PS — nunca expostos ao jogador.
"""
from __future__ import annotations

import time

PLAYER_BLOCKED = {'ps', 'home', 'guide', 'touchpad', 'touchpad_settings'}
DPAD = {'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right'}


class GamepadUnavailable(Exception):
    pass


class VirtualPad:
    """Implementação real (Windows + driver ViGEmBus)."""

    def __init__(self):
        try:
            import vgamepad as vg
        except Exception as e:  # ImportError ou falha do driver ao carregar
            raise GamepadUnavailable('Controle virtual indisponível: instale o driver ViGEmBus e o pacote vgamepad '
                                     f'(pip install vgamepad). Detalhe: {e}') from e
        try:
            self._pad = vg.VDS4Gamepad()
        except Exception as e:
            raise GamepadUnavailable(f'Não foi possível criar o controle virtual (ViGEmBus instalado?): {e}') from e
        B, S, D = vg.DS4_BUTTONS, vg.DS4_SPECIAL_BUTTONS, vg.DS4_DPAD_DIRECTIONS
        self._btn = {'cross': B.DS4_BUTTON_CROSS, 'circle': B.DS4_BUTTON_CIRCLE, 'square': B.DS4_BUTTON_SQUARE,
                     'triangle': B.DS4_BUTTON_TRIANGLE, 'l1': B.DS4_BUTTON_SHOULDER_LEFT, 'r1': B.DS4_BUTTON_SHOULDER_RIGHT,
                     'l2': B.DS4_BUTTON_TRIGGER_LEFT, 'r2': B.DS4_BUTTON_TRIGGER_RIGHT, 'l3': B.DS4_BUTTON_THUMB_LEFT,
                     'r3': B.DS4_BUTTON_THUMB_RIGHT, 'options': B.DS4_BUTTON_OPTIONS, 'share': B.DS4_BUTTON_SHARE}
        self._special = {'ps': S.DS4_SPECIAL_BUTTON_PS, 'touchpad': S.DS4_SPECIAL_BUTTON_TOUCHPAD}
        self._dirs = {(0, -1): D.DS4_BUTTON_DPAD_NORTH, (1, -1): D.DS4_BUTTON_DPAD_NORTHEAST, (1, 0): D.DS4_BUTTON_DPAD_EAST,
                      (1, 1): D.DS4_BUTTON_DPAD_SOUTHEAST, (0, 1): D.DS4_BUTTON_DPAD_SOUTH, (-1, 1): D.DS4_BUTTON_DPAD_SOUTHWEST,
                      (-1, 0): D.DS4_BUTTON_DPAD_WEST, (-1, -1): D.DS4_BUTTON_DPAD_NORTHWEST, (0, 0): D.DS4_BUTTON_DPAD_NONE}
        self._dpad: set[str] = set()
        self._axes = {'left_x': 0.0, 'left_y': 0.0, 'right_x': 0.0, 'right_y': 0.0}

    # ------------------------------------------------------------ baixo nível
    def _set(self, name: str, pressed: bool) -> None:
        p = self._pad
        if name in DPAD:
            (self._dpad.add if pressed else self._dpad.discard)(name)
            x = ('dpad_right' in self._dpad) - ('dpad_left' in self._dpad)
            y = ('dpad_down' in self._dpad) - ('dpad_up' in self._dpad)
            p.directional_pad(direction=self._dirs[(x, y)])
        elif name in self._special:
            (p.press_special_button if pressed else p.release_special_button)(special_button=self._special[name])
        elif name in self._btn:
            (p.press_button if pressed else p.release_button)(button=self._btn[name])
            if name == 'l2':
                p.left_trigger(value=255 if pressed else 0)
            elif name == 'r2':
                p.right_trigger(value=255 if pressed else 0)
        else:
            raise ValueError(f'Botão desconhecido: {name}')
        p.update()

    def _axis(self, name: str, value: float) -> None:
        if name not in self._axes:
            raise ValueError(f'Eixo desconhecido: {name}')
        self._axes[name] = max(-1.0, min(1.0, float(value)))
        a = self._axes
        self._pad.left_joystick_float(x_value_float=a['left_x'], y_value_float=a['left_y'])
        self._pad.right_joystick_float(x_value_float=a['right_x'], y_value_float=a['right_y'])
        self._pad.update()

    # ------------------------------------------------------------ alto nível
    def apply(self, command: dict) -> None:
        """Comando do jogador (já validado pela API; validado de novo aqui)."""
        kind, name = command.get('type'), str(command.get('name', '')).lower()
        if name in PLAYER_BLOCKED:
            raise PermissionError('Comando bloqueado por segurança.')
        if kind == 'button':
            self._set(name, bool(command.get('pressed', True)))
        elif kind == 'axis':
            self._axis(name, float(command.get('value', 0)))
        else:
            raise ValueError('Tipo de comando inválido.')

    def press(self, name: str, hold: float = 0.12) -> None:
        """Toque curto (uso interno: roteiros de preparação/testes)."""
        self._set(name, True)
        time.sleep(hold)
        self._set(name, False)

    def reset(self) -> None:
        """Solta tudo (fim de sessão / revogação)."""
        self._dpad.clear()
        self._axes = dict.fromkeys(self._axes, 0.0)
        self._pad.reset()
        self._pad.update()

    def close(self) -> None:
        try:
            self.reset()
        finally:
            del self._pad
