"""Estado do console sem olhar a imagem: conta online e jogo aberto (title ID).

Duas fontes, na ordem:
1. Presença PSN pela internet (rota legada profile2), com o mesmo token do Remote Play já salvo no cofre do agente.
   Validado em PS4 real (28/11/2026): abertura e fechamento do jogo aparecem na mesma leitura que o DDP local.
   Exige o perfil do console com status "Online" (com "aparecer offline" a Sony informa sempre offline).
2. DDP na rede local (UDP 987/9302), quando o console está na mesma rede do agente.
O title ID aparece no início do carregamento do jogo, não quando o menu do jogo já está pronto.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

log = logging.getLogger('consoleagent.presence')
PROFILE2 = ('https://us-prof.np.community.playstation.net/userProfile/v1/users/me/profile2'
            '?fields=onlineId,primaryOnlineStatus,presences(@default,@titleInfo,platform,lastOnlineDate)')
TITLE_RE = re.compile(r'^((?:CUSA|PPSA|PCJS|PLJS|PLAS|PCAS|ELJM|ELAS)\d{5})(?:_\d{2})?$')


def normalize_title(value: str | None) -> str:
    """CUSA05904_00 -> CUSA05904; qualquer outra coisa -> ''."""
    m = TITLE_RE.match((value or '').strip().upper())
    return m.group(1) if m else ''


@dataclass
class Presence:
    online: bool | None          # None = desconhecido (fonte não informa)
    title_id: str = ''
    title_name: str = ''
    source: str = ''             # psn | lan


def parse_profile2(payload: dict) -> Presence:
    profile = payload.get('profile') if isinstance(payload, dict) else None
    if not isinstance(profile, dict):
        raise ValueError('resposta sem perfil')
    items = [p for p in profile.get('presences') or [] if isinstance(p, dict)]
    item = next((p for p in items if p.get('npTitleId')), items[0] if items else {})
    status = item.get('onlineStatus') or profile.get('primaryOnlineStatus')
    online = None if status is None else status != 'offline'
    return Presence(online, normalize_title(item.get('npTitleId')), str(item.get('titleName') or '')[:120], 'psn')


class PsnPresence:
    """Lê a presença da conta PSN vinculada ao console (registro do cofre do agente = id da conta no painel)."""

    def __init__(self, record_id: str, store=None, fetch=None):
        self.record_id = record_id
        self._store, self._fetch = store, fetch      # fetch(url) -> (status, json|None); dublê nos testes

    async def _default_fetch(self, url: str):
        import httpx
        from remoteplay.psn.accounts import DEFAULT_PATH, shared_store
        from remoteplay.psn.oauth import request_token
        store = self._store or shared_store(DEFAULT_PATH)
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            token = await store.access_token(self.record_id, lambda r: request_token(client, refresh_token=r))
            r = await client.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=8)
            return r.status_code, (r.json() if r.status_code == 200 else None)

    def read(self) -> Presence | None:
        """Presença atual; None quando a Sony não respondeu (nunca tratar como "offline")."""
        try:
            status, body = asyncio.run((self._fetch or self._default_fetch)(PROFILE2))
        except Exception as e:
            log.info('presença PSN indisponível: %s', e.__class__.__name__)
            return None
        if status != 200 or not isinstance(body, dict):
            log.info('presença PSN: HTTP %s', status)
            return None
        try:
            return parse_profile2(body)
        except ValueError:
            return None


class StateReader:
    """Junta PSN e rede local. Prefere a PSN (funciona em qualquer rede); a rede local completa quando a PSN falha."""

    def __init__(self, psn: PsnPresence | None = None, lan=None):
        self.psn, self.lan = psn, lan             # lan: objeto com running_app() -> (title_id, nome), ex.: runtime.System
        self._lan_ok = lan is not None

    @property
    def available(self) -> bool:
        return self.psn is not None or self._lan_ok

    def read(self) -> Presence | None:
        p = self.psn.read() if self.psn else None
        if p is not None:
            return p
        if self._lan_ok:
            try:
                code, name = self.lan.running_app()
                return Presence(None, normalize_title(code), name or '', 'lan')
            except Exception:
                self._lan_ok = False               # console fora da rede local: não tenta de novo nesta preparação
        return None
