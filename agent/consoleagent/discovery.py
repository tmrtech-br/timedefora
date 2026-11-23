"""Descoberta de PS4/PS5 pelo protocolo de descoberta do Remote Play (UDP).

O console responde a uma mensagem "SRCH" com o estado ("200 Ok" = ligado, "620 Server Standby" = repouso),
nome, ID e versão do sistema. Funciona na rede local (IP do console ou broadcast) e pela internet apenas se a
porta UDP de descoberta estiver redirecionada no roteador do console. Não envia credenciais nem altera nada no console.
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field

# Porta e versão do protocolo por família (mesmos valores usados por clientes Remote Play de código aberto).
PROTOCOL = {
    'PS4': {'port': 987, 'version': '00020020'},
    'PS5': {'port': 9302, 'version': '00030010'},
}
STATE = {'200': 'ligado', '620': 'em repouso'}


@dataclass
class ConsoleInfo:
    address: str
    state: str                  # ligado | em repouso | desconhecido
    status_code: str
    host_name: str | None = None
    host_id: str | None = None
    host_type: str | None = None
    system_version: str | None = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {'address': self.address, 'state': self.state, 'status_code': self.status_code, 'host_name': self.host_name,
                'host_id': self.host_id, 'host_type': self.host_type, 'system_version': self.system_version}


def family(platform_code: str | None) -> str:
    return 'PS5' if (platform_code or '').upper().startswith('PS5') else 'PS4'


def search_message(platform_code: str | None) -> bytes:
    v = PROTOCOL[family(platform_code)]['version']
    return f'SRCH * HTTP/1.1\ndevice-discovery-protocol-version:{v}\n'.encode()


def parse_response(data: bytes, address: str) -> ConsoleInfo | None:
    """Interpreta a resposta do console. Retorna None se não for uma resposta de descoberta válida."""
    try:
        text = data.decode('utf-8', errors='replace')
    except Exception:
        return None
    lines = [ln.strip() for ln in text.replace('\r', '').split('\n') if ln.strip()]
    if not lines or not lines[0].startswith('HTTP/1.1 '):
        return None
    parts = lines[0].split(' ', 2)
    code = parts[1] if len(parts) > 1 else ''
    headers: dict[str, str] = {}
    for ln in lines[1:]:
        if ':' in ln:
            k, v = ln.split(':', 1)
            headers[k.strip().lower()] = v.strip()
    if 'host-id' not in headers and 'host-type' not in headers:
        return None
    return ConsoleInfo(address=address, state=STATE.get(code, 'desconhecido'), status_code=code,
                       host_name=headers.get('host-name'), host_id=headers.get('host-id'),
                       host_type=headers.get('host-type'), system_version=headers.get('system-version'), raw=headers)


def wakeup_message(regist_key: str, platform_code: str | None) -> bytes:
    """Mensagem WAKEUP do Remote Play. A credencial é a chave de registro (hex, ex.: "2ebf539d") como número.

    É o mesmo pacote que o chiaki-ng envia ao clicar em "Acordar": o console em repouso liga se a chave
    pertencer a um aparelho registrado nele. Sem a chave correta o console simplesmente ignora.
    """
    key = (regist_key or '').strip().lower().rstrip('\x00')
    if not key or any(ch not in '0123456789abcdef' for ch in key) or len(key) > 16:
        raise ValueError('Chave de registro inválida (esperado texto hexadecimal, ex.: 2ebf539d).')
    credential = int(key, 16)
    v = PROTOCOL[family(platform_code)]['version']
    return (f'WAKEUP * HTTP/1.1\nclient-type:vr\nauth-type:R\nmodel:w\napp-type:r\n'
            f'user-credential:{credential}\ndevice-discovery-protocol-version:{v}\n').encode()


def wakeup(host: str, regist_key: str, platform_code: str | None = 'PS4', port: int | None = None, attempts: int = 3) -> None:
    """Envia o WAKEUP (UDP, sem resposta). Confirme depois com discover() até o estado virar "ligado"."""
    if not host:
        raise ValueError('Endereço do console não informado.')
    msg = wakeup_message(regist_key, platform_code)
    target_port = int(port or PROTOCOL[family(platform_code)]['port'])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for _ in range(max(1, attempts)):
            s.sendto(msg, (host, target_port))
            time.sleep(0.1)


def discover(host: str | None, platform_code: str | None = 'PS4', timeout: float = 2.0, port: int | None = None,
             attempts: int = 2) -> list[ConsoleInfo]:
    """Envia SRCH ao host (ou broadcast quando host é None/255.255.255.255) e coleta as respostas."""
    fam = family(platform_code)
    target_port = int(port or PROTOCOL[fam]['port'])
    target = host or '255.255.255.255'
    broadcast = target == '255.255.255.255'
    msg = search_message(platform_code)
    found: dict[str, ConsoleInfo] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        if broadcast:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(('', 0))
        deadline = time.monotonic() + timeout
        for _ in range(max(1, attempts)):
            try:
                s.sendto(msg, (target, target_port))
            except OSError:
                break
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            s.settimeout(remaining)
            try:
                data, (addr, _p) = s.recvfrom(4096)
            except (socket.timeout, TimeoutError):
                break
            except OSError:
                break
            info = parse_response(data, addr)
            if info:
                found[info.host_id or addr] = info
            if not broadcast and found:
                break
    return list(found.values())
