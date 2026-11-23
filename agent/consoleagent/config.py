"""Configuração do agente (arquivo JSON local; nunca versionado porque contém tokens)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / 'config.json'
DEFAULT_CHIAKI = r'C:\Program Files\chiaki-ng\chiaki.exe'


class ConfigError(Exception):
    pass


@dataclass
class AgentConfig:
    api_url: str                         # URL da API LocaPlay (ex.: http://127.0.0.1:8000)
    agent_token: str                     # agente → API (heartbeat). Gerado no painel.
    api_to_agent_token: str              # API → agente (comandos). Gerado no painel.
    listen_host: str = '127.0.0.1'       # em produção: atrás de HTTPS (proxy/túnel)
    listen_port: int = 8765
    heartbeat_seconds: int = 30
    discovery_timeout_seconds: float = 2.0
    chiaki_path: str = DEFAULT_CHIAKI
    # ---- Parte 2: dados que só o agente guarda, por console (chave = identificação do console no painel, ex.: "PS4-118")
    #   {"nickname": apelido no chiaki-ng, "regist_key": chave de registro (hex) para acordar,
    #    "passcode": senha de 4 dígitos do console (opcional), "profile": perfil do chiaki-ng (opcional),
    #    "host": endereço (opcional; sobrepõe o do painel), "psn_gui_steps": roteiro de teclas (rota PSN),
    #    "games": {"slug-do-jogo": ["ps", "wait:2", "dpad_right", "cross"]}}
    consoles: dict = field(default_factory=dict)
    wake_timeout_seconds: float = 60.0
    stream_timeout_seconds: float = 60.0
    stop_chiaki_after_session: bool = False    # padrão: mantém a conexão para o próximo jogador
    require_game_script: bool = False          # True: sem roteiro de abertura do jogo a preparação falha
    control_test_button: str = ''              # botão "inofensivo" apertado no teste de controles (vazio = teste não aprova)
    extra: dict = field(default_factory=dict)

    @property
    def chiaki_found(self) -> bool:
        return bool(self.chiaki_path) and Path(self.chiaki_path).is_file()


def load(path: str | os.PathLike | None = None) -> AgentConfig:
    p = Path(path or os.getenv('LOCAPLAY_AGENT_CONFIG') or DEFAULT_PATH)
    if not p.is_file():
        raise ConfigError(f'Arquivo de configuração não encontrado: {p}. Copie config.example.json para config.json e preencha.')
    try:
        raw = json.loads(p.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        raise ConfigError(f'config.json inválido: {e}') from e
    missing = [k for k in ('api_url', 'agent_token', 'api_to_agent_token') if not str(raw.get(k) or '').strip()
               or str(raw.get(k)).startswith('COLE_')]
    if missing:
        raise ConfigError('Preencha em config.json: ' + ', '.join(missing) + ' (tokens em Painel → Agentes e dispositivos → Rotacionar tokens).')
    known = {f for f in AgentConfig.__dataclass_fields__ if f != 'extra'}
    cfg = AgentConfig(**{k: v for k, v in raw.items() if k in known})
    cfg.extra = {k: v for k, v in raw.items() if k not in known}
    cfg.api_url = cfg.api_url.rstrip('/')
    if not (1 <= int(cfg.listen_port) <= 65535):
        raise ConfigError('listen_port inválida.')
    if int(cfg.heartbeat_seconds) < 5:
        raise ConfigError('heartbeat_seconds deve ser >= 5.')
    if not isinstance(cfg.consoles, dict) or not all(isinstance(v, dict) for v in cfg.consoles.values()):
        raise ConfigError('"consoles" deve ser um objeto: {"PS4-118": {"nickname": ..., "regist_key": ...}}.')
    for name, c in cfg.consoles.items():
        key = str(c.get('regist_key') or '').strip().lower()
        if key and (len(key) > 16 or any(ch not in '0123456789abcdef' for ch in key)):
            raise ConfigError(f'consoles.{name}.regist_key inválida (texto hexadecimal, ex.: 2ebf539d).')
        pc = str(c.get('passcode') or '')
        if pc and not (len(pc) == 4 and pc.isdigit()):
            raise ConfigError(f'consoles.{name}.passcode deve ter 4 dígitos.')
    return cfg
