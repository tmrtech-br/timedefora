"""Controle do chiaki-ng (processo separado; o agente não incorpora código AGPL).

Dois modos:
- Direto (rotas "lan" e "internet_port_forward"): `chiaki [--profile P] [--passcode N] --exit-app-on-stream-exit stream <apelido> <endereço>`.
  O chiaki-ng lê a chave de registro salva pelo apelido (o console precisa estar registrado nele antes).
- PSN (rota "internet_psn"): a conexão remota via PSN só existe na interface gráfica do chiaki-ng. Antes de abrir a
  interface, o agente grava nas configurações do chiaki-ng o console a conectar automaticamente ("auto_connect_mac",
  recurso nativo do chiaki-ng que escolhe o console pelo apelido — nunca "o primeiro da lista") e desliga as perguntas
  da tela inicial. Sem o console no registro do chiaki-ng, cai no roteiro de teclas `psn_gui_steps` (legado).

A interface do chiaki-ng fica aberta mesmo sem transmissão (menu de consoles), então "janela com imagem" não prova
conexão: no modo PSN o estado real vem do log de sessão do chiaki-ng (%APPDATA%/Chiaki/Chiaki/log).
"""
from __future__ import annotations

import logging
import os
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
REG_ROOT = r'Software\Chiaki'
# PS4 pela PSN: espera a lista da PSN carregar (renova o token + consulta a Sony), ↑ = último item (PSN), Enter = conectar.
DEFAULT_PS4_PSN_STEPS = ('wait:12', 'up', 'enter')


class ChiakiError(Exception):
    pass


# ===================================================================================  configurações do chiaki-ng
# O chiaki-ng usa QSettings (registro do Windows): HKCU\Software\Chiaki\Chiaki (ou Chiaki-<perfil>).
# QByteArray é gravado como texto "@ByteArray(...)" com cada byte num caractere; com byte zero vira REG_BINARY (UTF-16).
def _reg_key(profile: str = '') -> str:
    return REG_ROOT + '\\' + (f'Chiaki-{profile}' if profile else 'Chiaki')


def _decode_bytearray(value) -> bytes | None:
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode('utf-16-le', errors='ignore').rstrip('\x00')
    if not isinstance(value, str) or not value.startswith('@ByteArray(') or not value.endswith(')'):
        return None
    try:
        return value[len('@ByteArray('):-1].encode('latin-1')
    except UnicodeEncodeError:
        return None


def _encode_bytearray(data: bytes):
    """(valor, tipo) para winreg, no formato que o QSettings lê."""
    import winreg
    text = '@ByteArray(' + data.decode('latin-1') + ')'
    if '\x00' in text:
        return text.encode('utf-16-le'), winreg.REG_BINARY
    return text, winreg.REG_SZ


def registered_mac(nickname: str, profile: str = '') -> bytes | None:
    """MAC (6 bytes) do console registrado no chiaki-ng com este apelido; None se não achar (ou fora do Windows)."""
    if not winutil.IS_WIN or not nickname:
        return None
    import winreg
    want = nickname.strip().lower()
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _reg_key(profile) + r'\registered_hosts')
    except OSError:
        return None
    with root:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, sub) as k:
                    nick = str(winreg.QueryValueEx(k, 'server_nickname')[0] or '')
                    mac = _decode_bytearray(winreg.QueryValueEx(k, 'server_mac')[0])
            except OSError:
                continue
            if nick.strip().lower() == want and mac and len(mac) == 6:
                return mac
    return None


def set_autoconnect(mac: bytes | None, profile: str = '', quiet: bool = True):
    """Grava o console de conexão automática. Devolve o valor anterior (bruto) para restaurar depois."""
    import winreg
    path = _reg_key(profile) + r'\settings'
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
        try:
            previous = winreg.QueryValueEx(k, 'auto_connect_mac')
        except OSError:
            previous = None
        if mac is None:
            try:
                winreg.DeleteValue(k, 'auto_connect_mac')
            except OSError:
                pass
        else:
            value, kind = _encode_bytearray(mac)
            winreg.SetValueEx(k, 'auto_connect_mac', 0, kind, value)
        if quiet:   # perguntas da tela inicial ("Steam"/"PSN", com "lembrar depois") travariam a automação
            for name in ('remote_play_ask', 'add_steam_shortcut_ask'):
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, 'false')
    return previous


def restore_autoconnect(previous, profile: str = '') -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _reg_key(profile) + r'\settings', 0, winreg.KEY_WRITE) as k:
            if previous is None:
                try:
                    winreg.DeleteValue(k, 'auto_connect_mac')
                except OSError:
                    pass
            else:
                winreg.SetValueEx(k, 'auto_connect_mac', 0, previous[1], previous[0])
    except OSError as e:
        log.warning('não foi possível restaurar auto_connect_mac do chiaki-ng: %s', e)


# ===================================================================================  log de sessão do chiaki-ng
def session_log_dir() -> Path:
    return Path(os.getenv('APPDATA') or Path.home()) / 'Chiaki' / 'Chiaki' / 'log'


class SessionLog:
    """Acompanha o log de sessão mais novo do chiaki-ng criado depois de `since` (relógio de parede).

    Estados: None (nenhuma sessão iniciada) · connecting · streaming · quit.
    """
    STREAMING = ('StreamConnection successfully received streaminfo',)
    # "Failed to start session": a PSN não fechou a conexão (ex.: console ainda acordando). O chiaki-ng volta ao menu
    # sem escrever "Session has quit", então sem isto o agente só perceberia no fim do prazo.
    QUIT = ('Session has quit', 'Failed to start session', 'Failed to create session')

    def __init__(self, since: float, log_dir: Path | None = None):
        self.since, self.dir = since, log_dir or session_log_dir()
        self.path: Path | None = None
        self._pos = 0
        self.state: str | None = None
        self.last_error = ''

    def _newest(self) -> Path | None:
        try:
            files = [p for p in self.dir.glob('chiaki_session_*.log') if p.stat().st_mtime >= self.since - 2]
        except OSError:
            return None
        return max(files, key=lambda p: p.stat().st_mtime, default=None)

    def poll(self) -> str | None:
        newest = self._newest()
        if newest and newest != self.path:          # nova sessão (ex.: o chiaki-ng tentou de novo)
            self.path, self._pos, self.state, self.last_error = newest, 0, 'connecting', ''
        if not self.path:
            return None
        try:
            with self.path.open('rb') as f:
                f.seek(self._pos)
                chunk = f.read()
                self._pos += len(chunk)
        except OSError:
            return self.state
        for line in chunk.decode('utf-8', errors='replace').splitlines():
            if any(s in line for s in self.STREAMING):
                self.state = 'streaming'
            elif any(s in line for s in self.QUIT):
                self.state = 'quit'
            elif '] [E] ' in line:
                self.last_error = line.split('] [E] ', 1)[1].strip()[:200]
        return self.state


class ChiakiDriver:
    def __init__(self, path: str, log_dir: Path | None = None):
        self.path = path
        self.log_dir = log_dir or Path(__file__).resolve().parent.parent / 'logs'
        self.proc: subprocess.Popen | None = None
        self.mode: str | None = None              # direct | psn_gui
        self.log_file: Path | None = None
        self.started_at: float | None = None
        self.session_log: SessionLog | None = None    # só no modo PSN (interface aberta)

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
        if self.proc is None or self.proc.poll() is not None:
            return False
        # Modo PSN: a interface continua aberta quando a sessão termina (volta ao menu) — isso é conexão caída.
        return not (self.mode == 'psn_gui' and self.session_state() == 'quit')

    def session_state(self) -> str | None:
        """Modo direto: 'streaming' enquanto o processo vive. Modo PSN: estado lido do log de sessão do chiaki-ng."""
        if self.proc is None or self.proc.poll() is not None:
            return None
        if self.mode != 'psn_gui':
            return 'streaming'
        return self.session_log.poll() if self.session_log else None

    @property
    def streaming(self) -> bool:
        return self.session_state() == 'streaming'

    def session_hint(self) -> str:
        st = self.session_state()
        if st is None:
            return 'o chiaki-ng ainda não iniciou a conexão com o console'
        if st == 'connecting':
            return 'o chiaki-ng está conectando pela PSN (acordando o console/atravessando os roteadores)'
        if st == 'quit':
            err = self.session_log.last_error if self.session_log else ''
            return 'a sessão do chiaki-ng terminou sem transmitir' + (f' (último erro: {err})' if err else '')
        return 'transmitindo'

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

    def start_psn_gui(self, nickname: str, steps: list[str], profile: str = '', platform: str = 'PS4',
                      window_timeout: float = 40.0, sleep=time.sleep) -> str:
        """Abre a interface do chiaki-ng e inicia a conexão via PSN com o console do cadastro. Devolve um resumo.

        PS5: a PSN devolve cada console pelo nome, então a conexão automática nativa (auto_connect_mac → apelido) funciona.
        PS4: a PSN só expõe o "Main PS4 Console" (console principal da conta, nome fixo), que nunca bate com o apelido —
        a conexão automática ficaria presa em "Waiting for console...". Então ela é DESLIGADA nesta abertura e o
        console é escolhido na lista: ↑ a partir do primeiro item dá a volta para o último, que é a entrada da PSN
        (a lista é: consoles da rede local, manuais e, por último, os da PSN).
        """
        if not winutil.IS_WIN:
            raise ChiakiError('O modo PSN (automação da interface) só funciona no Windows.')
        mac = registered_mac(nickname, profile)
        ps5 = str(platform or '').upper() == 'PS5'
        auto = bool(mac) and ps5 and not steps
        if not steps and not auto:
            steps = list(DEFAULT_PS4_PSN_STEPS)
        # Sempre grava: PS5 → este console; PS4 → nenhum (uma conexão automática salva pelo usuário travaria a tela).
        previous = set_autoconnect(mac if auto else None, profile)
        wall = time.time()
        try:
            self._spawn(['--profile', profile] if profile else [], 'psn_gui')
            self.session_log = SessionLog(wall)
            deadline = time.monotonic() + window_timeout
            w = None
            while time.monotonic() < deadline and self.running:
                w = self.window()
                if w:
                    break
                sleep(0.5)
            if not w:
                raise ChiakiError('A janela do chiaki-ng não apareceu. ' + self.log_tail())
        finally:
            sleep(2)                        # o chiaki-ng lê a configuração ao abrir; depois devolve a do usuário
            restore_autoconnect(previous, profile)
        if auto:
            return f'chiaki-ng mandado conectar a "{nickname}" ({mac.hex(":").upper()}) pela PSN.'
        run_key_steps(steps, lambda: self.window(), sleep)
        return f'chiaki-ng: console da PSN escolhido na lista (teclas {", ".join(map(str, steps))}).'

    def stop(self) -> None:
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(8)
            except subprocess.TimeoutExpired:
                p.kill()
        self.mode, self.session_log = None, None


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
