"""Estado e orquestração por console: preparar (acordar + conectar + abrir o jogo), sessão do jogador e testes.

Operações demoradas (acordar e conectar levam de 20 a 60 s) rodam em segundo plano; cada chamada da API
(limite de 5 s) recebe o andamento. A API repete a chamada até o prazo de tolerância.
Nenhum resultado é simulado: sucesso só com imagem real do console (captura da janela ou quadro decodificado).
A conversa com o console fica num "link" (links.py): chiaki-ng ou Remote Play direto.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import discovery
from .chiaki import ChiakiError
from .config import AgentConfig
from .gamepad import GamepadUnavailable
from .links import LinkError

log = logging.getLogger('consoleagent.runtime')
DIRECT_ROUTES = ('lan', 'internet_port_forward')
PSN_NO_SESSION_SECONDS = 45      # chiaki-ng aberto sem sessão nenhuma após isso = tentativa perdida
PSN_RETRY_GAP_SECONDS = 15


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
    psn_user: str = ''              # Remote Play direto: conta PSN usada (vazio = a registrada no console)
    psn_account_id: str = ''
    mac: str = ''
    resolution: str = '720p'
    fps: int = 30
    bitrate_kbps: int = 0           # 0 = padrão do método (Remote Play pela PSN usa 6 Mbps)
    codec: str = 'h264'

    @property
    def direct(self) -> bool:
        return self.route in DIRECT_ROUTES


def target_from(cfg: AgentConfig, console_id: str, body: dict) -> Target:
    """Junta o que a API envia (rota/endereço/qualidade) com o que só o agente guarda (chave, senha, roteiros)."""
    t = body.get('target') or {}
    settings = body.get('settings') or {}
    route = t.get('route') or settings.get('network_route') or body.get('route') or 'lan'
    ident = (t.get('console_identifier') or settings.get('console_identifier') or body.get('console_identifier') or '').strip()
    entry = cfg.consoles.get(ident) or cfg.consoles.get(console_id) or {}
    host = entry.get('host') or t.get('host') or body.get('host')
    if not host and route == 'internet_port_forward':
        host = settings.get('public_host')
    try:
        fps = int(t.get('fps') or settings.get('fps') or 30)
    except (TypeError, ValueError):
        fps = 30
    try:
        bitrate = int(t.get('bitrate_kbps') or settings.get('bitrate_kbps') or 0)
    except (TypeError, ValueError):
        bitrate = 0
    return Target(console_id=console_id, route=route, host=(host or '').strip() or None,
                  platform=(t.get('platform_code') or body.get('platform_code') or entry.get('platform') or 'PS4'),
                  identifier=ident, nickname=(entry.get('nickname') or ident).strip(),
                  regist_key=str(entry.get('regist_key') or ''), passcode=str(entry.get('passcode') or ''),
                  profile=str(entry.get('profile') or ''), psn_gui_steps=list(entry.get('psn_gui_steps') or []),
                  games=dict(entry.get('games') or {}), psn_user=str(entry.get('psn_user') or ''),
                  psn_account_id=str(t.get('psn_account_id') or settings.get('psn_account_id') or ''),
                  mac=str(entry.get('mac') or ''), resolution=str(t.get('resolution') or settings.get('resolution') or '720p'),
                  fps=fps, codec=str(t.get('codec') or settings.get('codec') or 'h264'), bitrate_kbps=max(0, bitrate))


@dataclass
class Deps:
    """Dependências trocáveis (os testes usam dublês; nada de hardware)."""
    link: object
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

    @property
    def link(self):
        return self.d.link

    # ------------------------------------------------------------ estado
    @property
    def streaming(self) -> bool:
        return self.link.running

    def ensure_pad(self):
        if self.pad is None:
            self.pad = self.link.new_pad()
        return self.pad

    def _drop_pad(self):
        if self.pad is not None:
            try:
                self.pad.close()
            except Exception:
                pass
            self.pad = None

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
        except (Fail, ChiakiError, LinkError, GamepadUnavailable, ValueError, OSError) as e:
            j.state, j.message = 'failed', f'{j.step}: {e}'
            log.warning('preparação falhou (%s): %s', t.identifier or t.console_id, j.message)
        except Exception as e:  # nunca derrubar o agente
            j.state, j.message = 'failed', f'{j.step}: erro inesperado {e.__class__.__name__}: {e}'
            log.exception('erro inesperado na preparação')

    def _bringup(self, t: Target, j: Job) -> str:
        link, cfg = self.link, self.cfg
        j.step = 'verificando a conexão do agente'
        if not link.available:
            raise Fail(link.unavailable_reason or 'Forma de conexão indisponível neste agente.')
        if link.kind == 'chiaki' and not t.nickname:
            raise Fail('Identificação do console não informada (cadastro do console no painel).')
        if self.streaming:
            j.step = 'conferindo a imagem'
            f = link.frame()
            if f.ok:
                self.ensure_pad()
                return f'Console já conectado. {f.message}'
            self._drop_pad()
            link.stop()                                            # conectado sem imagem: reinicia
        notes: list[str] = []
        if link.kind == 'chiaki':                                  # no modo direto o registro é conferido ao conectar
            reg = link.registered(t)
            if reg is False:
                raise Fail(f'"{t.nickname}" não está registrado no chiaki-ng deste PC. Registre o console no chiaki-ng '
                           '(mesmo apelido do cadastro) e tente de novo.')
            if reg is None:
                notes.append('(não foi possível listar os consoles do chiaki-ng)')

        if t.direct:
            if not t.host:
                raise Fail('Endereço do console não informado (IP na rede local ou IP público/DDNS).')
            notes.append(self._wake(t, j))
        else:
            notes.append('Rota PSN: o console deve estar ligado ou em repouso com o Remote Play ativado.')

        self._drop_pad()
        if link.kind == 'chiaki':
            j.step = 'criando o controle virtual'
            self.ensure_pad()                                      # o chiaki-ng precisa ver o controle ao abrir
        # Pela PSN a conexão (descoberta pela Sony + atravessar os roteadores) leva bem mais que na rede local, e a
        # primeira tentativa costuma falhar quando o console está em repouso (ele acorda durante ela): tenta de novo.
        psn = t.route == 'internet_psn'
        attempts = max(1, int(cfg.psn_connect_attempts)) if psn else 1
        wait = float(cfg.stream_timeout_seconds) * (2 if psn else 1)
        why = ''
        for attempt in range(1, attempts + 1):
            j.step = 'conectando ao console' + (f' (tentativa {attempt} de {attempts})' if attempts > 1 else '')
            try:
                started = link.start(t, self.d.sleep)
            except LinkError as e:
                # Pela PSN o próprio link negocia até a 1ª imagem: a falha dele também precisa de nova tentativa
                # (console em repouso acorda durante a 1ª e quase sempre a perde).
                if not psn or attempt >= attempts or not getattr(e, 'retryable', True):
                    raise
                why = str(e)
                log.info('rota PSN: tentativa %s falhou (%s); tentando de novo', attempt, why)
                link.stop()
                self.d.sleep(PSN_RETRY_GAP_SECONDS)
                continue
            if started:
                notes.append(started)
            if link.kind != 'chiaki':
                j.step = 'criando o controle'
                self.ensure_pad()                                  # direto: o controle pertence à sessão
            j.step = 'aguardando a imagem do console' + (f' (tentativa {attempt} de {attempts})' if attempts > 1 else '')
            deadline = time.monotonic() + wait
            last = None
            while time.monotonic() < deadline:
                if not link.running:
                    why = 'A conexão com o console caiu antes de transmitir. ' + (
                        (link.stream_hint() if psn and hasattr(link, 'stream_hint') else '') or link.log_tail() or 'Veja agent/logs.')
                    break
                if psn and getattr(link, 'stalled', None) and link.stalled(PSN_NO_SESSION_SECONDS):
                    why = (f'O chiaki-ng não iniciou a conexão em {PSN_NO_SESSION_SECONDS} s (ficou no menu ou em '
                           '"Waiting for console"). Confira no chiaki-ng se "Main PS4 Console" aparece na lista da PSN.')
                    break
                last = link.frame()
                if last.ok:
                    if attempt > 1:
                        notes.append(f'Conectou na tentativa {attempt}.')
                    return ' '.join(x for x in [*notes, f'Conectado. {last.message}'] if x)
                self.d.sleep(2)
            else:
                why = 'Sem imagem do console dentro do prazo. ' + (last.message if last else '')
            if attempt < attempts:
                log.info('rota PSN: tentativa %s falhou (%s); tentando de novo', attempt, why)
                link.stop()
                # A PSN leva alguns segundos para apagar a sessão anterior; reabrir logo dá "Holepunch session was
                # deleted on PSN server" / "Failed to create session".
                self.d.sleep(PSN_RETRY_GAP_SECONDS)
        raise Fail(why)

    def _wake(self, t: Target, j: Job) -> str:
        j.step = 'procurando o console'
        found = self.d.discover(t.host, t.platform, self.cfg.discovery_timeout_seconds)
        state = found[0].state if found else None
        if state == 'ligado':
            return 'Console ligado.'
        key = self.link.regist_key(t)
        if not key:
            if state == 'em repouso':
                raise Fail('Console em repouso e sem chave de registro para acordá-lo (pareie o console ou preencha "regist_key").')
            raise Fail(f'Console não respondeu em {t.host} (desligado, fora da rede ou porta bloqueada).')
        j.step = 'acordando o console'
        self.d.wake(t.host, key, t.platform)
        deadline = time.monotonic() + float(self.cfg.wake_timeout_seconds)
        while time.monotonic() < deadline:
            self.d.sleep(3)
            found = self.d.discover(t.host, t.platform, self.cfg.discovery_timeout_seconds)
            if found and found[0].state == 'ligado':
                self.d.sleep(5)                                  # o Remote Play sobe alguns segundos depois
                return 'Console acordado.'
        raise Fail('O console não ligou após o comando de acordar (confira "Ativar ligar o console pela rede" e a chave de registro).')

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
        f = self.link.frame()
        if not f.ok:
            raise Fail(f'Após o roteiro de "{title}" a imagem sumiu: {f.message}')
        self.ready_game = slug
        return f'Roteiro de abertura de "{title}" executado ({len(steps)} passos).'

    # ------------------------------------------------------------ sessão do jogador
    def start_session(self, session_id: str) -> tuple[bool, str]:
        if not self.streaming:
            return False, 'Console não está conectado (a preparação não terminou).'
        # A conexão com o console basta: tela preta/carregando/aviso aberto no momento não pode travar o jogador
        # (a imagem foi validada na preparação; aqui ela é só informativa).
        f = self.link.frame()
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
            try:
                self.pad.reset()
            except Exception as e:
                log.warning('falha ao soltar os controles: %s', e)

    def disconnect(self) -> None:
        self.revoke()
        self._drop_pad()
        self.link.stop()
        self.ready_game, self.job = None, None

    def standby(self) -> tuple[bool, str]:
        """Fim de sessão com hibernação: solta os controles, pede repouso ao console e encerra a conexão."""
        if self.job and self.job.state == 'running':
            return False, 'Conexão/preparação em andamento: o console não foi colocado em repouso.'
        self.revoke()
        self._drop_pad()
        fn = getattr(self.link, 'standby', None)
        ok = False
        if fn is not None and self.streaming:
            try:
                ok = bool(fn())
            except Exception as e:  # repouso é melhor esforço: nunca impede o encerramento
                log.warning('falha ao pedir repouso ao console: %s', e)
        self.link.stop()
        self.ready_game, self.job = None, None
        if fn is None:
            return False, 'Este método de conexão não coloca o console em repouso; conexão encerrada.'
        return ok, 'Console colocado em repouso.' if ok else 'O console não confirmou o repouso; conexão encerrada.'


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
