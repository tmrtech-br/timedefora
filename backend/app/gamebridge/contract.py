"""Contrato versionado ConsoleStreamingAdapter (v1).

Mapeamento para os nomes do prompt: discoverConsole→discover_console, pairConsole→pair_console,
connect, startStream→start_stream, stopStream→stop_stream, getStreamStatus→get_stream_status,
getMetrics→get_metrics, sendInput→send_input, revokeInput→revoke_input, disconnect, healthCheck→health_check.
Também há equivalentes TypeScript em frontend/src/lib/gamebridge.ts (somente tipos).
"""
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum

CONTRACT_VERSION = '1.0'


class StreamState(str, Enum):
    IDLE = 'idle'
    CONNECTING = 'connecting'
    STREAMING = 'streaming'
    DEGRADED = 'degraded'
    STOPPED = 'stopped'
    ERROR = 'error'
    UNAVAILABLE = 'unavailable'


class AdapterError(Exception):
    """Códigos: not_implemented, not_configured, agent_unreachable, agent_error,
    input_revoked, invalid_session, unsupported_platform."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class ConsoleRef:
    console_id: str
    platform_code: str
    method: str
    agent_endpoint: str | None = None
    agent_token: str | None = None       # nunca exposto ao jogador
    internal_host: str | None = None
    capture_device_identifier: str | None = None
    control_adapter_identifier: str | None = None
    settings: dict = field(default_factory=dict)


@dataclass
class StreamMetrics:
    """Valores REAIS medidos ou None ("não disponível"). Nunca fabricar números."""
    fps: float | None = None
    bitrate_kbps: float | None = None
    rtt_ms: float | None = None
    jitter_ms: float | None = None
    packet_loss_pct: float | None = None
    frames_dropped: int | None = None
    input_latency_ms: float | None = None
    simulated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AdapterResult:
    ok: bool
    simulated: bool
    message: str = ''
    state: StreamState | None = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['state'] = self.state.value if self.state else None
        return d


class ConsoleStreamingAdapter(ABC):
    method: str = ''
    label: str = ''
    simulated: bool = False
    operational: bool = False  # True somente quando validado com hardware real

    @abstractmethod
    def discover_console(self, ref: ConsoleRef) -> AdapterResult: ...
    @abstractmethod
    def pair_console(self, ref: ConsoleRef, code: str | None) -> AdapterResult: ...
    @abstractmethod
    def connect(self, ref: ConsoleRef) -> AdapterResult: ...
    @abstractmethod
    def start_stream(self, ref: ConsoleRef, session_id: str) -> AdapterResult: ...
    @abstractmethod
    def stop_stream(self, ref: ConsoleRef, session_id: str) -> AdapterResult: ...
    @abstractmethod
    def get_stream_status(self, ref: ConsoleRef, session_id: str) -> AdapterResult: ...
    @abstractmethod
    def get_metrics(self, ref: ConsoleRef, session_id: str | None = None) -> StreamMetrics: ...
    @abstractmethod
    def send_input(self, ref: ConsoleRef, session_id: str, command: dict) -> AdapterResult: ...
    @abstractmethod
    def revoke_input(self, ref: ConsoleRef, session_id: str) -> AdapterResult: ...
    @abstractmethod
    def disconnect(self, ref: ConsoleRef) -> AdapterResult: ...
    @abstractmethod
    def health_check(self, ref: ConsoleRef) -> AdapterResult: ...

    # Testes administrativos (vídeo/áudio/controle) — por padrão usam health/connect.
    def test_video_audio(self, ref: ConsoleRef) -> AdapterResult:
        raise AdapterError('not_implemented', 'Teste de imagem e áudio não implementado para este método.')

    def test_controls(self, ref: ConsoleRef) -> AdapterResult:
        raise AdapterError('not_implemented', 'Teste de controles não implementado para este método.')

    def webrtc_offer(self, ref: ConsoleRef, session_id: str, offer: dict) -> AdapterResult:
        """Vídeo/áudio do console para o navegador: recebe a oferta SDP e devolve a resposta em data {'sdp','type'}."""
        raise AdapterError('not_implemented', 'Vídeo no navegador não disponível para este método de conexão.')

    def prepare_console(self, ref: ConsoleRef, game: dict) -> AdapterResult:
        """Antes da sessão: acordar o console e garantir o jogo da reserva aberto (game: id, slug, title)."""
        raise AdapterError('not_implemented', 'Preparação automática do console não implementada para este método.')


ALLOWED_COMMANDS = {
    'button': {'cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l2', 'r2', 'l3', 'r3',
               'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right', 'options', 'share'},
    'axis': {'left_x', 'left_y', 'right_x', 'right_y'},
}
# Comandos sensíveis bloqueados (acesso à tela inicial/loja/configurações do console).
BLOCKED_BUTTONS = {'ps', 'home', 'guide', 'touchpad_settings'}


def validate_command(command: dict) -> dict:
    kind = command.get('type')
    if kind == 'button':
        name = str(command.get('name', '')).lower()
        if name in BLOCKED_BUTTONS:
            raise AdapterError('blocked_command', 'Comando bloqueado por segurança.')
        if name not in ALLOWED_COMMANDS['button']:
            raise AdapterError('invalid_command', f'Botão desconhecido: {name}')
        return {'type': 'button', 'name': name, 'pressed': bool(command.get('pressed', True))}
    if kind == 'axis':
        name = str(command.get('name', '')).lower()
        if name not in ALLOWED_COMMANDS['axis']:
            raise AdapterError('invalid_command', f'Eixo desconhecido: {name}')
        try:
            value = float(command.get('value', 0))
        except (TypeError, ValueError):
            raise AdapterError('invalid_command', 'Valor de eixo inválido.')
        return {'type': 'axis', 'name': name, 'value': max(-1.0, min(1.0, value))}
    raise AdapterError('invalid_command', 'Tipo de comando inválido.')
