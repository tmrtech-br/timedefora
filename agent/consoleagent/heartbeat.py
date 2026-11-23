"""Heartbeat: avisa a API LocaPlay que o agente está online (POST /agents/heartbeat com o token agente→API)."""
from __future__ import annotations

import logging
import threading

import httpx

from . import VERSION
from .config import AgentConfig

log = logging.getLogger('consoleagent.heartbeat')


def send_once(cfg: AgentConfig, client: httpx.Client | None = None) -> tuple[bool, str]:
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        r = client.post(f'{cfg.api_url}/agents/heartbeat', json={'agent_version': VERSION, 'consoles': []},
                        headers={'Authorization': f'Bearer {cfg.agent_token}'})
        if r.status_code == 200:
            return True, 'ok'
        try:
            detail = r.json().get('detail') or r.text
        except ValueError:
            detail = r.text
        return False, f'API respondeu {r.status_code}: {detail}'
    except httpx.HTTPError as e:
        return False, f'API inacessível ({e.__class__.__name__}) em {cfg.api_url}'
    finally:
        if own:
            client.close()


class Heartbeat(threading.Thread):
    def __init__(self, cfg: AgentConfig):
        super().__init__(name='heartbeat', daemon=True)
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.last_ok: bool | None = None

    def run(self) -> None:
        with httpx.Client(timeout=10) as client:
            while not self.stop_event.is_set():
                ok, msg = send_once(self.cfg, client)
                if ok != self.last_ok:  # só registra mudanças, para não poluir o log
                    (log.info if ok else log.warning)('heartbeat %s', 'OK — agente online no painel' if ok else f'FALHOU: {msg}')
                    self.last_ok = ok
                self.stop_event.wait(self.cfg.heartbeat_seconds)

    def stop(self) -> None:
        self.stop_event.set()
