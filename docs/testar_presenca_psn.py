"""Consulta de presença PSN para o teste de bancada, sem renovar o cofre."""

import argparse
import asyncio
import base64
from datetime import datetime
from getpass import GetPassWarning, getpass
import json
import logging
from pathlib import Path
import re
import sys
import time
import warnings

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from remoteplay.psn.accounts import DEFAULT_PATH, PsnAccountStore


BASE_URL = "https://m.np.playstation.com/api/userProfile/v2/internal/users"
PARAMS = {
    "type": "primary",
    "platforms": "PS4,PS5,MOBILE_APP,PSPC",
    "withOwnGameTitleInfo": "true",
}
INTERVALO = 5
DURACAO = 600


def id_decimal(account_id: str) -> str:
    raw = base64.b64decode(account_id, validate=True)
    if len(raw) != 8:
        raise ValueError("ID do cofre deve representar oito bytes.")
    return str(int.from_bytes(raw, "little"))


def extrair_presenca(payload: object, account_id: str, token: str) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("basicPresences"), list):
        raise ValueError("Formato de presença inesperado.")
    presence = next((item for item in payload["basicPresences"]
                     if isinstance(item, dict) and item.get("accountId") == account_id), {})
    primary = presence.get("primaryPlatformInfo", {})
    titles = presence.get("gameTitleInfoList", [])
    if not isinstance(primary, dict) or not isinstance(titles, list):
        raise ValueError("Campos de presença inesperados.")
    status = primary.get("onlineStatus")
    games = set()
    for title in titles:
        if not isinstance(title, dict):
            raise ValueError("Entrada de título inesperada.")
        title_id = title.get("npTitleId")
        if not isinstance(title_id, str) or not re.fullmatch(r"(?:CUSA|PPSA)\d{5}(?:_\d{2})?", title_id):
            continue
        name = title.get("titleName")
        if not isinstance(name, str) or token in name:
            name = ""
        games.add((title_id.split("_", 1)[0], name))
    return {
        "online": {"online": True, "offline": False}.get(status) if isinstance(status, str) else None,
        "jogos": [{"title_id": title_id, "nome": name or None} for title_id, name in sorted(games)],
    }


async def consultar(account_id: str, token: str) -> int:
    loop = asyncio.get_running_loop()
    inicio = loop.time()
    anterior = None
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for segundo in range(0, DURACAO, INTERVALO):
            await asyncio.sleep(max(0, inicio + segundo - loop.time()))
            try:
                async with asyncio.timeout(inicio + segundo + INTERVALO - loop.time()):
                    response = await client.get(f"{BASE_URL}/basicPresences",
                                                params={**PARAMS, "accountIds": account_id})
                if response.status_code in (400, 401, 403, 404, 429):
                    print(f"Consulta encerrada (HTTP {response.status_code}).", file=sys.stderr)
                    return 1
                if response.status_code == 200:
                    atual = extrair_presenca(response.json(), account_id, token)
                else:
                    atual = {"erro_http": response.status_code}
            except (TimeoutError, httpx.RequestError):
                atual = {"erro": "transporte"}
            except ValueError:
                atual = {"erro": "resposta inesperada"}
            if atual != anterior:
                hora = datetime.now().astimezone().isoformat(timespec="seconds")
                print(json.dumps({"hora": hora, **atual}, ensure_ascii=True), flush=True)
                anterior = atual
        await asyncio.sleep(max(0, inicio + DURACAO - loop.time()))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registro", help="ID interno da conta vinculada no cofre do agente")
    parser.add_argument("--cofre", type=Path, default=DEFAULT_PATH, help="Caminho do cofre DPAPI")
    parser.add_argument("--token-presenca", action="store_true",
                        help="Lê sem eco um token de presença autorizado da mesma conta")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    record = PsnAccountStore(args.cofre).get(args.registro)
    if not record:
        print("Registro ausente no cofre.", file=sys.stderr)
        return 1
    account_id = id_decimal(record.get("account_id"))
    if args.token_presenca:
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            token = getpass("Token de presença autorizado: ").strip()
    else:
        token = record.get("access_token")
        if float(record.get("expires_at") or 0) <= time.time():
            print("Token do cofre expirado. Renove pelo fluxo normal do agente.", file=sys.stderr)
            return 1
    if not isinstance(token, str) or not token or not token.isascii() or any(c.isspace() for c in token):
        print("Token de acesso ausente ou inválido.", file=sys.stderr)
        return 1
    return asyncio.run(consultar(account_id, token))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        print("Falha no teste. Confira o cofre, o usuário Windows e o terminal interativo.", file=sys.stderr)
        sys.exit(1)
