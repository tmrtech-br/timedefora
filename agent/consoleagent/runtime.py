"""Estado e orquestração por console: preparar (acordar + conectar + abrir o jogo), sessão do jogador e testes.

Operações demoradas (acordar e conectar levam de 20 a 60 s) rodam em segundo plano; cada chamada da API
(limite de 5 s) recebe o andamento. A API repete a chamada até o prazo de tolerância.
Nenhum resultado é simulado: sucesso só com imagem real capturada da janela do chiaki-ng.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import discovery, media
from .chiaki import ChiakiDriver, ChiakiError, run_key_steps
from .config import AgentConfig
from .gamepad import GamepadUnavailable, VirtualPad

log = logging.getLogger('consoleagent.runtime')
DIRECT_ROUTES = ('lan', 'internet_port_forward')


@dataclass
class Target:
    console_id: str
    route: str
    host: str | None
    platform: str
    identifier: str
    nickname: str
    regist_key: str = ''
    passcode: str = ''
    profile: str = ''
    psn_gui_steps: list = field(default_factory=list)
    games: dict = field(default_factory=dict)

    @property
    def direct(self) -> bool:
        return self.route in DIRECT_ROUTES


def target_from(cfg: AgentConfig, console_id: str, body: dict) -> Target:
    """Junta o que a API envia (rota/endereço) com o que só o agente guarda (chave de registro, senha, roteiros)."""
    t = body.get('target') or {}
    settings = body.get('settings') or {}
    route = t.get('route') or settings.get('network_route') or body.get('route') or 'lan'
    ident = (t.get('console_identifier') or settings.get('console_identifier') or body.get('console_identifier') or '').strip()
    entry = cfg.consoles.get(ident) or cfg.consoles.get(console_id) or {}
    host = entry.get('host') or t.get('host') or body.get('host')
    if not host and route == 'internet_port_forward':
        host = settings.get('public_host')
    return Target(console_id=console_id, route=route, host=(host or '').strip() or None,
                  platform=(t.get('platform_code') or body.get('platform_code') or entry.get('platform') or 'PS4'),
                  identifier=ident, nickname=(entry.get('nickname') or ident).strip(),
                  regist_key=str(entry.get('regist_key') or ''), passcode=str(entry.get('passcode') or ''),
                  profile=str(entry.get('profile') or ''), psn_gui_steps=list(entry.get('psn_gui_steps') or []),
                  games=dict(entry.get('games') or {}))


@dataclass
class Deps:
    """Dependências trocáveis (os testes usam dublês; nada de hardware)."""
    chiaki: ChiakiDriver
    make_pad: Callable[[], object] = VirtualPad
    frame: Callable = media.frame
    audio: Callable = media.audio_peak
    discover: Callable = discovery.discover
    wake: Callable = discovery.wakeup
    sleep: Callable = time.sleep


class Fail(Exception):
    pass


@dataclass
class Job:
    kind: str                      # connect | prepare
    game_slug: str | None
    state: str = 'running'         # running | ok | failed
    step: str = 'iniciando'
    message: str = ''
    started: float = field(default_factory=time.monotonic)


class ConsoleRuntime:
    def __init__(self, cfg: AgentConfig, deps: Deps):
        self.cfg, self.d = cfg, deps
        self.pad = None
        self.session_id: str | None = None
        self.job: Job | None = None
        self.ready_game: str | None = None       # jogo aberto pela última preparação bem-sucedida
        self._lock = threading.RLock()

    # ------------------------------------------------------------ estado
    @property
    def streaming(self) -> bool:
        return self.d.chiaki.running

    def ensure_pad(self):
        if self.pad is None:
            self.pad = self.d.make_pad()
        return self.pad

    # ------------------------------------------------------------ jobs
    def start_job(self, t: Target, kind: str, game: dict | None = None, wait: float = 3.0) -> Job:
        slug = (game or {}).get('slug')
        with self._lock:
            j = self.job
            reusable = j and j.kind in (kind, 'prepare') and j.game_slug == slug
            if j and j.state == 'running':
                return j                                           # já em andamento
            if reusable and j.state == 'ok' and self.streaming:
                return j                                           # pronto (idempotente)
            if kind == 'prepare' and self.streaming and self.ready_game is not None and slug == self.ready_game:
                self.job = Job(kind, slug, 'ok', 'pronto', 'Console já conectado com este jogo aberto.')
                return self.job
            self.job = j = Job(kind, slug)
        th = threading.Thread(target=self._run, args=(t, j, game), daemon=True, name=f'job-{kind}-{t.console_id[:8]}')
        th.start()
        th.join(wait)                                              # resposta rápida quando já está tudo pronto
        return j

    def _run(self, t: Target, j: Job, game: dict | None) -> None:
        try:
            j.message = self._bringup(t, j)
            if j.kind == 'prepare':
                j.message += ' ' + self._open_game(t, j, game or {})
            j.state, j.step = 'ok', 'pronto'
        except (Fail, ChiakiError, GamepadUnavailable, ValueError, OSError) as e:
            j.state, j.message = 'failed', f'{j.step}: {e}'
            log.warning('preparação falhou (%s): %s', t.identifier or t.console_id, j.message)
        except Exception as e:  # nunca derrubar o agente
            j.state, j.message = 'failed', f'{j.step}: erro inesperado {e.__class__.__name__}: {e}'
            log.exception('erro inesperado na preparação')

    def _bringup(self, t: Target, j: Job) -> str:
        ch, cfg = self.d.chiaki, self.cfg
        j.step = 'verificando o chiaki-ng'
        if not ch.available:
            raise Fail(f'chiaki-ng não encontrado em {ch.path}.')
        if not t.nickname:
            raise Fail('Identificação do console não informada (cadastro do console no painel).')
        if self.streaming:
            j.step = 'conferindo a imagem'
            f = self.d.frame(ch.pid)
            if f.ok:
                self.ensure_pad()
                return f'Console já conectado. {f.message}'
            ch.stop()                                              # processo aberto sem imagem: reinicia
        reg = ch.registered(t.nickname)
        if reg is False:
            raise Fail(f'"{t.nickname}" não está registrado no chiaki-ng deste PC. Registre o console no chiaki-ng '
                       '(mesmo apelido do cadastro) e tente de novo.')
        notes = [] if reg else ['(não foi possível listar os consoles do chiaki-ng)']

        if t.direct:
            if not t.host:
                raise Fail('Endereço do console não informado (IP na rede local ou IP público/DDNS).')
            notes.append(self._wake(t, j))
        else:
            notes.append('Rota PSN: o console deve estar ligado ou em repouso com o Remote Play ativado.')

        j.step = 'criando o controle virtual'
        self.ensure_pad()

        j.step = 'abrindo o chiaki-ng'
        if t.direct:
            ch.start_direct(t.nickname, t.host, t.passcode, t.profile)
        else:
            ch.start_psn_gui(t.psn_gui_steps, t.profile, sleep=self.d.sleep)

        j.step = 'aguardando a imagem do console'
        deadline = time.monotonic() + float(cfg.stream_timeout_seconds)
        last = None
        while time.monotonic() < deadline:
            if not ch.running:
                raise Fail('O chiaki-ng fechou antes de transmitir. ' + (ch.log_tail() or 'Veja agent/logs.'))
            last = self.d.frame(ch.pid)
            if last.ok:
                return ' '.join(x for x in [*notes, f'Conectado. {last.message}'] if x)
            self.d.sleep(2)
        raise Fail('Sem imagem do console dentro do prazo. ' + (last.message if last else ''))

    def _wake(self, t: Target, j: Job) -> str:
        j.step = 'procurando o console'
        found = self.d.discover(t.host, t.platform, self.cfg.discovery_timeout_seconds)
        state = found[0].state if found else None
        if state == 'ligado':
            return 'Console ligado.'
        if not t.regist_key:
            if state == 'em repouso':
                raise Fail('Console em repouso e sem "regist_key" no config.json do agente para acordá-lo.')
            raise Fail(f'Console não respondeu em {t.host} (desligado, fora da rede ou porta bloqueada).')
        j.step = 'acordando o console'
        self.d.wake(t.host, t.regist_key, t.platform)
        deadline = time.monotonic() + float(self.cfg.wake_timeout_seconds)
        while time.monotonic() < deadline:
            self.d.sleep(3)
            found = self.d.discover(t.host, t.platform, self.cfg.discovery_timeout_seconds)
            if found and found[0].state == 'ligado':
                self.d.sleep(5)                                  # o Remote Play sobe alguns segundos depois
                return 'Console acordado.'
        raise Fail('O console não ligou após o comando de acordar (confira "Ativar ligar o PS4 pela rede" e a chave de registro).')

    def _open_game(self, t: Target, j: Job, game: dict) -> str:
        slug, title = game.get('slug'), game.get('title') or game.get('slug') or 'jogo'
        steps = t.games.get(slug) if slug else None
        if not steps:
            self.ready_game = slug
            if self.cfg.require_game_script:
                raise Fail(f'Sem roteiro para abrir "{title}" (games.{slug} no config.json do agente).')
            return f'Jogo "{title}": sem roteiro de abertura configurado; confirme na tela que ele está aberto.'
        j.step = f'abrindo "{title}"'
        pad = self.ensure_pad()
        run_pad_steps(pad, steps, self.d.sleep)
        self.d.sleep(2)
        f = self.d.frame(self.d.chiaki.pid)
        if not f.ok:
            raise Fail(f'Após o roteiro de "{title}" a imagem sumiu: {f.message}')
        self.ready_game = slug
        return f'Roteiro de abertura de "{title}" executado ({len(steps)} passos).'

    # ------------------------------------------------------------ sessão do jogador
    def start_session(self, session_id: str) -> tuple[bool, str]:
        if not self.streaming:
            return False, 'Console não está conectado (a preparação não terminou).'
        f = self.d.frame(self.d.chiaki.pid)
        if not f.ok:
            return False, f.message
        pad = self.ensure_pad()
        pad.reset()
        self.session_id = session_id
        return True, f'Sessão liberada. {f.message}'

    def input(self, session_id: str, command: dict) -> None:
        if not session_id or session_id != self.session_id:
            raise PermissionError('Controle revogado ou sessão diferente da ativa neste console.')
        self.ensure_pad().apply(command)

    def revoke(self, session_id: str | None = None) -> None:
        if session_id and self.session_id and session_id != self.session_id:
            return                                                   # pedido de outra sessão: não afeta a atual
        self.session_id = None
        if self.pad is not None:
            self.pad.reset()

    def disconnect(self) -> None:
        self.revoke()
        self.d.chiaki.stop()
        self.ready_game, self.job = None, None
        if self.pad is not None:
            try:
                self.pad.close()
            finally:
                self.pad = None


def run_pad_steps(pad, steps: list, sleep=time.sleep) -> None:
    """Roteiro interno: nomes de botão ("ps", "cross", "dpad_right"), "wait:N" ou "hold:botão:segundos"."""
    for raw in steps:
        s = str(raw).strip().lower()
        if s.startswith('wait:'):
            sleep(float(s.split(':', 1)[1]))
        elif s.startswith('hold:'):
            _, name, secs = s.split(':')
            pad.press(name, float(secs))
        else:
            pad.press(s)
        sleep(0.4)
