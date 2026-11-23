"""python -m consoleagent [--config caminho] [--discover IP|broadcast] [--platform PS4|PS5]"""
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


if __name__ == '__main__':
    sys.exit(main())
