"""Compara as duas formas de consultar a presença legada da própria conta."""

import argparse
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from remoteplay.psn.accounts import DEFAULT_PATH, PsnAccountStore


BASE = "https://us-prof.np.community.playstation.net/userProfile/v1/users"
FIELDS = "onlineId,primaryOnlineStatus,presences(@default,@titleInfo,platform,lastOnlineDate,hasBroadcastData)"
INTERVALO = 10
DURACAO = 600
STATUS = ("online", "offline", "busy", "away")
PLATAFORMAS = ("PS3", "PS4", "PS5", "PSVITA", "VITA")


def resumir(payload: dict, online_id: str) -> dict:
    profile = payload["profile"]
    if profile.get("onlineId", "").casefold() != online_id.casefold():
        return {"erro": "perfil divergente ou ausente"}
    primary = profile.get("primaryOnlineStatus")
    presences = []
    for item in profile.get("presences") or []:
        status = item.get("onlineStatus")
        plataforma = item.get("platform")
        title_id = item.get("npTitleId")
        presences.append({
            "status": status if status in STATUS else None,
            "plataforma": plataforma if plataforma in PLATAFORMAS else None,
            "title_id": title_id if isinstance(title_id, str)
            and re.fullmatch(r"(?:CUSA|PPSA)\d{5}(?:_\d{2})?", title_id) else None,
        })
    return {"status_primario": primary if primary in STATUS else None, "presencas": presences}


async def consultar(client: httpx.AsyncClient, alvo: str, online_id: str) -> dict:
    try:
        async with asyncio.timeout(4):
            response = await client.get(f"{BASE}/{alvo}/profile2", params={"fields": FIELDS})
        estado = {"http": response.status_code}
        if response.status_code == 200:
            try:
                estado.update(resumir(response.json(), online_id))
            except (ValueError, KeyError, TypeError, AttributeError):
                estado["erro"] = "formato de resposta inesperado"
        return estado
    except (TimeoutError, httpx.RequestError):
        return {"erro": "transporte"}


async def monitorar(token: str, online_id: str) -> int:
    loop = asyncio.get_running_loop()
    inicio = loop.time()
    anterior = None
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"},
                                 follow_redirects=False, trust_env=False) as client:
        for segundo in range(0, DURACAO, INTERVALO):
            await asyncio.sleep(max(0, inicio + segundo - loop.time()))
            me = await consultar(client, "me", online_id)
            explicito = (None if me.get("http") in (401, 429)
                         else await consultar(client, online_id, online_id))
            atual = {"me": me, "online_id_explicito": explicito}
            if atual != anterior:
                hora = datetime.now().astimezone().isoformat(timespec="seconds")
                print(json.dumps({"hora": hora, **atual}, ensure_ascii=True), flush=True)
                anterior = atual
            if any(estado and estado.get("http") in (401, 429) for estado in atual.values()):
                return 1
        await asyncio.sleep(max(0, inicio + DURACAO - loop.time()))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registro", help="ID interno da conta no cofre do agente")
    parser.add_argument("--cofre", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    record = PsnAccountStore(args.cofre).get(args.registro) or {}
    online_id = record.get("online_id")
    token = record.get("access_token")
    if not isinstance(online_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", online_id):
        print("Registro ausente ou sem Online ID compatível.", file=sys.stderr)
        return 1
    if not isinstance(token, str) or not token or float(record.get("expires_at") or 0) <= time.time():
        print("Credencial de acesso ausente ou expirada.", file=sys.stderr)
        return 1
    restante = float(record.get("expires_at") or 0) - time.time()
    if restante < DURACAO:
        print(f"Aviso: a credencial vence em {int(restante)} s, antes dos {DURACAO} s do monitor; "
              "um 401 no meio indica só o vencimento.", file=sys.stderr)
    return asyncio.run(monitorar(token, online_id))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        print("Falha no teste. Confira o cofre e o usuário Windows do agente.", file=sys.stderr)
        sys.exit(1)
