"""Registro de adaptadores por método de conexão escolhido no painel administrativo."""
from .agent_client import ChiakiWebRemotePlayAdapter, DirectRemotePlayAdapter, HdmiCaptureAdapter, NativeRemotePlayAdapter
from .contract import AdapterError, ConsoleStreamingAdapter
from .simulated import SimulatedAdapter

_ADAPTERS: dict[str, ConsoleStreamingAdapter] = {
    'simulated': SimulatedAdapter(),
    'remote_play_chiaki': ChiakiWebRemotePlayAdapter(),
    'remote_play_direct': DirectRemotePlayAdapter(),
    'hdmi_capture': HdmiCaptureAdapter(),
    'native_remote_play': NativeRemotePlayAdapter(),
}

METHODS = [
    {'method': 'remote_play_direct', 'label': 'Remote Play direto — vários consoles por PC (experimental)', 'status': 'experimental',
     'platforms': ['PS4', 'PS5'], 'needs': ['agent', 'internal_host', 'pairing'],
     'guide': 'O ConsoleAgent conecta direto no console pelo protocolo Remote Play, sem chiaki-ng: sem janelas nem monitores, '
              'cada console com o seu próprio controle (vários consoles no mesmo PC). Somente REDE LOCAL: o PC do agente fica '
              'no mesmo lugar dos consoles (cabo de rede recomendado; fixe o IP de cada console no roteador). '
              'Registro único por console: login PSN no agente + PIN de Configurações → Configurações da Conexão de Uso Remoto. '
              'Biblioteca pyremoteplay incorporada (GPL-3.0): requer análise da licença e dos termos da PlayStation.'},
    {'method': 'remote_play_chiaki', 'label': 'Remote Play — Chiaki (experimental)', 'status': 'experimental',
     'platforms': ['PS4', 'PS5'], 'needs': ['agent', 'internal_host', 'pairing'],
     'guide': 'Protocolo Remote Play via ConsoleAgent + chiaki-ng. Habilite o Uso Remoto no console e escolha a rota: '
              'mesma rede do agente (IP interno ou descoberta), internet via PSN (identificação do console) ou internet '
              'com portas abertas (IP público/DDNS). O console precisa estar registrado no chiaki-ng do agente. '
              'Requer análise da licença AGPL-3.0 do chiaki-ng e autorização de uso comercial. Não há compatibilidade com Xbox/Switch.'},
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
