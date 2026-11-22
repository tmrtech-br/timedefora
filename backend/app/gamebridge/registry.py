"""Registro de adaptadores por método de conexão escolhido no painel administrativo."""
from .agent_client import ChiakiWebRemotePlayAdapter, HdmiCaptureAdapter, NativeRemotePlayAdapter
from .contract import AdapterError, ConsoleStreamingAdapter
from .simulated import SimulatedAdapter

_ADAPTERS: dict[str, ConsoleStreamingAdapter] = {
    'simulated': SimulatedAdapter(),
    'remote_play_chiaki': ChiakiWebRemotePlayAdapter(),
    'hdmi_capture': HdmiCaptureAdapter(),
    'native_remote_play': NativeRemotePlayAdapter(),
}

METHODS = [
    {'method': 'remote_play_chiaki', 'label': 'Remote Play — Chiaki (experimental)', 'status': 'experimental',
     'platforms': ['PS4', 'PS5'], 'needs': ['agent', 'internal_host', 'pairing'],
     'guide': 'Usa a rede local e o protocolo Remote Play. Habilite Remote Play no console, informe o IP interno, '
              'inicie o pareamento pelo agente e digite o código exibido no console. Requer análise da licença '
              'AGPL-3.0 do Chiaki-NG e autorização de uso comercial. Não há compatibilidade com Xbox/Switch.'},
    {'method': 'hdmi_capture', 'label': 'Placa de captura HDMI', 'status': 'requires_hardware',
     'platforms': ['PS4', 'PS5', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'], 'needs': ['agent', 'capture_device', 'control_adapter'],
     'guide': 'A capturadora recebe apenas vídeo e áudio; é obrigatório um canal de controle separado e autorizado. '
              'Cada console precisa de uma entrada de captura independente (saída HDMI de notebook não é captura). '
              'Respeite HDCP/DRM — conteúdo protegido não deve ser capturado.'},
    {'method': 'native_remote_play', 'label': 'GameBridge Native (futuro)', 'status': 'not_operational',
     'platforms': ['PS4', 'PS5'], 'needs': [], 'guide': 'Componente próprio futuro. Não operacional.'},
    {'method': 'simulated', 'label': 'Simulador (desenvolvimento)', 'status': 'simulated',
     'platforms': ['PS4', 'PS5', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH'], 'needs': [],
     'guide': 'Não conecta a nenhum console. Usado para testes e demonstração, sempre identificado como simulado.'},
    {'method': 'unconfigured', 'label': 'Não configurado', 'status': 'unavailable', 'platforms': [], 'needs': [],
     'guide': 'Console cadastrado, porém indisponível para publicação e vendas.'},
]


def get_adapter(method: str) -> ConsoleStreamingAdapter:
    try:
        return _ADAPTERS[method]
    except KeyError:
        raise AdapterError('not_configured', 'Console sem método de conexão configurado.')


def method_info(method: str) -> dict | None:
    return next((m for m in METHODS if m['method'] == method), None)
