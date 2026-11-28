"""Teste de bancada: o login Remote Play aceita o escopo mobile (presença PSN)?

Não altera o agente nem o cofre: o token obtido fica só na memória deste processo e é descartado no fim.
Uso (PowerShell, na raiz do repositório, com o Python do agente):
    & "$env:LOCALAPPDATA\\Timedefora\\agent-venv\\Scripts\\python.exe" .\\docs\\testar_escopo_mobile.py
"""
import asyncio
from getpass import getpass
import json
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlparse
import webbrowser

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from remoteplay.psn import oauth  # noqa: E402
import testar_presenca_psn as sonda  # noqa: E402

MOBILE = 'psn:mobile.v2.core'
CONTROLE = '--controle' in sys.argv          # mesmo login do cadastro, sem a permissão nova (prova de controle)
SCOPE = oauth.SCOPE if CONTROLE else oauth.SCOPE + ' ' + MOBILE


def autorizar_url() -> str:
    url = oauth.login_url()
    return url.replace('scope=' + oauth.SCOPE.replace(' ', '+').replace(':', '%3A'),
                       'scope=' + SCOPE.replace(' ', '+').replace(':', '%3A'))


async def trocar_codigo(client: httpx.AsyncClient, code: str) -> dict:
    res = await client.post(oauth.TOKEN_URL, auth=(oauth.CLIENT_ID, oauth.CLIENT_SECRET), timeout=20,
                            data={'grant_type': 'authorization_code', 'code': code, 'scope': SCOPE,
                                  'redirect_uri': oauth.REDIRECT},
                            headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        data = res.json()
    except ValueError:
        data = {}
    if res.status_code != 200 or not data.get('access_token'):
        erro = data.get('error') if isinstance(data, dict) else None
        raise SystemExit(f'A Sony recusou a troca do código (HTTP {res.status_code}, erro: {erro}).')
    return data


async def main() -> int:
    url = autorizar_url()
    if CONTROLE:
        print('PROVA DE CONTROLE: login igual ao do cadastro, sem a permissão de presença.' + chr(10))
    elif MOBILE.replace(':', '%3A') not in url:
        print('Não foi possível montar a URL de login com o escopo mobile.')
        return 1
    print('1) Vai abrir o login da Sony no navegador (o mesmo do cadastro, pedindo também a permissão de presença).')
    print('   Se não abrir, copie este endereço no navegador:\n   ' + url + '\n')
    webbrowser.open(url)
    print('2) Entre com a conta de teste. A Sony vai para uma página em branco ou de erro do Remote Play.')
    print('   Copie o endereço COMPLETO dessa página (barra de endereços) e cole abaixo. Ele não aparece na tela.')
    redirect = getpass('   Endereço da página de retorno: ').strip()
    q = parse_qs(urlparse(redirect).query)
    if q.get('error'):
        print(f"\nRESULTADO: a Sony recusou o pedido no login: {q['error'][0]} — {q.get('error_description', [''])[0]}")
        print('O escopo mobile não é concedido a este login. Caminho 2 encerrado.')
        return 2
    try:
        code = oauth.parse_redirect(redirect)
    except oauth.OAuthError as e:
        print(f'\n{e}')
        return 1
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
        data = await trocar_codigo(client, code)
        concedido = str(data.get('scope') or '')
        print(f'\nEscopos concedidos pela Sony: {concedido or "(não informado)"}')
        token = str(data['access_token'])
        conta = await oauth.account_info(client, token)
        account_id = sonda.id_decimal(conta['account_id'])
        print(f"Conta: {conta['online_id']}")
        res = await client.get(f'{sonda.BASE_URL}/basicPresences', params={**sonda.PARAMS, 'accountIds': account_id},
                               headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'}, timeout=10)
        if CONTROLE:
            print(chr(10) + f'RESULTADO DO CONTROLE: login normal funcionou; presença deu HTTP {res.status_code}.')
            print('Se o teste com a permissão nova deu "Algo deu errado", a causa é a permissão de presença.')
            return 0
        if res.status_code != 200:
            try:
                err = res.json().get('error', {})
                msg = err.get('message') if isinstance(err, dict) else None
            except ValueError:
                msg = None
            print(f'\nRESULTADO: presença recusada (HTTP {res.status_code}: {msg}).')
            return 2
        print('\nRESULTADO: PRESENÇA LIBERADA. Primeira leitura:')
        print(json.dumps(sonda.extrair_presenca(res.json(), account_id, token), ensure_ascii=False))
        print('\n3) Agora monitorando por 10 minutos (só mudanças). Faça no PS4: repouso -> acordar -> perfil -> Far Cry 5.')
        print('   Ctrl+C para parar.\n')
    return await sonda.consultar(account_id, token)


if __name__ == '__main__':
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
