"""Controle do chiaki-ng (processo separado; o agente não incorpora código AGPL).

Dois modos:
- Direto (rotas "lan" e "internet_port_forward"): `chiaki [--profile P] [--passcode N] --exit-app-on-stream-exit stream <apelido> <endereço>`.
  O chiaki-ng lê a chave de registro salva pelo apelido (o console precisa estar registrado nele antes).
- PSN (rota "internet_psn"): a conexão remota via PSN só existe na interface gráfica do chiaki-ng. O agente abre a
  interface e executa um roteiro de teclas configurável (`psn_gui_steps`) — EXPERIMENTAL, depende da tela do chiaki-ng.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

from . import winutil

log = logging.getLogger('consoleagent.chiaki')
NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0       # CREATE_NO_WINDOW
HOST_LINE = re.compile(r'^\s*Host:\s*(.+?)\s*$')


class ChiakiError(Exception):
    pass


class ChiakiDriver:
    def __init__(self, path: str, log_dir: Path | None = None):
        self.path = path
        self.log_dir = log_dir or Path(__file__).resolve().parent.parent / 'logs'
        self.proc: subprocess.Popen | None = None
        self.mode: str | None = None              # direct | psn_gui
        self.log_file: Path | None = None
        self.started_at: float | None = None

    # ------------------------------------------------------------ consultas
    @property
    def available(self) -> bool:
        return bool(self.path) and Path(self.path).is_file()

    def list_hosts(self) -> list[str] | None:
        """Apelidos registrados no chiaki-ng (`chiaki list`). None = não foi possível consultar."""
        if not self.available:
            return None
        try:
            r = subprocess.run([self.path, 'list'], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning('chiaki list falhou: %s', e)
            return None
        if r.returncode != 0:
            return None
        return [m.group(1) for ln in (r.stdout or '').splitlines() if (m := HOST_LINE.match(ln))]

    def registered(self, nickname: str) -> bool | None:
        hosts = self.list_hosts()
        if hosts is None:
            return None
        return nickname.strip().lower() in {h.lower() for h in hosts}

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.running else None

    def window(self) -> winutil.Window | None:
        return winutil.main_window(self.pid)

    def log_tail(self, lines: int = 8) -> str:
        if not self.log_file or not self.log_file.is_file():
            return ''
        with self.log_file.open(encoding='utf-8', errors='replace') as f:
            return ' | '.join(x.strip() for x in deque(f, maxlen=lines) if x.strip())[-600:]

    # ------------------------------------------------------------ processo
    def _spawn(self, args: list[str], mode: str) -> None:
        if not self.available:
            raise ChiakiError(f'chiaki-ng não encontrado em {self.path}.')
        self.stop()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f'chiaki-{time.strftime("%Y%m%d-%H%M%S")}.log'
        out = self.log_file.open('w', encoding='utf-8', errors='replace')
        # Registro sem segredos: a senha (passcode) não vai para o log.
        log.info('iniciando chiaki-ng (%s): %s', mode, ' '.join('****' if prev == '--passcode' else a
                                                                for prev, a in zip([''] + args, args)))
        self.proc = subprocess.Popen([self.path, *args], stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        out.close()
        self.mode, self.started_at = mode, time.monotonic()

    def start_direct(self, nickname: str, host: str, passcode: str = '', profile: str = '') -> None:
        if not nickname or not host:
            raise ChiakiError('Apelido do console no chiaki-ng e endereço são obrigatórios.')
        args: list[str] = []
        if profile:
            args += ['--profile', profile]
        if passcode:
            if not re.fullmatch(r'\d{4}', passcode):
                raise ChiakiError('A senha de login do console (passcode) deve ter 4 dígitos.')
            args += ['--passcode', passcode]
        args += ['--exit-app-on-stream-exit', 'stream', nickname, host]
        self._spawn(args, 'direct')

    def start_psn_gui(self, steps: list[str], profile: str = '', window_timeout: float = 40.0,
                      sleep=time.sleep) -> None:
        """Abre a interface do chiaki-ng e executa o roteiro de teclas que inicia a conexão via PSN."""
        if not steps:
            raise ChiakiError('Rota PSN: configure "psn_gui_steps" no config.json do agente (roteiro de teclas que, na tela '
                              'inicial do chiaki-ng, seleciona o console em "Remote Connection via PSN" e conecta). Veja o README.')
        if not winutil.IS_WIN:
            raise ChiakiError('O modo PSN (automação da interface) só funciona no Windows.')
        self._spawn(['--profile', profile] if profile else [], 'psn_gui')
        deadline = time.monotonic() + window_timeout
        w = None
        while time.monotonic() < deadline and self.running:
            w = self.window()
            if w:
                break
            sleep(0.5)
        if not w:
            raise ChiakiError('A janela do chiaki-ng não apareceu. ' + self.log_tail())
        sleep(3)  # a lista de consoles PSN demora a carregar
        run_key_steps(steps, lambda: self.window(), sleep)

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(8)
            except subprocess.TimeoutExpired:
                p.kill()
        self.mode = None


def run_key_steps(steps: list[str], get_window, sleep=time.sleep) -> None:
    """Executa passos: "down", "enter", "wait:3" ... sempre com a janela do chiaki-ng em primeiro plano."""
    for raw in steps:
        step = str(raw).strip().lower()
        if step.startswith('wait:'):
            sleep(float(step.split(':', 1)[1]))
            continue
        w = get_window()
        if not w:
            raise ChiakiError(f'A janela do chiaki-ng sumiu durante o roteiro (passo "{raw}").')
        winutil.focus(w)
        try:
            winutil.press_key(step)
        except ValueError as e:
            raise ChiakiError(str(e)) from e
        sleep(0.6)
