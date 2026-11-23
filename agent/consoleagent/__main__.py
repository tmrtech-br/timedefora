"""python -m consoleagent [--config caminho] [--discover IP|broadcast] [--platform PS4|PS5]
                         [--list] [--check CONSOLE --route lan|internet_port_forward|internet_psn --host ENDEREÇO]"""
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
    ap.add_argument('--platform', default='PS4', help='PS4 ou PS5 (para --discover)')
    ap.add_argument('--list', action='store_true', help='mostra os consoles registrados no chiaki-ng deste PC e sai')
    ap.add_argument('--check', metavar='CONSOLE', help='teste completo local (acordar, conectar, imagem, áudio) do console '
                                                       'configurado em "consoles" no config.json; ex.: --check PS4-118')
    ap.add_argument('--route', default='lan', choices=['lan', 'internet_port_forward', 'internet_psn'], help='rota para --check')
    ap.add_argument('--host', help='endereço do console para --check (IP local ou IP público/DDNS)')
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


def _check(cfg, args) -> int:
    """Executa o mesmo fluxo da API (conectar + testes) direto no terminal, mostrando cada etapa."""
    import time

    from .chiaki import ChiakiDriver
    from .runtime import ConsoleRuntime, Deps, target_from
    from .server import _test_controls, _test_video_audio

    body = {'target': {'route': args.route, 'host': args.host, 'platform_code': args.platform, 'console_identifier': args.check}}
    t = target_from(cfg, 'local-check', body)
    print(f'Console {t.identifier} · apelido no chiaki-ng "{t.nickname}" · rota {t.route} · endereço {t.host or "(PSN)"}')
    r = ConsoleRuntime(cfg, Deps(chiaki=ChiakiDriver(cfg.chiaki_path)))
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
    input('Enter para desconectar e sair… ')
    r.disconnect()
    return 0


if __name__ == '__main__':
    sys.exit(main())
