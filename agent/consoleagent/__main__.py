"""python -m consoleagent [--config caminho]                       → roda o agente
   --discover IP|broadcast [--platform PS4|PS5]                     → procura consoles e sai
   --list                                                           → consoles registrados no chiaki-ng
   --psn-login                                                      → vincula uma conta PSN ao agente (Remote Play direto)
   --pair CONSOLE --host IP --pin 12345678                          → registra o console no agente (Remote Play direto)
   --check CONSOLE --mode direct|chiaki --route ... --host IP       → teste completo local (conectar, imagem, áudio, controle)
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import VERSION, discovery
from .config import ConfigError, load


def main() -> int:
    ap = argparse.ArgumentParser(prog='consoleagent', description='LocaPlay ConsoleAgent')
    ap.add_argument('--config', help='caminho do config.json (padrão: agent/config.json)')
    ap.add_argument('--discover', metavar='IP', help='só procura o console (IP ou "broadcast") e sai; não precisa de config')
    ap.add_argument('--platform', default='PS4', help='PS4 ou PS5 (para --discover/--check)')
    ap.add_argument('--list', action='store_true', help='mostra os consoles registrados no chiaki-ng deste PC e sai')
    ap.add_argument('--psn-login', action='store_true', help='vincula uma conta PSN ao agente (necessário para o Remote Play direto)')
    ap.add_argument('--psn-redirect', metavar='URL', help='conclui o login PSN com o endereço final copiado do navegador (sem prompt)')
    ap.add_argument('--pair', metavar='CONSOLE', help='registra o console no agente com o PIN (Remote Play direto)')
    ap.add_argument('--pin', help='PIN de 8 dígitos exibido no console (para --pair)')
    ap.add_argument('--check', metavar='CONSOLE', help='teste completo local do console; ex.: --check PS4-118')
    ap.add_argument('--mode', default='direct', choices=['direct', 'chiaki'], help='forma de conexão para --check (padrão: direct)')
    ap.add_argument('--route', default='lan', choices=['lan', 'internet_port_forward', 'internet_psn'], help='rota para --check')
    ap.add_argument('--host', help='endereço do console (IP na rede local; para chiaki pela internet: IP público/DDNS)')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%H:%M:%S')

    if args.discover:
        host = None if args.discover.lower() == 'broadcast' else args.discover
        found = discovery.discover(host, args.platform, timeout=3.0)
        if not found:
            print(f'Nenhum {args.platform} respondeu em {args.discover}.')
            return 1
        for c in found:
            print(f'{c.host_name} ({c.host_type}) em {c.address}: {c.state} · sistema {c.system_version} · id {c.host_id}')
        return 0

    if args.psn_login or args.psn_redirect:
        return _psn_login(args.psn_redirect)

    try:
        cfg = load(args.config)
    except ConfigError as e:
        print(f'ERRO: {e}', file=sys.stderr)
        return 2

    if args.list:
        from .chiaki import ChiakiDriver
        hosts = ChiakiDriver(cfg.chiaki_path).list_hosts()
        if hosts is None:
            print(f'Não foi possível consultar o chiaki-ng em {cfg.chiaki_path}.')
            return 1
        print('Consoles registrados no chiaki-ng: ' + (', '.join(hosts) if hosts else 'nenhum'))
        return 0

    if args.pair:
        return _pair(cfg, args)

    if args.check:
        return _check(cfg, args)

    import uvicorn

    from .heartbeat import Heartbeat
    from .server import create_app

    hb = Heartbeat(cfg)
    hb.start()
    logging.getLogger('consoleagent').info('ConsoleAgent %s em http://%s:%s · API %s · chiaki-ng %s', VERSION, cfg.listen_host,
                                           cfg.listen_port, cfg.api_url, 'encontrado' if cfg.chiaki_found else 'não encontrado')
    try:
        uvicorn.run(create_app(cfg), host=cfg.listen_host, port=int(cfg.listen_port), log_level='warning')
    finally:
        hb.stop()
    return 0


def _psn_login(redirect: str | None = None) -> int:
    """Login PSN uma única vez: o agente guarda só o ID da conta (não guarda a senha nem o token)."""
    from .links import LinkError, load_profiles, profiles_path
    try:
        profiles = load_profiles()
        from pyremoteplay.oauth import get_login_url
    except LinkError as e:
        print(f'ERRO: {e}')
        return 2
    if redirect:
        url = redirect.strip()
    else:
        print('1) Abra este endereço no navegador e entre com a conta PSN que está logada no console:\n')
        print('   ' + get_login_url() + '\n')
        print('2) Depois do login a página fica em branco/"redirect". Copie o ENDEREÇO COMPLETO da barra do navegador e cole aqui.')
        url = input('Endereço: ').strip()
    user = profiles.new_user(url, save=True)
    if not user:
        print('Não foi possível vincular a conta (endereço inválido ou expirado). Tente de novo.')
        return 1
    print(f'Conta PSN "{user.name}" vinculada. Dados em {profiles_path()} (nunca compartilhe esse arquivo).')
    return 0


def _pair(cfg, args) -> int:
    from .links import DirectLink
    from .runtime import target_from
    if not args.host or not args.pin:
        print('Informe --host (IP do console) e --pin (8 dígitos exibidos no console).')
        return 2
    t = target_from(cfg, 'local-pair', {'target': {'route': 'lan', 'host': args.host, 'platform_code': args.platform,
                                                   'console_identifier': args.pair}})
    ok, msg = DirectLink().pair(t, args.pin)
    print(('OK: ' if ok else 'FALHOU: ') + msg)
    return 0 if ok else 1


def _check(cfg, args) -> int:
    """Executa o mesmo fluxo da API (conectar + testes) direto no terminal, mostrando cada etapa."""
    import time

    from .links import ChiakiLink, DirectLink
    from .runtime import ConsoleRuntime, Deps, target_from
    from .server import _test_controls, _test_video_audio

    body = {'target': {'route': args.route, 'host': args.host, 'platform_code': args.platform, 'console_identifier': args.check}}
    t = target_from(cfg, 'local-check', body)
    link = DirectLink() if args.mode == 'direct' else ChiakiLink(cfg.chiaki_path)
    print(f'Console {t.identifier} · modo {"Remote Play direto" if args.mode == "direct" else "chiaki-ng"} · rota {t.route} · '
          f'endereço {t.host or "(PSN)"}')
    r = ConsoleRuntime(cfg, Deps(link=link))
    j = r.start_job(t, 'connect', wait=0)
    last = None
    while j.state == 'running':
        if j.step != last:
            print(f'  … {j.step}')
            last = j.step
        time.sleep(0.5)
    print(('OK: ' if j.state == 'ok' else 'FALHOU: ') + j.message)
    if j.state != 'ok':
        return 1
    for name, fn in (('Imagem e áudio', lambda: _test_video_audio(r)), ('Controles', lambda: _test_controls(cfg, r))):
        res = fn()
        print(f'{name}: {"OK" if res["ok"] else "NÃO APROVADO"} — {res["message"]}')
    if sys.stdin and sys.stdin.isatty():
        input('Enter para desconectar e sair… ')
    else:
        time.sleep(float(getattr(args, 'hold', 0) or 0))
    r.disconnect()
    return 0


if __name__ == '__main__':
    sys.exit(main())
