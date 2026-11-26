# SPDX-License-Identifier: AGPL-3.0-only
"""Consulta REAL de PS5 pelo endpoint PSN documentado no Chiaki-ng.

Fonte: chiaki-ng/lib/src/remote/holepunch.c:chiaki_holepunch_list_devices.
O PS4 principal exige fluxo próprio; NÃO é inventado como se a API o listasse.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

PS5_CLIENTS = ('https://web.np.playstation.com/api/cloudAssistedNavigation/v2/users/me/clients'
               '?platform=PS5&includeFields=device&limit=10&offset={offset}')


class DeviceDiscoveryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PsnDevice:
    platform: str
    duid: str
    name: str
    remoteplay_enabled: bool


def parse_ps5_clients(json_data: dict) -> list[PsnDevice]:
    if not isinstance(json_data, dict) or not isinstance(json_data.get('clients'), list):
        raise DeviceDiscoveryUnavailable('Resposta de dispositivos PSN inválida: campo clients ausente.')
    result = []
    for raw in json_data['clients']:
        if not isinstance(raw, dict) or not isinstance(raw.get('device'), dict):
            raise DeviceDiscoveryUnavailable('Registro de console Sony incompleto.')
        duid, device = raw.get('duid'), raw['device']
        name, features = device.get('name'), device.get('enabledFeatures')
        if not isinstance(duid, str) or not duid or not isinstance(name, str) or not isinstance(features, list):
            raise DeviceDiscoveryUnavailable('DUID, nome ou recursos do console ausentes na Sony.')
        if len(duid) > 128 or len(duid) % 2 or any(ch not in '0123456789abcdefABCDEF' for ch in duid):
            raise DeviceDiscoveryUnavailable('DUID da Sony com formato inválido.')
        result.append(PsnDevice('PS5', duid.lower(), name[:80], 'remotePlay' in features))
    return result


async def list_psn_devices(client, access_token: str) -> list[dict]:
    if not access_token:
        raise DeviceDiscoveryUnavailable('Conta não autenticada na Sony.')
    unique = {}
    for offset in (0, 10, 20):  # limite defensivo: 30 consoles, 3 chamadas
        try:
            response = await client.get(PS5_CLIENTS.format(offset=offset), timeout=8.0,
                                        headers={'Authorization': f'Bearer {access_token}', 'Accept-Language': 'jp'})
            response.raise_for_status()
            devices = parse_ps5_clients(response.json())
        except DeviceDiscoveryUnavailable:
            raise
        except Exception as exc:
            # Não enviar dados sensíveis/corpo HTTP; retornos de erro são genéricos.
            raise DeviceDiscoveryUnavailable('Não foi possível consultar os PS5 da conta na Sony. Renove o login e tente novamente.') from exc
        for device in devices:
            unique[device.duid] = asdict(device)
        if len(devices) < 10:
            break
    return list(unique.values())
