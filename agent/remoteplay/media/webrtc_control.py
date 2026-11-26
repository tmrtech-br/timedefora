# SPDX-License-Identifier: AGPL-3.0-only
"""Fila isolada de comandos recebidos por DataChannel WebRTC.

O DataChannel herda o controle de acesso da oferta WebRTC (session_id, input token
validado no backend). Nenhum botão de outro console é acessado.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable

BUTTONS = frozenset(('cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l2', 'r2',
                     'l3', 'r3', 'options', 'share', 'dpad_up', 'dpad_down',
                     'dpad_left', 'dpad_right', 'touchpad'))
AXES = frozenset(('left_x', 'left_y', 'right_x', 'right_y'))


class ControlProtocolError(ValueError):
    pass


def parse_command(data: str | bytes) -> dict:
    if not isinstance(data, (str, bytes)) or len(data) > 512:
        raise ControlProtocolError('Comando WebRTC inválido ou excessivamente grande.')
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise ControlProtocolError('Comando WebRTC não é JSON válido.') from exc
    if not isinstance(obj, dict) or set(obj) - {'type', 'name', 'value', 'pressed', 'seq'}:
        raise ControlProtocolError('Comando WebRTC contém campos não permitidos.')
    kind, name = obj.get('type'), obj.get('name')
    seq = obj.get('seq')
    if seq is not None and (type(seq) is not int or not 0 < seq <= 2**53):
        raise ControlProtocolError('Sequência de controle inválida.')
    if kind == 'button' and name in BUTTONS and type(obj.get('pressed', True)) is bool:
        return {'type': kind, 'name': name, 'pressed': obj.get('pressed', True), **({'seq': seq} if seq is not None else {})}
    if kind == 'axis' and name in AXES and type(obj.get('value')) in (int, float):
        value = float(obj['value'])
        if math.isfinite(value) and -1 <= value <= 1:
            return {'type': kind, 'name': name, 'value': value, **({'seq': seq} if seq is not None else {})}
    raise ControlProtocolError('Botão ou eixo WebRTC inválido ou bloqueado.')


class ControlChannel:
    """Fila pequena e um consumidor para preservar a ordem por sessão.

    Rejeita rajadas grandes ao invés de acumular latência. callback acessa
    SOMENTE o runtime do console associado àquela oferta WebRTC.
    """
    def __init__(self, callback: Callable[[dict], object], *, max_rate=120, max_queue=64):
        self.callback = callback
        self.queue = asyncio.Queue(maxsize=max_queue)
        self.max_rate = max_rate
        self.tokens = float(max_rate)
        self.last = time.monotonic()
        self.closed = False
        self.accepted = 0
        self.rejected = 0
        self.worker: asyncio.Task | None = None
        self.last_error = ''
        self.last_seq: dict[tuple[str, str], int] = {}

    def start(self):
        if not self.worker:
            self.worker = asyncio.create_task(self._consume())
        return self

    def submit(self, raw: str | bytes) -> bool:
        if self.closed:
            return False
        now = time.monotonic()
        self.tokens = min(float(self.max_rate), self.tokens + (now - self.last) * self.max_rate)
        self.last = now
        if self.tokens < 1:
            self.rejected += 1
            return False
        try:
            command = parse_command(raw)
            seq = command.pop('seq', None)
            if seq is not None:
                key = (command['type'], command['name'])
                if seq <= self.last_seq.get(key, 0):
                    # Duplicata ou pacote atrasado no canal unordered.
                    return False
            self.queue.put_nowait(command)
            if seq is not None:
                self.last_seq[key] = seq
        except (ControlProtocolError, asyncio.QueueFull):
            self.rejected += 1
            return False
        self.tokens -= 1
        self.accepted += 1
        return True

    async def _consume(self):
        while not self.closed:
            command = await self.queue.get()
            try:
                # Mesmo callback thread-safe de input HTTP; nunca bloquear o loop WebRTC.
                await asyncio.to_thread(self.callback, command)
            except (PermissionError, ValueError, RuntimeError) as exc:
                self.last_error = exc.__class__.__name__
            except Exception as exc:  # erro isolado na sessão
                self.last_error = exc.__class__.__name__
            finally:
                self.queue.task_done()

    async def stop(self):
        self.closed = True
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
            self.worker = None
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
